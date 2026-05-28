# Folding productivity — 3 reporting modes (superseded)

> **Superseded by:** [RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md](./RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md)  
> **Reason:** Dashboard is **clock-first** (paid time via `shift_sessions`). Bag-wise stats are secondary; work-span is not a management view.

## Historical summary

| Old mode | New role |
|----------|----------|
| Mode A — Bag-wise | Gaming / scoring section (per **folding hour**) |
| Mode B — Work-span | **Dropped** as primary (unreliable for management) |
| Mode C — Clock hours | **Productivity** section (per **clocked hour**) — **primary** |

Phase **4A** delivered per-user `clocked_productivity` + `gaming_scoring` (no work-span in API). Phase **4B** adds All users team view and dashboard layout per the new doc.

Implementation modules listed below are **reference only**; follow the phase doc for current file names and endpoints.

---

## Non-negotiable constraints (still apply)

Phase 4 productivity is **read-only** on bag timing and scan data. See the phase doc for full boundaries.

---

## Deferred / removed

- Work-span as a dashboard tab
- Using scan exception rate as “quality”
- Mode B `rinse_folding_work_span.py` as a first-class feature (do not build for 4B)

For the full specification, tests, and phases **4B / 4C / 4D**, use [RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md](./RINSE_FOLDING_PHASE4_PRODUCTIVITY_DASHBOARD.md).
