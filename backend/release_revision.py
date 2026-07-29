"""Shared release-revision stamps for API and ACA rinse-scheduler.

Both deployables must expose the same source / build / artifact / expected
fields so post-cutover observation can prove revision agreement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _read_artifact_file() -> str:
    for candidate in (
        Path(__file__).resolve().parent / "release_revision.json",
        Path(__file__).resolve().parent.parent / "release_revision.json",
    ):
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                sha = str((data or {}).get("sha") or "").strip()
                if sha:
                    return sha
        except Exception:
            continue
    return ""


def load_release_revision_stamps() -> dict[str, Any]:
    source_revision = (
        os.environ.get("SOURCE_RELEASE_SHA")
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("GIT_SHA")
        or ""
    ).strip()
    build_revision = (
        os.environ.get("BUILD_SHA")
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("GIT_SHA")
        or ""
    ).strip()
    artifact_revision = (
        os.environ.get("ARTIFACT_SHA") or _read_artifact_file() or ""
    ).strip()
    runtime_revision = (artifact_revision or build_revision or source_revision).strip()
    expected_revision = (os.environ.get("EXPECTED_RELEASE_SHA") or "").strip()
    image_revision = (
        os.environ.get("SCHEDULER_IMAGE_SHA")
        or os.environ.get("IMAGE_GIT_SHA")
        or artifact_revision
        or build_revision
        or ""
    ).strip()
    stamped = [
        v
        for v in (source_revision, build_revision, artifact_revision, runtime_revision)
        if v
    ]
    stamp_agreement = len(set(stamped)) <= 1 if stamped else True
    expected_ok = (not expected_revision) or (
        expected_revision == runtime_revision or expected_revision == artifact_revision
    )
    return {
        "source_revision": source_revision or None,
        "build_revision": build_revision or None,
        "artifact_revision": artifact_revision or None,
        "runtime_revision": runtime_revision or None,
        "expected_revision": expected_revision or None,
        "image_revision": image_revision or None,
        "revision_stamp_agreement": stamp_agreement,
        "expected_revision_match": expected_ok,
        "build_time": (os.environ.get("BUILD_TIME") or "").strip() or None,
    }
