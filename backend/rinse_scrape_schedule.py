"""
Authoritative Rinse scrape schedule / mode (America/New_York).

SCHEDULE answers: when should a scrape run?
SINGLE-FLIGHT (GET_LOCK / lease) answers: may this process scrape?
RECOVERY answers: was scheduled work missed/orphaned?

Normal state between ticks may be "no scraper running". That is healthy Quiet
and healthy Active idle — not a dead chain.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, time
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

from backend.rinse_folding_et import ET

ScheduleMode = Literal["ACTIVE", "QUIET"]
TimezoneName = "America/New_York"

SCHEDULE_SETTINGS_KEY = "rinse_scrape_schedule_v1"
# Global (non-tenant) row — schedule is infrastructure, not per-org product data.
SCHEDULE_SETTINGS_ORG_ID = 0

DEFAULT_ACTIVE_START = time(6, 45)
DEFAULT_ACTIVE_END = time(22, 0)
DEFAULT_ACTIVE_INTERVAL_MINUTES = 15


@dataclass(frozen=True)
class ScrapeScheduleConfig:
    timezone: str = TimezoneName
    active_start: time = DEFAULT_ACTIVE_START
    active_end: time = DEFAULT_ACTIVE_END
    active_interval_minutes: int = DEFAULT_ACTIVE_INTERVAL_MINUTES
    quiet_scrape_times: tuple[time, ...] = ()
    # When True, config came from defaults/env after rejecting invalid persisted JSON.
    used_safe_fallback: bool = False
    validation_errors: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "active_start": _fmt_hhmm(self.active_start),
            "active_end": _fmt_hhmm(self.active_end),
            "active_interval_minutes": int(self.active_interval_minutes),
            "quiet_scrape_times": [_fmt_hhmm(t) for t in self.quiet_scrape_times],
            "used_safe_fallback": bool(self.used_safe_fallback),
            "validation_errors": list(self.validation_errors),
        }


@dataclass(frozen=True)
class ScheduleDecision:
    mode: ScheduleMode
    now_et: datetime
    scrape_due: bool
    reason: str
    tick_et: datetime | None = None
    tick_key: str | None = None
    next_tick_et: datetime | None = None
    recovery_start_permitted: bool = False
    quiet_suppresses_automatic_start: bool = False
    config: ScrapeScheduleConfig = field(default_factory=ScrapeScheduleConfig)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "now_et": self.now_et.isoformat(),
            "scrape_due": self.scrape_due,
            "reason": self.reason,
            "tick_et": self.tick_et.isoformat() if self.tick_et else None,
            "tick_key": self.tick_key,
            "next_tick_et": self.next_tick_et.isoformat() if self.next_tick_et else None,
            "recovery_start_permitted": self.recovery_start_permitted,
            "quiet_suppresses_automatic_start": self.quiet_suppresses_automatic_start,
            "config": self.config.to_public_dict(),
        }


def _fmt_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _parse_hhmm(raw: Any, *, field_name: str) -> time:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required (HH:MM)")
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field_name} must be HH:MM, got {text!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{field_name} out of range: {text!r}")
    return time(hour, minute)


def default_schedule_config() -> ScrapeScheduleConfig:
    return ScrapeScheduleConfig()


def validate_schedule_config_payload(
    payload: dict[str, Any] | None,
) -> tuple[ScrapeScheduleConfig | None, list[str]]:
    """Validate a config dict. Returns (config, errors). config is None when invalid."""
    errors: list[str] = []
    raw = dict(payload or {})

    tz_name = str(raw.get("timezone") or TimezoneName).strip() or TimezoneName
    if tz_name != TimezoneName:
        errors.append(f"timezone must be {TimezoneName}")
    try:
        ZoneInfo(tz_name)
    except Exception:
        errors.append(f"invalid timezone: {tz_name!r}")

    try:
        active_start = _parse_hhmm(raw.get("active_start"), field_name="active_start")
    except ValueError as exc:
        errors.append(str(exc))
        active_start = DEFAULT_ACTIVE_START

    try:
        active_end = _parse_hhmm(raw.get("active_end"), field_name="active_end")
    except ValueError as exc:
        errors.append(str(exc))
        active_end = DEFAULT_ACTIVE_END

    try:
        interval = int(raw.get("active_interval_minutes") or DEFAULT_ACTIVE_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        errors.append("active_interval_minutes must be an integer")
        interval = DEFAULT_ACTIVE_INTERVAL_MINUTES

    if interval < 5 or interval > 120:
        errors.append("active_interval_minutes must be between 5 and 120")
    if 60 % interval != 0 and interval % 5 != 0:
        # Allow 5/10/15/20/30/60 primarily; still accept other multiples of 5.
        pass
    if interval % 5 != 0:
        errors.append("active_interval_minutes must be a multiple of 5")

    if active_start == active_end:
        errors.append("active_start and active_end must differ")
    # Active window is same-calendar-day [start, end] inclusive of endpoints as ticks.
    # Overnight active windows are not supported (facility is daytime).
    start_min = active_start.hour * 60 + active_start.minute
    end_min = active_end.hour * 60 + active_end.minute
    if end_min < start_min:
        errors.append("active_end must be after active_start on the same ET day")

    quiet_raw = raw.get("quiet_scrape_times") or []
    if not isinstance(quiet_raw, (list, tuple)):
        errors.append("quiet_scrape_times must be a list of HH:MM strings")
        quiet_raw = []

    quiet_times: list[time] = []
    seen: set[str] = set()
    for item in quiet_raw:
        try:
            qt = _parse_hhmm(item, field_name="quiet_scrape_times[]")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        key = _fmt_hhmm(qt)
        if key in seen:
            errors.append(f"duplicate quiet scrape time: {key}")
            continue
        seen.add(key)
        qmin = qt.hour * 60 + qt.minute
        if start_min <= qmin <= end_min:
            errors.append(
                f"quiet scrape time {key} falls inside the ACTIVE window "
                f"{_fmt_hhmm(active_start)}–{_fmt_hhmm(active_end)}"
            )
            continue
        quiet_times.append(qt)

    if errors:
        return None, errors

    return (
        ScrapeScheduleConfig(
            timezone=TimezoneName,
            active_start=active_start,
            active_end=active_end,
            active_interval_minutes=interval,
            quiet_scrape_times=tuple(sorted(quiet_times)),
        ),
        [],
    )


def _config_from_env() -> dict[str, Any]:
    out: dict[str, Any] = {}
    start = os.getenv("RINSE_SCRAPE_ACTIVE_START")
    end = os.getenv("RINSE_SCRAPE_ACTIVE_END")
    interval = os.getenv("RINSE_SCRAPE_ACTIVE_INTERVAL_MIN")
    quiet = os.getenv("RINSE_SCRAPE_QUIET_TIMES")
    if start:
        out["active_start"] = start.strip()
    if end:
        out["active_end"] = end.strip()
    if interval and str(interval).strip():
        out["active_interval_minutes"] = int(interval)
    if quiet is not None and str(quiet).strip() != "":
        out["quiet_scrape_times"] = [p.strip() for p in quiet.split(",") if p.strip()]
    return out


def load_schedule_config(cursor=None) -> ScrapeScheduleConfig:
    """
    Load schedule config.

    Precedence for values: persisted DB JSON (if valid) overlays defaults;
    env overlays those. Invalid persisted config → defaults (+ env) with
    used_safe_fallback=True and validation_errors populated.
    """
    base = default_schedule_config().to_public_dict()
    persisted_errors: list[str] = []
    if cursor is not None:
        try:
            from backend.ta_helpers import table_exists, table_has_column

            if table_exists(cursor, "system_settings") and table_has_column(
                cursor, "system_settings", "organization_id"
            ):
                cursor.execute(
                    """
                    SELECT svalue FROM system_settings
                    WHERE organization_id = %s AND skey = %s
                    LIMIT 1
                    """,
                    (SCHEDULE_SETTINGS_ORG_ID, SCHEDULE_SETTINGS_KEY),
                )
                row = cursor.fetchone()
                raw_val = None
                if isinstance(row, dict):
                    raw_val = row.get("svalue")
                elif row:
                    raw_val = row[0]
                if raw_val:
                    parsed = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
                    if isinstance(parsed, dict):
                        cfg, errs = validate_schedule_config_payload({**base, **parsed})
                        if cfg is not None:
                            base = cfg.to_public_dict()
                        else:
                            persisted_errors = errs
        except Exception as exc:
            persisted_errors.append(f"failed to load persisted schedule: {exc}")

    merged = {**base, **_config_from_env()}
    # Drop non-payload keys before validate
    merged.pop("used_safe_fallback", None)
    merged.pop("validation_errors", None)
    cfg, errs = validate_schedule_config_payload(merged)
    if cfg is not None and not persisted_errors:
        return cfg
    if cfg is not None and persisted_errors:
        return replace(
            cfg,
            used_safe_fallback=True,
            validation_errors=tuple(persisted_errors),
        )
    # Env+defaults also invalid — hard-fallback to code defaults.
    safe = default_schedule_config()
    return replace(
        safe,
        used_safe_fallback=True,
        validation_errors=tuple(persisted_errors + errs),
    )


def save_schedule_config(cursor, payload: dict[str, Any]) -> ScrapeScheduleConfig:
    """Persist a validated schedule config. Raises ValueError when invalid."""
    cfg, errs = validate_schedule_config_payload(payload)
    if cfg is None:
        raise ValueError("; ".join(errs))
    from backend.ta_helpers import table_exists, table_has_column

    if not table_exists(cursor, "system_settings") or not table_has_column(
        cursor, "system_settings", "organization_id"
    ):
        raise RuntimeError("system_settings table unavailable")
    body = {
        "timezone": cfg.timezone,
        "active_start": _fmt_hhmm(cfg.active_start),
        "active_end": _fmt_hhmm(cfg.active_end),
        "active_interval_minutes": cfg.active_interval_minutes,
        "quiet_scrape_times": [_fmt_hhmm(t) for t in cfg.quiet_scrape_times],
    }
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE svalue = VALUES(svalue)
        """,
        (SCHEDULE_SETTINGS_ORG_ID, SCHEDULE_SETTINGS_KEY, json.dumps(body)),
    )
    return cfg


