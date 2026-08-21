"""Entry: long-lived Rinse freshness supervisor (never cron-driven)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _reexec_with_project_venv() -> None:
    repo = Path(__file__).resolve().parents[2]
    venv_python = repo / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(
        str(venv_python),
        [str(venv_python), "-m", "backend.jobs.run_rinse_freshness_supervisor", *sys.argv[1:]],
    )


_reexec_with_project_venv()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rinse freshness supervisor")
    p.add_argument("--organization-id", type=int, default=None)
    p.add_argument("--max-cycles", type=int, default=None)
    args = p.parse_args(argv)

    # Hard-disable legacy successor starts from any nested scrape code.
    os.environ["RINSE_FRESHNESS_DISABLE_SUCCESSOR"] = "1"
    os.environ["RINSE_SCHEDULED_SCRAPE_ENABLED"] = os.environ.get(
        "RINSE_SCHEDULED_SCRAPE_ENABLED", "1"
    )

    from backend.rinse_freshness_supervisor import run_supervisor

    return run_supervisor(
        organization_id=args.organization_id,
        max_cycles=args.max_cycles,
    )


if __name__ == "__main__":
    raise SystemExit(main())
