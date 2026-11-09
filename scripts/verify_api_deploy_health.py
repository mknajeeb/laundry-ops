#!/usr/bin/env python3
"""Require a deployed API revision before the deploy job succeeds.

Package upload is not success. This probe does not restart the app. It waits
through old-process responses and startup timeouts until a deadline, and fails
immediately once the expected SHA is serving an unhealthy health payload.

Success requires all of:
- HTTP 200
- the expected deployed SHA
- revision_stamp_agreement is true
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

READY = "ready"
OLD_PROCESS = "old_process"
STARTING = "starting"
UNHEALTHY = "unhealthy"

DEFAULT_DEADLINE_SECONDS = 600
DEFAULT_WARMUP_SECONDS = 45
DEFAULT_INTERVAL_SECONDS = 15
DEFAULT_REQUEST_TIMEOUT = 20
DEFAULT_MAX_ATTEMPTS = 36
DEFAULT_UNHEALTHY_LIMIT = 2


def classify_health_response(
    *,
    http_status: int,
    body_text: str,
    expected_sha: str,
    transport_error: str | None = None,
) -> tuple[str, dict]:
    """Classify one /health probe.

    old_process: a different revision is still answering.
    starting: timeout, gateway error, or a body that is not a revision yet.
    unhealthy: the expected revision is answering, but it is not ready.
    ready: HTTP 200, expected SHA, status ok, and stamp agreement.
    """
    expected = (expected_sha or "").strip()
    if transport_error or http_status == 0:
        return STARTING, {"reason": transport_error or "no_response"}

    text = body_text or ""
    if http_status in (502, 504) or not text.strip():
        return STARTING, {"reason": f"http_{http_status}" if http_status else "empty_body"}

    try:
        body = json.loads(text)
    except Exception:
        return STARTING, {"reason": "non_json", "http_status": http_status}
    if not isinstance(body, dict):
        return STARTING, {"reason": "non_object", "http_status": http_status}

    runtime = str(body.get("runtime_revision") or "").strip()
    source = str(body.get("source_revision") or "").strip()
    build = str(body.get("build_revision") or "").strip()
    artifact = str(body.get("artifact_revision") or "").strip()
    git_sha = str(body.get("git_sha") or "").strip()
    serving = runtime or artifact or git_sha
    reported = (runtime, source, build, artifact, git_sha)
    serves_expected = bool(expected) and expected in reported
    agreement = body.get("revision_stamp_agreement") is True
    status = str(body.get("status") or "")
    detail = {
        "http_status": http_status,
        "status": status,
        "serving": serving,
        "agreement": body.get("revision_stamp_agreement"),
    }

    if (
        http_status == 200
        and status == "ok"
        and serves_expected
        and agreement
        and serving == expected
    ):
        return READY, detail
    if serving and expected and serving != expected:
        return OLD_PROCESS, detail
    if serves_expected:
        return UNHEALTHY, detail
    return STARTING, {"reason": "no_revision", **detail}


def summarize_failure(observations: list[dict], expected_sha: str, deadline_seconds: int) -> str:
    """Turn probe history into one old-process, startup, or unhealthy failure."""
    unhealthy = [item for item in observations if item["kind"] == UNHEALTHY]
    if unhealthy:
        last = unhealthy[-1]["detail"]
        return (
            "unhealthy deployment: expected SHA is serving but /health is not ready "
            f"(http={last.get('http_status')} status={last.get('status')} "
            f"agreement={last.get('agreement')})"
        )

    old = [item for item in observations if item["kind"] == OLD_PROCESS]
    starting = [item for item in observations if item["kind"] == STARTING]
    if old:
        serving = old[-1]["detail"].get("serving")
        if observations and observations[-1]["kind"] == STARTING:
            return (
                "startup timeout: the previous process was still serving "
                f"{serving} and the new process did not become ready before the "
                f"{deadline_seconds}s deadline "
                f"(startup_responses={len(starting)} old_process_responses={len(old)})"
            )
        return (
            "old-process SHA mismatch: production is still serving "
            f"{serving}; expected {expected_sha} before the {deadline_seconds}s deadline"
        )
    return (
        "startup timeout: /health did not return HTTP 200 with the deployed SHA "
        f"and revision-stamp agreement before the {deadline_seconds}s deadline "
        f"(startup_responses={len(starting)})"
    )


def poll_health(
    fetch,
    *,
    expected_sha: str,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    warmup_seconds: int = DEFAULT_WARMUP_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    unhealthy_limit: int = DEFAULT_UNHEALTHY_LIMIT,
    sleep=time.sleep,
    now=time.monotonic,
) -> tuple[int, str, list[dict]]:
    """Poll until ready, the deadline, or a confirmed unhealthy revision.

    Returns (exit_code, message, observations). Exit 0 only when classify
    returns ready. This function never restarts the app.
    """
    started = now()
    deadline = started + max(1, int(deadline_seconds))
    if warmup_seconds > 0 and now() < deadline:
        sleep(min(warmup_seconds, max(0, deadline - now())))

    observations: list[dict] = []
    consecutive_unhealthy = 0
    attempts = 0
    while attempts < max_attempts and now() < deadline:
        attempts += 1
        http_status, body_text, transport_error = fetch()
        kind, detail = classify_health_response(
            http_status=http_status,
            body_text=body_text,
            expected_sha=expected_sha,
            transport_error=transport_error,
        )
        observations.append({"kind": kind, "detail": detail, "attempt": attempts})
        print(
            f"health attempt {attempts}: class={kind} http={http_status} detail={detail}",
            flush=True,
        )
        if kind == READY:
            message = f"Verified production /health reports agreed revision {expected_sha}"
            print(message, flush=True)
            return 0, message, observations
        if kind == UNHEALTHY:
            consecutive_unhealthy += 1
            if consecutive_unhealthy >= unhealthy_limit:
                message = summarize_failure(observations, expected_sha, deadline_seconds)
                print(f"::error::{message}", flush=True)
                return 1, message, observations
        else:
            consecutive_unhealthy = 0
        remaining = deadline - now()
        if remaining <= 0 or attempts >= max_attempts:
            break
        sleep(min(interval_seconds, remaining))

    message = summarize_failure(observations, expected_sha, deadline_seconds)
    print(f"::error::{message}", flush=True)
    return 1, message, observations


def fetch_health(url: str, timeout: int) -> tuple[int, str, str | None]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return int(exc.code), body, None
    except Exception as exc:
        return 0, "", exc.__class__.__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Full /health URL")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--deadline-seconds", type=int, default=DEFAULT_DEADLINE_SECONDS)
    parser.add_argument("--warmup-seconds", type=int, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--request-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--unhealthy-limit", type=int, default=DEFAULT_UNHEALTHY_LIMIT)
    args = parser.parse_args(argv)
    expected = args.expected_sha.strip()
    if len(expected) < 7:
        print("::error::expected SHA is missing", flush=True)
        return 1

    def fetch():
        return fetch_health(args.url, args.request_timeout)

    code, _message, _observations = poll_health(
        fetch,
        expected_sha=expected,
        deadline_seconds=args.deadline_seconds,
        interval_seconds=args.interval_seconds,
        warmup_seconds=args.warmup_seconds,
        max_attempts=args.max_attempts,
        unhealthy_limit=args.unhealthy_limit,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