def ensure_et(now: datetime | None = None) -> datetime:
    """Return timezone-aware America/New_York datetime."""
    if now is None:
        return datetime.now(tz=ET)
    if now.tzinfo is None:
        # Treat naive as already-ET wall time (tests / ET wall stamps).
        return now.replace(tzinfo=ET)
    return now.astimezone(ET)


def current_mode(now: datetime | None = None, config: ScrapeScheduleConfig | None = None) -> ScheduleMode:
    cfg = config or default_schedule_config()
    now_et = ensure_et(now)
    # Minute resolution so 22:00:30 still counts as the closing ACTIVE minute.
    t_min = now_et.hour * 60 + now_et.minute
    start_min = cfg.active_start.hour * 60 + cfg.active_start.minute
    end_min = cfg.active_end.hour * 60 + cfg.active_end.minute
    if start_min <= t_min <= end_min:
        return "ACTIVE"
    return "QUIET"


def quiet_suppresses_automatic_start(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
) -> bool:
    return current_mode(now, config) == "QUIET"


def recovery_start_permitted(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
) -> bool:
    """Recovery may start a scrape only in ACTIVE (missed/failed tick)."""
    return current_mode(now, config) == "ACTIVE"


def _aware_on_day(d: date, t: time) -> datetime | None:
    """
    Build ET-aware datetime for date d + time t.

    Spring-forward: nonexistent local times return None (skip that tick).
    Fall-back: ZoneInfo fold=0 picks the first occurrence (deterministic).
    """
    try:
        return datetime(
            d.year, d.month, d.day, t.hour, t.minute, 0, tzinfo=ET, fold=0
        )
    except Exception:
        return None


