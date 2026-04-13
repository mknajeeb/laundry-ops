"""
Run scripts/rinse-cleanertickets/scrape.mjs via Node (Playwright).

Production: install Node + Chromium on the API host, set env in scripts/.env or process env,
and place rinse-auth.json next to the scraper or set RINSE_STORAGE_STATE to an absolute path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scraper_dir() -> Path:
    return _repo_root() / "scripts" / "rinse-cleanertickets"


def scraper_script() -> Path:
    return scraper_dir() / "scrape.mjs"


def node_binary() -> str:
    return (os.getenv("NODE_BIN") or "").strip() or shutil.which("node") or "node"


def export_enabled() -> bool:
    return os.getenv("RINSE_BAG_EXPORT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def scrape_timeout_sec() -> int:
    try:
        return max(60, min(3600, int(os.getenv("RINSE_SCRAPE_TIMEOUT_SEC", "900"))))
    except (TypeError, ValueError):
        return 900


def _node_executable_ok(node: str) -> bool:
    """Use `node --version`; os.access(X_OK) is unreliable on some Azure /home mounts."""
    if not node:
        return False
    if not (os.path.isabs(node) or os.sep in node):
        return bool(shutil.which(node))
    if not os.path.isfile(node):
        return False
    try:
        r = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0 and out.startswith("v")
    except (OSError, subprocess.TimeoutExpired):
        return False


def diagnose() -> dict:
    root = _repo_root()
    sdir = scraper_dir()
    script = scraper_script()
    node = node_binary()
    node_ok = _node_executable_ok(node)
    return {
        "enabled": export_enabled(),
        "repo_root": str(root),
        "scraper_dir": str(sdir),
        "scraper_script_exists": script.is_file(),
        "node_path": node,
        "node_found": node_ok,
    }


def run_bag_export_csv(output_path: Path) -> tuple[int, str, str]:
    """
    Run scrape.mjs with OUTPUT_CSV set to output_path (absolute).
    Returns (exit_code, stdout, stderr).
    """
    sdir = scraper_dir()
    script = scraper_script()
    if not script.is_file():
        return -1, "", f"Missing scraper: {script}"

    output_path.parent.mkdir(parent=True, exist_ok=True)
    out_abs = str(output_path.resolve())

    env = os.environ.copy()
    env["OUTPUT_CSV"] = out_abs
    # Ensure dotenv in scraper can still load scripts/rinse-cleanertickets/.env
    env.setdefault("NODE_NO_WARNINGS", "1")

    cmd = [node_binary(), str(script)]
    timeout = scrape_timeout_sec()
    proc = subprocess.run(
        cmd,
        cwd=str(sdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""
