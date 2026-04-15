"""
Run scripts/rinse-cleanertickets/scrape.mjs via Node (Playwright).

Production: install Node + Chromium on the API host, set env in scripts/.env or process env,
and place rinse-auth.json next to the scraper or set RINSE_STORAGE_STATE to an absolute path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scraper_dir() -> Path:
    return _repo_root() / "scripts" / "rinse-cleanertickets"


def scraper_script() -> Path:
    return scraper_dir() / "scrape.mjs"


_AZURE_NODE_DEFAULT = "/home/site/node-v20.18.0-linux-x64/bin/node"


def effective_playwright_browsers_path(env: dict | None = None) -> str:
    """
    Playwright browser cache directory.
    Azure App Service Linux uses /home/site/ms-playwright (persistent volume).
    macOS and generic local dev do not have /home/site — use ~/.cache/ms-playwright.
    """
    src = env if env is not None else os.environ
    b = (src.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if b:
        return b
    if Path("/home/site").is_dir():
        return "/home/site/ms-playwright"
    p = Path.home() / ".cache" / "ms-playwright"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return str(p)


def node_binary() -> str:
    explicit = (os.getenv("NODE_BIN") or "").strip()
    if explicit:
        return explicit
    if os.path.isfile(_AZURE_NODE_DEFAULT):
        return _AZURE_NODE_DEFAULT
    return shutil.which("node") or "node"


def _parse_env_truthy(raw: str | None) -> bool:
    """Azure / Key Vault values sometimes include BOM, NBSP, or odd casing."""
    if raw is None:
        return False
    v = (
        str(raw)
        .replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\xa0", " ")
        .strip()
        .lower()
    )
    if not v:
        return False
    return v in ("1", "true", "yes", "on", "y")


def rinse_bag_export_env_raw() -> str | None:
    """
    First non-None value for the Rinse export flag.
    Azure App Service may expose the same setting as RINSE_BAG_EXPORT_ENABLED and/or
    APPSETTING_RINSE_BAG_EXPORT_ENABLED (legacy / slot tooling). Prefer the plain name.
    """
    for key in ("RINSE_BAG_EXPORT_ENABLED", "APPSETTING_RINSE_BAG_EXPORT_ENABLED"):
        v = os.getenv(key)
        if v is not None:
            return v
    return None


def export_enabled() -> bool:
    return _parse_env_truthy(rinse_bag_export_env_raw())


def scrape_timeout_sec() -> int:
    """Subprocess timeout for scrape.mjs (separate from any HTTP proxy limit)."""
    try:
        return max(60, min(7200, int(os.getenv("RINSE_SCRAPE_TIMEOUT_SEC", "900"))))
    except (TypeError, ValueError):
        return 900


def rinse_import_subprocess_extra_env() -> dict[str, str]:
    """
    Env merged only for POST /admin/rinse/import-upload-batch.

    Draft import: page cap is RINSE_IMPORT_MAX_PAGES if set, else RINSE_MAX_PAGES, else 10.
    Slightly shorter page settle when RINSE_PAGE_SETTLE_MS is unset (see rinse_export_routes).
    """
    out: dict[str, str] = {"RINSE_CSV_LAYOUT": "portal"}
    imp = (os.getenv("RINSE_IMPORT_MAX_PAGES") or "").strip()
    if imp:
        raw = imp
    else:
        raw = (os.getenv("RINSE_MAX_PAGES") or "10").strip() or "10"
    try:
        n = int(raw)
    except ValueError:
        n = 10
    out["RINSE_MAX_PAGES"] = str(max(1, min(500, n)))
    if not (os.getenv("RINSE_PAGE_SETTLE_MS") or "").strip():
        out["RINSE_PAGE_SETTLE_MS"] = "2200"
    return out


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
    pw_pkg = sdir / "node_modules" / "playwright" / "package.json"
    browsers = effective_playwright_browsers_path()
    raw_flag = rinse_bag_export_env_raw()
    return {
        "enabled": export_enabled(),
        "rinse_export_env_key_present": raw_flag is not None,
        "rinse_export_env_value_len": len(str(raw_flag)) if raw_flag is not None else 0,
        "repo_root": str(root),
        "scraper_dir": str(sdir),
        "scraper_script_exists": script.is_file(),
        "node_path": node,
        "node_found": node_ok,
        "playwright_package_present": pw_pkg.is_file(),
        "playwright_browsers_path": browsers,
        "playwright_chromium_cached": _playwright_chromium_cached(Path(browsers)),
        "playwright_sysdeps_marker": _SYSDEPS_MARKER.is_file(),
        "chromium_os_libs_present": _chromium_os_libs_likely_present(),
    }


def _use_persistent_node_modules() -> bool:
    """Azure: wwwroot is replaced on deploy; /home/site persists."""
    return Path("/home/site").is_dir()


def _playwright_cli_js(sdir: Path) -> Path | None:
    p = sdir / "node_modules" / "playwright" / "cli.js"
    return p if p.is_file() else None


def _playwright_chromium_cached(browsers_path: Path) -> bool:
    """True if a Playwright-downloaded headless Chromium binary is already present."""
    if not browsers_path.is_dir():
        return False
    try:
        for p in browsers_path.rglob("chrome-headless-shell"):
            if p.is_file():
                return True
        for p in browsers_path.rglob("chromium"):
            if p.is_file() and p.name == "chromium":
                return True
    except OSError:
        pass
    return False


def _npm_install_command(node: str) -> tuple[list[str] | None, str]:
    """
    Build an npm install command that works even when `bin/npm` is not directly executable
    (some hosts raise Exec format error on that shim).
    """
    node_path = Path(node).resolve()
    nd = node_path.parent
    npm = nd / "npm"
    if not npm.is_file():
        return None, f"npm not found beside Node ({node!r})."
    npm_cli = nd.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if npm_cli.is_file():
        return [str(node_path), str(npm_cli), "install", "--omit=dev", "--no-audit", "--no-fund"], ""
    return [str(npm), "install", "--omit=dev", "--no-audit", "--no-fund"], ""


def _ensure_rinse_scraper_node_modules() -> tuple[bool, str]:
    """
    Ensure scripts/rinse-cleanertickets/node_modules contains playwright.
    On Azure, symlink node_modules -> /home/site/rinse_scraper_node_modules so deploys do not wipe deps.
    """
    sdir = scraper_dir()
    nm = sdir / "node_modules"
    pw_pkg = nm / "playwright" / "package.json"

    if pw_pkg.is_file():
        return True, ""

    node = node_binary()
    if not _node_executable_ok(node):
        return False, f"Node is not runnable ({node!r}). Set NODE_BIN in Azure (e.g. {_AZURE_NODE_DEFAULT})."

    npm_cmd, npm_err = _npm_install_command(node)
    if not npm_cmd:
        return False, npm_err

    env = os.environ.copy()
    browsers = effective_playwright_browsers_path(env)
    env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
    try:
        Path(browsers).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    if _use_persistent_node_modules():
        persist = Path("/home/site/rinse_scraper_node_modules")
        try:
            persist.mkdir(parents=True, exist_ok=True)
            if nm.exists() or nm.is_symlink():
                if nm.is_symlink() or nm.is_file():
                    nm.unlink(missing_ok=True)
                elif nm.is_dir():
                    shutil.rmtree(nm)
            nm.symlink_to(persist, target_is_directory=True)
        except OSError as e:
            return False, f"Could not link node_modules to {persist}: {e}"

    try:
        r = subprocess.run(
            npm_cmd,
            cwd=str(sdir),
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "npm install timed out after 600s."
    except OSError as e:
        return False, f"npm install could not run: {e}"

    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-2000:]
        return False, f"npm install failed (exit {r.returncode}): {tail}"

    if not pw_pkg.is_file():
        return False, "playwright is still missing after npm install."
    return True, ""


_SYSDEPS_MARKER = Path("/home/site/.rinse_playwright_sysdeps_ok")


def _chromium_os_libs_likely_present() -> bool:
    """
    /home/site markers persist across App Service worker swaps; apt packages under /usr may not.
    Re-run install-deps when glib is missing even if the marker file exists.
    """
    candidates = (
        Path("/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0"),
        Path("/lib/x86_64-linux-gnu/libglib-2.0.so.0"),
        Path("/usr/lib/aarch64-linux-gnu/libglib-2.0.so.0"),
    )
    return any(p.is_file() for p in candidates)


def _ensure_playwright_chromium(sdir: Path, node: str, env: dict) -> tuple[bool, str]:
    """Download Chromium + OS libraries (glibc GTK stack). Uses node + cli.js (no npx shim)."""
    cli = _playwright_cli_js(sdir)
    if not cli:
        return False, "Missing playwright cli.js after npm install."

    browsers = effective_playwright_browsers_path(env)
    env = {**env, "PLAYWRIGHT_BROWSERS_PATH": browsers}
    node_resolved = str(Path(node).resolve())
    try:
        Path(browsers).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    if not _playwright_chromium_cached(Path(browsers)):
        try:
            r = subprocess.run(
                [node_resolved, str(cli), "install", "chromium"],
                cwd=str(sdir),
                capture_output=True,
                text=True,
                timeout=900,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "playwright install chromium timed out after 900s."
        except OSError as e:
            return False, f"playwright install chromium could not run: {e}"

        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-2000:]
            return False, f"playwright install chromium failed (exit {r.returncode}): {tail}"

        if not _playwright_chromium_cached(Path(browsers)):
            return False, "Chromium still missing after playwright install (check PLAYWRIGHT_BROWSERS_PATH and disk space)."

    # Headless shell still needs libglib etc. on Debian/Ubuntu (Azure App Service Linux).
    # Skip on macOS / hosts without /home/site — `install-deps` is apt-oriented and breaks local Darwin.
    if Path("/home/site").is_dir() and (not _SYSDEPS_MARKER.is_file() or not _chromium_os_libs_likely_present()):
        try:
            r2 = subprocess.run(
                [node_resolved, str(cli), "install-deps", "chromium"],
                cwd=str(sdir),
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, "playwright install-deps chromium timed out after 600s."
        except OSError as e:
            return False, f"playwright install-deps could not run: {e}"

        if r2.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-2500:]
            ssh_hint = (
                "Missing system libraries for Chromium (e.g. libglib). SSH as root into the API app and run:\n"
                f"  cd {sdir} && export PATH=\"$(dirname {node_resolved}):$PATH\" && "
                f"{node_resolved} node_modules/playwright/cli.js install-deps chromium\n"
                "If that fails, on Debian/Ubuntu try:\n"
                "  apt-get update && apt-get install -y "
                "libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 "
                "libxcb1 libxkbcommon0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 "
                "libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0\n"
                f"install-deps output (tail): {tail}"
            )
            return False, ssh_hint

        try:
            _SYSDEPS_MARKER.touch()
        except OSError:
            pass

    return True, ""


def run_bag_export_csv(
    output_path: Path,
    extra_env: dict[str, str] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
) -> tuple[int, str, str]:
    """
    Run scrape.mjs with OUTPUT_CSV set to output_path (absolute).
    Optional extra_env merged into the subprocess environment (e.g. RINSE_CSV_LAYOUT=portal).
    If progress_callback is set, stdout/stderr are streamed and the callback receives
    cumulative tails (throttled ~1.25s) so a UI can show live scrape progress.

    Returns (exit_code, stdout, stderr).
    """
    sdir = scraper_dir()
    script = scraper_script()
    if not script.is_file():
        return -1, "", f"Missing scraper: {script}"

    ok, prep_err = _ensure_rinse_scraper_node_modules()
    if not ok:
        return -1, "", prep_err

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_abs = str(output_path.resolve())

    env = os.environ.copy()
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items() if v is not None})
    env["OUTPUT_CSV"] = out_abs
    # Ensure dotenv in scraper can still load scripts/rinse-cleanertickets/.env
    env.setdefault("NODE_NO_WARNINGS", "1")
    if not (env.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip():
        env["PLAYWRIGHT_BROWSERS_PATH"] = effective_playwright_browsers_path(env)

    node = node_binary()
    bok, berr = _ensure_playwright_chromium(sdir, node, env)
    if not bok:
        return -1, "", berr

    cmd = [node, str(script)]
    timeout = scrape_timeout_sec()

    if progress_callback is None:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(sdir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            return (
                -1,
                "",
                f"Scrape timed out after {timeout}s (raise RINSE_SCRAPE_TIMEOUT_SEC, cap pages with RINSE_MAX_PAGES or RINSE_IMPORT_MAX_PAGES, or lower RINSE_PAGE_SETTLE_MS if pages load quickly).",
            )
        except OSError as e:
            return -1, "", f"Failed to run Node scraper: {e}"

    # Piped scrape with live progress (bounded memory).
    stdout_d: deque[str] = deque(maxlen=8000)
    stderr_d: deque[str] = deque(maxlen=2000)

    def _read_pipe(pipe, buf: deque[str]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                buf.append(line)
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(sdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        return -1, "", f"Failed to run Node scraper: {e}"

    t_out = threading.Thread(
        target=_read_pipe,
        args=(proc.stdout, stdout_d),
        name="rinse-scrape-stdout",
        daemon=True,
    )
    t_err = threading.Thread(
        target=_read_pipe,
        args=(proc.stderr, stderr_d),
        name="rinse-scrape-stderr",
        daemon=True,
    )
    t_out.start()
    t_err.start()

    deadline = time.monotonic() + timeout
    last_cb = 0.0
    code: int | None = None
    try:
        while True:
            code = proc.poll()
            if code is not None:
                break
            now = time.monotonic()
            if now >= deadline:
                proc.kill()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
                t_out.join(timeout=5.0)
                t_err.join(timeout=5.0)
                return (
                    -1,
                    "".join(stdout_d),
                    "".join(stderr_d)
                    + "\nScrape timed out after "
                    + str(timeout)
                    + "s (raise RINSE_SCRAPE_TIMEOUT_SEC, cap pages with RINSE_MAX_PAGES or RINSE_IMPORT_MAX_PAGES).",
                )
            if now - last_cb >= 1.25:
                last_cb = now
                so = "".join(stdout_d)
                se = "".join(stderr_d)
                try:
                    progress_callback(so[-600_000:], se[-32_000:])
                except Exception:
                    pass
            time.sleep(0.2)
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        t_out.join(timeout=5.0)
        t_err.join(timeout=5.0)

    full_out = "".join(stdout_d)
    full_err = "".join(stderr_d)
    final_code = int(code if code is not None else proc.returncode or -1)
    try:
        progress_callback(full_out[-600_000:], full_err[-32_000:])
    except Exception:
        pass
    return final_code, full_out, full_err