def iter_active_ticks_for_day(d: date, config: ScrapeScheduleConfig) -> list[datetime]:
    """Inclusive ACTIVE ticks from active_start through active_end on calendar day d."""
    ticks: list[datetime] = []
    start = _aware_on_day(d, config.active_start)
    end = _aware_on_day(d, config.active_end)
    if start is None or end is None:
        return ticks
    step = timedelta(minutes=int(config.active_interval_minutes))
    cur = start
    # Guard against pathological loops.
    for _ in range(2000):
        if cur > end:
            break
        ticks.append(cur)
        nxt = cur + step
        # If addition lands on a repeated/gap hour, still advance wall by step from prior.
        if nxt <= cur:
            break
        cur = nxt
    # Ensure closing endpoint is present even if interval doesn't land exactly.
    if ticks and ticks[-1] != end and end >= start:
        ticks.append(end)
    elif not ticks and end >= start:
        ticks = [start, end] if start != end else [start]
    # Deduplicate while preserving order (endpoint append).
    out: list[datetime] = []
    seen: set[str] = set()
    for t in ticks:
        key = t.strftime("%Y-%m-%d %H:%M")
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def iter_quiet_ticks_for_day(d: date, config: ScrapeScheduleConfig) -> list[datetime]:
    out: list[datetime] = []
    for t in config.quiet_scrape_times:
        aware = _aware_on_day(d, t)
        if aware is not None:
            out.append(aware)
    return out


