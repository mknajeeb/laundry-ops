"""Deploy health classification. Package upload is not a successful deployment."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_api_deploy_health",
    ROOT / "scripts" / "verify_api_deploy_health.py",
)
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)

EXPECTED = "9e59c6b56100a065bc9d2c12cabf00368ea7a5eb"
OLD = "5700668c90f497354caee3b9c9b29f7a5eb4c685"


def _body(**overrides):
    payload = {
        "status": "ok",
        "runtime_revision": EXPECTED,
        "source_revision": EXPECTED,
        "build_revision": EXPECTED,
        "artifact_revision": EXPECTED,
        "git_sha": EXPECTED,
        "revision_stamp_agreement": True,
    }
    payload.update(overrides)
    import json

    return json.dumps(payload)


def test_ready_requires_http_200_expected_sha_and_agreement():
    kind, _detail = health.classify_health_response(
        http_status=200,
        body_text=_body(),
        expected_sha=EXPECTED,
    )
    assert kind == health.READY

    kind, _detail = health.classify_health_response(
        http_status=503,
        body_text=_body(),
        expected_sha=EXPECTED,
    )
    assert kind == health.UNHEALTHY

    kind, _detail = health.classify_health_response(
        http_status=200,
        body_text=_body(revision_stamp_agreement=False),
        expected_sha=EXPECTED,
    )
    assert kind == health.UNHEALTHY

    kind, _detail = health.classify_health_response(
        http_status=200,
        body_text=_body(revision_stamp_agreement=None),
        expected_sha=EXPECTED,
    )
    assert kind == health.UNHEALTHY


def test_old_process_is_not_treated_as_unhealthy_or_ready():
    kind, detail = health.classify_health_response(
        http_status=503,
        body_text=_body(
            status="unhealthy",
            runtime_revision=OLD,
            source_revision=OLD,
            build_revision=OLD,
            artifact_revision=OLD,
            git_sha=OLD,
            revision_stamp_agreement=False,
        ),
        expected_sha=EXPECTED,
    )
    assert kind == health.OLD_PROCESS
    assert detail["serving"] == OLD


def test_startup_timeout_and_gateway_are_starting():
    kind, detail = health.classify_health_response(
        http_status=0,
        body_text="",
        expected_sha=EXPECTED,
        transport_error="TimeoutError",
    )
    assert kind == health.STARTING
    assert detail["reason"] == "TimeoutError"

    kind, _detail = health.classify_health_response(
        http_status=503,
        body_text="<html>gateway</html>",
        expected_sha=EXPECTED,
    )
    assert kind == health.STARTING


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _poll(responses, **kwargs):
    clock = _Clock()
    seen = {"n": 0}

    def fetch():
        item = responses[min(seen["n"], len(responses) - 1)]
        seen["n"] += 1
        clock.t += item.get("elapsed", 0.1)
        return item["http"], item["body"], item.get("error")

    code, message, observations = health.poll_health(
        fetch,
        expected_sha=EXPECTED,
        deadline_seconds=kwargs.get("deadline_seconds", 100),
        interval_seconds=kwargs.get("interval_seconds", 10),
        warmup_seconds=kwargs.get("warmup_seconds", 0),
        max_attempts=kwargs.get("max_attempts", 10),
        unhealthy_limit=2,
        sleep=clock.sleep,
        now=clock.now,
    )
    return code, message, observations, seen["n"]


def test_poll_waits_through_old_process_and_startup_until_ready():
    ready = {"http": 200, "body": _body()}
    old = {
        "http": 200,
        "body": _body(
            runtime_revision=OLD,
            source_revision=OLD,
            build_revision=OLD,
            artifact_revision=OLD,
            git_sha=OLD,
        ),
    }
    timeout = {"http": 0, "body": "", "error": "TimeoutError", "elapsed": 20}
    code, message, observations, fetches = _poll([old, timeout, ready])
    assert code == 0
    assert EXPECTED in message
    assert [item["kind"] for item in observations] == [
        health.OLD_PROCESS,
        health.STARTING,
        health.READY,
    ]
    assert fetches == 3


def test_poll_fails_fast_on_confirmed_unhealthy_deployment():
    bad = {
        "http": 503,
        "body": _body(status="unhealthy", revision_stamp_agreement=False),
    }
    code, message, observations, fetches = _poll([bad, bad, bad], deadline_seconds=600)
    assert code == 1
    assert message.startswith("unhealthy deployment")
    assert fetches == 2
    assert len(observations) == 2


def test_poll_reports_startup_timeout_when_the_new_process_never_answers():
    old = {
        "http": 200,
        "body": _body(
            runtime_revision=OLD,
            source_revision=OLD,
            build_revision=OLD,
            artifact_revision=OLD,
            git_sha=OLD,
        ),
        "elapsed": 1,
    }
    timeout = {"http": 0, "body": "", "error": "TimeoutError", "elapsed": 20}
    code, message, _observations, _fetches = _poll(
        [old, timeout],
        deadline_seconds=30,
        interval_seconds=5,
        max_attempts=6,
    )
    assert code == 1
    assert message.startswith("startup timeout")
    assert OLD in message


def test_poll_reports_old_process_when_the_previous_sha_keeps_answering():
    old = {
        "http": 200,
        "body": _body(
            runtime_revision=OLD,
            source_revision=OLD,
            build_revision=OLD,
            artifact_revision=OLD,
            git_sha=OLD,
        ),
    }
    code, message, _observations, fetches = _poll(
        [old],
        deadline_seconds=25,
        interval_seconds=10,
        max_attempts=5,
    )
    assert code == 1
    assert message.startswith("old-process SHA mismatch")
    assert OLD in message
    assert fetches >= 2


def test_workflow_health_step_is_required_and_does_not_restart():
    text = (ROOT / ".github" / "workflows" / "main_laundryops-api.yml").read_text(encoding="utf-8")
    marker = "name: Verify API health after deploy"
    assert marker in text
    health_step = text.split(marker, 1)[1]
    assert "verify_api_deploy_health.py" in health_step
    assert "--deadline-seconds 600" in health_step
    assert "--expected-sha" in health_step
    assert "continue-on-error" not in health_step
    assert "az webapp restart" not in health_step
    assert "restart:" not in health_step
    deploy_step = text.split("name: 'Deploy to Azure Web App'", 1)[1].split(marker, 1)[0]
    assert "restart: true" in deploy_step
