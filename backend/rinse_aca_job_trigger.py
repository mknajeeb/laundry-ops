"""
Start the Azure Container Apps scheduled Rinse scrape job from the API host.

Manual Refresh Both Syncs must not run Playwright inside gunicorn; this module
starts the ACA job that already runs scheduled sync with the correct auth mount.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from backend.rinse_bag_export_runner import _parse_env_truthy

ACA_API_VERSION = "2024-03-01"
MANAGEMENT_SCOPE = "https://management.azure.com/"


@dataclass
class AcaJobStartResult:
    ok: bool
    execution_name: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    detail: dict[str, Any] | None = None


def aca_job_trigger_configured() -> bool:
    """True when required Azure job identity settings are present."""
    sub = (os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("RINSE_ACA_SUBSCRIPTION_ID") or "").strip()
    rg = (os.getenv("RINSE_ACA_JOB_RESOURCE_GROUP") or "").strip()
    job = (os.getenv("RINSE_ACA_JOB_NAME") or "rinse-scrape-scheduled").strip()
    return bool(sub and rg and job)


def manual_sync_must_not_run_local_playwright() -> bool:
    """
    API workers must not launch Playwright for manual refresh.

    Enabled on App Service, when remote-only is set, or when ACA dispatch is configured.
    """
    if _parse_env_truthy(os.getenv("RINSE_SCRAPE_REMOTE_ONLY")):
        return True
    if aca_job_trigger_configured() and not _parse_env_truthy(
        os.getenv("RINSE_ACA_MANUAL_SYNC_DISABLED")
    ):
        return True
    try:
        from pathlib import Path

        if Path("/home/site").is_dir():
            return True
    except OSError:
        pass
    return False


def remote_only_user_message() -> str:
    return (
        "Manual scrape runs through the scheduler. "
        "Please wait for the scheduled sync or trigger the scheduler job."
    )


def _job_settings() -> tuple[str, str, str, str]:
    sub = (os.getenv("AZURE_SUBSCRIPTION_ID") or os.getenv("RINSE_ACA_SUBSCRIPTION_ID") or "").strip()
    rg = (os.getenv("RINSE_ACA_JOB_RESOURCE_GROUP") or "").strip()
    job = (os.getenv("RINSE_ACA_JOB_NAME") or "rinse-scrape-scheduled").strip()
    container = (os.getenv("RINSE_ACA_JOB_CONTAINER") or "rinse-scheduler").strip()
    if not sub or not rg or not job:
        raise RuntimeError(
            "ACA job trigger not configured (AZURE_SUBSCRIPTION_ID, RINSE_ACA_JOB_RESOURCE_GROUP, RINSE_ACA_JOB_NAME)"
        )
    return sub, rg, job, container


def _get_management_token() -> str:
    """Managed Identity on App Service/ACA jobs, else client-credentials env vars.

    Container Apps inject IDENTITY_ENDPOINT + IDENTITY_HEADER, not classic VM IMDS.
    """
    resource = urllib.parse.quote(MANAGEMENT_SCOPE, safe="")
    client_id = (os.getenv("AZURE_CLIENT_ID") or os.getenv("RINSE_ACA_MSI_CLIENT_ID") or "").strip()
    identity_endpoint = (os.getenv("IDENTITY_ENDPOINT") or "").strip()
    identity_header = (os.getenv("IDENTITY_HEADER") or "").strip()
    if identity_endpoint and identity_header:
        ident_url = f"{identity_endpoint}?api-version=2019-08-01&resource={resource}"
        if client_id:
            ident_url += f"&client_id={urllib.parse.quote(client_id, safe='')}"
        req = urllib.request.Request(ident_url, headers={"X-IDENTITY-HEADER": identity_header})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                token = payload.get("access_token")
                if token:
                    return str(token)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, OSError):
            pass

    imds_url = (
        "http://169.254.169.254/metadata/identity/oauth2/token"
        f"?api-version=2019-08-01&resource={resource}"
    )
    if client_id:
        imds_url += f"&client_id={urllib.parse.quote(client_id, safe='')}"

    req = urllib.request.Request(imds_url, headers={"Metadata": "true"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            token = payload.get("access_token")
            if token:
                return str(token)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, OSError):
        pass

    tenant = (os.getenv("AZURE_TENANT_ID") or "").strip()
    sp_client = (os.getenv("AZURE_CLIENT_ID") or "").strip()
    secret = (os.getenv("AZURE_CLIENT_SECRET") or "").strip()
    if tenant and sp_client and secret:
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": sp_client,
                "client_secret": secret,
                "resource": MANAGEMENT_SCOPE,
            }
        ).encode("utf-8")
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/token"
        req = urllib.request.Request(
            token_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            token = payload.get("access_token")
            if token:
                return str(token)

    raise RuntimeError(
        "No Azure credentials for ACA job trigger (enable App Service managed identity or set AZURE_* service principal env)"
    )


def _job_start_url(subscription_id: str, resource_group: str, job_name: str) -> str:
    path = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/jobs/{job_name}/start"
    )
    return f"https://management.azure.com{path}?api-version={ACA_API_VERSION}"


def build_job_start_template(
    organization_id: int,
    *,
    run_type: str = "manual",
    container_name: str = "rinse-scheduler",
) -> dict[str, Any]:
    org = int(organization_id)
    # Azure Jobs StartJobExecutionTemplate expects top-level containers[],
    # not a nested template wrapper.
    return {
        "containers": [
            {
                "name": container_name,
                "command": ["/opt/laundry_venv/bin/python"],
                "args": [
                    "-m",
                    "backend.jobs.run_scheduled_rinse_scrape",
                    "--organization-id",
                    str(org),
                    "--run-type",
                    str(run_type or "manual"),
                ],
            }
        ]
    }


def start_rinse_scrape_aca_job(
    organization_id: int,
    *,
    run_type: str = "manual",
) -> AcaJobStartResult:
    """
    POST .../jobs/{name}/start with org-scoped CLI args.

    Duplicate cycles are still guarded by per-org MySQL lock inside the job.
    """
    if not aca_job_trigger_configured():
        return AcaJobStartResult(
            ok=False,
            error_message="ACA job trigger is not configured on this API host",
        )

    try:
        sub, rg, job, container = _job_settings()
        token = _get_management_token()
        url = _job_start_url(sub, rg, job)
        body = json.dumps(
            build_job_start_template(organization_id, run_type=run_type, container_name=container)
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            execution_name = None
            if isinstance(payload, dict):
                execution_name = payload.get("name")
                if not execution_name and isinstance(payload.get("id"), str):
                    execution_name = payload["id"].rstrip("/").split("/")[-1]
            return AcaJobStartResult(
                ok=True,
                execution_name=execution_name,
                http_status=getattr(resp, "status", 200),
                detail=payload if isinstance(payload, dict) else None,
            )
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        message = err_body or str(exc)
        if len(message) > 800:
            message = message[-800:]
        return AcaJobStartResult(
            ok=False,
            error_message=f"ACA job start failed (HTTP {exc.code}): {message}",
            http_status=exc.code,
        )
    except Exception as exc:
        return AcaJobStartResult(
            ok=False,
            error_message=f"ACA job start failed: {exc}",
        )


def _job_url(subscription_id: str, resource_group: str, job_name: str, suffix: str) -> str:
    path = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/jobs/{job_name}{suffix}"
    )
    return f"https://management.azure.com{path}?api-version={ACA_API_VERSION}"


def _azure_json(method: str, url: str, token: str, body: bytes | None = None) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return int(getattr(resp, "status", 200) or 200), payload
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"Azure {method} {url} HTTP {exc.code}: {err_body[-600:]}") from exc


def start_rinse_scrape_chain_job(*, run_type: str = "scheduled") -> AcaJobStartResult:
    """Start the job with its default command (continuous sequential loop)."""
    if not aca_job_trigger_configured():
        return AcaJobStartResult(
            ok=False,
            error_message="ACA job trigger is not configured",
        )
    try:
        sub, rg, job, _container = _job_settings()
        token = _get_management_token()
        url = _job_start_url(sub, rg, job)
        status, payload = _azure_json("POST", url, token, b"{}")
        execution_name = None
        if isinstance(payload, dict):
            execution_name = payload.get("name")
            if not execution_name and isinstance(payload.get("id"), str):
                execution_name = payload["id"].rstrip("/").split("/")[-1]
        return AcaJobStartResult(
            ok=True,
            execution_name=execution_name,
            http_status=status,
            detail=payload if isinstance(payload, dict) else None,
        )
    except Exception as exc:
        return AcaJobStartResult(ok=False, error_message=str(exc))


def list_running_job_executions() -> list[str]:
    if not aca_job_trigger_configured():
        return []
    sub, rg, job, _container = _job_settings()
    token = _get_management_token()
    url = _job_url(sub, rg, job, "/executions")
    _status, payload = _azure_json("GET", url, token)
    names: list[str] = []
    items = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        st = str(props.get("status") or item.get("status") or "")
        if st.lower() != "running":
            continue
        name = item.get("name") or (str(item.get("id") or "").rstrip("/").split("/")[-1])
        if name:
            names.append(str(name))
    return names


def stop_job_execution(execution_name: str) -> bool:
    name = (execution_name or "").strip()
    if not name or not aca_job_trigger_configured():
        return False
    sub, rg, job, _container = _job_settings()
    token = _get_management_token()
    url = _job_url(sub, rg, job, f"/executions/{urllib.parse.quote(name, safe='')}/stop")
    try:
        _azure_json("POST", url, token, b"{}")
        return True
    except Exception:
        return False


def stop_foreign_running_executions(*, keep_execution_name: str | None = None) -> list[str]:
    keep = (keep_execution_name or "").strip()
    if not keep:
        # Never mass-stop when this replica cannot identify itself.
        return []
    stopped: list[str] = []
    for name in list_running_job_executions():
        if name == keep:
            continue
        if stop_job_execution(name):
            stopped.append(name)
    return stopped