def all_ticks_covering(
    now_et: datetime,
    config: ScrapeScheduleConfig,
    *,
    lookback_days: int = 1,
    lookahead_days: int = 1,
) -> list[datetime]:
    now_et = ensure_et(now_et)
    days = [
        now_et.date() + timedelta(days=offset)
        for offset in range(-lookback_days, lookahead_days + 1)
    ]
    ticks: list[datetime] = []
    for d in days:
        ticks.extend(iter_active_ticks_for_day(d, config))
        ticks.extend(iter_quiet_ticks_for_day(d, config))
    ticks.sort()
    return ticks


def tick_key(tick: datetime) -> str:
    tick = ensure_et(tick)
    return tick.strftime("%Y-%m-%d %H:%M")


def next_scheduled_tick(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
) -> datetime | None:
    cfg = config or default_schedule_config()
    now_et = ensure_et(now)
    for tick in all_ticks_covering(now_et, cfg, lookback_days=0, lookahead_days=2):
        if tick > now_et:
            return tick
    return None


def current_or_due_tick(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
    *,
    grace_after_seconds: int = 0,
) -> datetime | None:
    """
    Return the schedule tick that is currently due.

    A tick at T is due for [T, min(next_tick, T + interval)).
    That keeps the closing ACTIVE tick from remaining due all Quiet night.
    grace_after_seconds extends the window for recovery evaluation only.
    """
    cfg = config or default_schedule_config()
    now_et = ensure_et(now)
    ticks = all_ticks_covering(now_et, cfg, lookback_days=1, lookahead_days=1)
    slot = timedelta(minutes=int(cfg.active_interval_minutes))
    due: datetime | None = None
    for i, tick in enumerate(ticks):
        nxt = ticks[i + 1] if i + 1 < len(ticks) else tick + slot
        natural_end = min(nxt, tick + slot)
        end = natural_end + timedelta(seconds=max(0, int(grace_after_seconds)))
        if tick <= now_et < end:
            due = tick
    return due


def evaluate_schedule(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
    *,
    last_completed_tick_key: str | None = None,
    grace_after_seconds: int = 0,
) -> ScheduleDecision:
    """
    Authoritative schedule decision for scraper/watchdog entrypoints.

    scrape_due=True only when there is a tick for `now` that has not already
    been completed (matched by tick_key).
    """
    cfg = config or default_schedule_config()
    now_et = ensure_et(now)
    mode = current_mode(now_et, cfg)
    quiet = mode == "QUIET"
    tick = current_or_due_tick(now_et, cfg, grace_after_seconds=grace_after_seconds)
    nxt = next_scheduled_tick(now_et, cfg)
    recovery_ok = mode == "ACTIVE"

    if tick is None:
        return ScheduleDecision(
            mode=mode,
            now_et=now_et,
            scrape_due=False,
            reason="no_tick_for_now",
            tick_et=None,
            tick_key=None,
            next_tick_et=nxt,
            recovery_start_permitted=recovery_ok,
            quiet_suppresses_automatic_start=quiet,
            config=cfg,
        )

    key = tick_key(tick)
    if last_completed_tick_key and last_completed_tick_key == key:
        return ScheduleDecision(
            mode=mode,
            now_et=now_et,
            scrape_due=False,
            reason="tick_already_completed",
            tick_et=tick,
            tick_key=key,
            next_tick_et=nxt,
            recovery_start_permitted=recovery_ok,
            quiet_suppresses_automatic_start=quiet,
            config=cfg,
        )

    if quiet and tick.timetz().replace(tzinfo=None) not in cfg.quiet_scrape_times:
        # Safety: Active ticks should not be "due" in Quiet; current_or_due_tick
        # only returns quiet ticks during Quiet if configured.
        if tick.timetz().replace(tzinfo=None) >= cfg.active_start and tick.timetz().replace(
            tzinfo=None
        ) <= cfg.active_end:
            return ScheduleDecision(
                mode=mode,
                now_et=now_et,
                scrape_due=False,
                reason="quiet_suppresses_active_tick",
                tick_et=tick,
                tick_key=key,
                next_tick_et=nxt,
                recovery_start_permitted=False,
                quiet_suppresses_automatic_start=True,
                config=cfg,
            )

    return ScheduleDecision(
        mode=mode,
        now_et=now_et,
        scrape_due=True,
        reason="scheduled_tick_due",
        tick_et=tick,
        tick_key=key,
        next_tick_et=nxt,
        recovery_start_permitted=recovery_ok,
        quiet_suppresses_automatic_start=quiet,
        config=cfg,
    )


def missed_active_tick(
    now: datetime | None = None,
    config: ScrapeScheduleConfig | None = None,
    *,
    last_completed_tick_key: str | None = None,
    miss_grace_seconds: int = 120,
) -> ScheduleDecision:
    """
    Recovery helper: in ACTIVE, if the current slot's tick is still incomplete
    after miss_grace_seconds past the tick time, report scrape_due for recovery.
    Quiet always returns not-due with quiet suppression.
    """
    cfg = config or default_schedule_config()
    now_et = ensure_et(now)
    mode = current_mode(now_et, cfg)
    if mode == "QUIET":
        return ScheduleDecision(
            mode="QUIET",
            now_et=now_et,
            scrape_due=False,
            reason="quiet_expected_idle",
            next_tick_et=next_scheduled_tick(now_et, cfg),
            recovery_start_permitted=False,
            quiet_suppresses_automatic_start=True,
            config=cfg,
        )

    tick = current_or_due_tick(now_et, cfg, grace_after_seconds=0)
    nxt = next_scheduled_tick(now_et, cfg)
    if tick is None:
        return ScheduleDecision(
            mode=mode,
            now_et=now_et,
            scrape_due=False,
            reason="no_active_tick_to_recover",
            next_tick_et=nxt,
            recovery_start_permitted=True,
            quiet_suppresses_automatic_start=False,
            config=cfg,
        )
    key = tick_key(tick)
    if last_completed_tick_key == key:
        return ScheduleDecision(
            mode=mode,
            now_et=now_et,
            scrape_due=False,
            reason="tick_already_completed",
            tick_et=tick,
            tick_key=key,
            next_tick_et=nxt,
            recovery_start_permitted=True,
            quiet_suppresses_automatic_start=False,
            config=cfg,
        )
    age = (now_et - tick).total_seconds()
    if age < float(miss_grace_seconds):
        return ScheduleDecision(
            mode=mode,
            now_et=now_et,
            scrape_due=False,
            reason="within_miss_grace",
            tick_et=tick,
            tick_key=key,
            next_tick_et=nxt,
            recovery_start_permitted=True,
            quiet_suppresses_automatic_start=False,
            config=cfg,
        )
    return ScheduleDecision(
        mode=mode,
        now_et=now_et,
        scrape_due=True,
        reason="missed_active_tick",
        tick_et=tick,
        tick_key=key,
        next_tick_et=nxt,
        recovery_start_permitted=True,
        quiet_suppresses_automatic_start=False,
        config=cfg,
    )


def config_as_dict(config: ScrapeScheduleConfig) -> dict[str, Any]:
    return config.to_public_dict()


LAST_TICK_SETTINGS_KEY = "rinse_scrape_last_tick_v1"


def get_last_completed_tick_key(cursor, organization_id: int) -> str | None:
    """Return the last schedule tick_key completed for this org, if recorded."""
    try:
        from backend.ta_helpers import table_exists, table_has_column

        if not table_exists(cursor, "system_settings") or not table_has_column(
            cursor, "system_settings", "organization_id"
        ):
            return None
        cursor.execute(
            """
            SELECT svalue FROM system_settings
            WHERE organization_id = %s AND skey = %s
            LIMIT 1
            """,
            (int(organization_id), LAST_TICK_SETTINGS_KEY),
        )
        row = cursor.fetchone()
        raw = row.get("svalue") if isinstance(row, dict) else (row[0] if row else None)
        if not raw:
            return None
        if isinstance(raw, str) and raw.strip().startswith("{"):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                key = parsed.get("tick_key")
                return str(key) if key else None
        return str(raw).strip() or None
    except Exception:
        return None


def mark_tick_completed(
    cursor,
    organization_id: int,
    tick_key_value: str,
    *,
    run_id: int | None = None,
) -> None:
    """Record that a schedule tick was completed (owned scrape finished successfully)."""
    from backend.ta_helpers import table_exists, table_has_column

    if not tick_key_value:
        return
    if not table_exists(cursor, "system_settings") or not table_has_column(
        cursor, "system_settings", "organization_id"
    ):
        return
    body = json.dumps(
        {
            "tick_key": str(tick_key_value),
            "run_id": int(run_id) if run_id is not None else None,
            "recorded_at_et": ensure_et().isoformat(),
        }
    )
    cursor.execute(
        """
        INSERT INTO system_settings (organization_id, skey, svalue)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE svalue = VALUES(svalue)
        """,
        (int(organization_id), LAST_TICK_SETTINGS_KEY, body),
    )
