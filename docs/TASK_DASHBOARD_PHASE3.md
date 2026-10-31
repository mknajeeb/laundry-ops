# Task Dashboard Phase 3 — Redesign & Record Management

**Branch:** `feat/task-dashboard-redesign-record-mgmt`  
**Base:** production `main` @ `07f3338b`  
**Approved commit:** `4236bc5344b7c4854f1fdff2cd636281d89ee0cf`  
**Status:** Validated & committed. **Not deployed. Production migrations not applied.**  
**Release prep:** [`TASK_DASHBOARD_PHASE3_RELEASE.md`](./TASK_DASHBOARD_PHASE3_RELEASE.md) · screenshots [`phase3-screenshots/`](./phase3-screenshots/)

---

## 1. Redesigned dashboard

- VeeWash tokens from `frontend/src/theme/veewashDashboard.js`
- One compact card per assignment (shared groups counted once)
- Collapsed-by-default expandable participants + checklist
- Compact badges: Not Started · In Progress · Completed · Pending Verification · Partially Verified · Verified · Needs Correction
- Dates `Oct 30, 2026`, times `9:32 AM`
- Responsive stack layout (mobile / tablet / desktop)
- Separate Activity Log removed from Rinse; managers get a compact Management history section (not duplicated as primary UI)

## 2. Record management (VeeWash only)

| Action | API | Persistence |
|---|---|---|
| Edit start/end / business date | `POST …/update-record` | Soft correction + `cleaning_task_completion_revisions` |
| Soft-remove | `POST …/void-activity` | `voided_at` / `voided_by_user_id` / `void_reason` (no DELETE) |
| Add / correct completion | existing manual-complete / correct-completion | unchanged |
| History | `GET …/activity-history` | revisions JSON |

Schema (additive): `backend/sql/task_dashboard_record_mgmt_v1.sql`  
Runtime ensure: `ensure_record_management_schema`.

Does **not** write payroll or attendance tables. Verification actor fields are not rewritten by void; time edits mark `completion_source=corrected` and store before/after.

## 3. Rinse visibility (API-enforced)

`apply_rinse_task_dashboard_scope` now:

- Excludes manual / corrected / voided / superseded activities
- Clears `activity_log` and `queue`
- Strips labor durations + management/audit fields
- Recomputes metrics from eligible assignments only
- Forces `read_only`, disables approve/manual/manage flags

Rinse cannot fetch void/update/history write routes (403 via `_mgmt_write_gate` / history gate).

## 4. Floor & Washer (Angelica / Aselisa) — Oct 30

**Finding (read-only prod evidence):**

- Parents `#77` Angelica, `#78` Aselisa: `status=completed`, `verification_required=0`
- Shared session `#7` still `open`
- Shared checklist items `#13/#14` still `pending` (not checked off)
- No `group_item` children for that shared pair

**Cause:** Shared execution intentionally allows finishing **participation** while checklist completeness is separate. Historical rows were not rewritten.

**Enforcement (this branch):**

- Assignment `completion_status` / dashboard totals stay **In Progress** until required shared checklist items are done (`apply_shared_checklist_to_assignment_status`, `assignment_is_completed`).
- Once checklist is complete, verification children apply the effective policy → **Pending Verification** until approved.
- PIN: participants may finish timers; unfinished shared checklist remains reachable via `shared_checklist_followup` + post-finish check-off.
- Manual completion **cannot** bypass required checklist items (shared or individual groups).
- Historical activity rows are unchanged unless a manager explicitly edits/voids.

## 5. Screenshots (implemented UI)

See `docs/phase3-screenshots/` — captured from real React components via `/dev/task-dashboard-phase3-preview`:

- Management collapsed / expanded shared assignment
- Edit date/time dialog
- Add activity dialog
- Void confirmation
- Rinse read-only (no labor metric, no Manage/Edit/Add/Remove)

## 6. Tests (pre-commit validation)

| Suite | Result |
|---|---|
| Shared checklist + record mgmt + rinse scope + shared groups + cleaning activity + checklist + dashboard metrics | 28 passed |
| Payroll time-record / payment + verification policy + dashboard enhancements + monthly | 73 passed |
| Weekly schedule | 100 passed |
| Frontend `src/components/tasks` | 7 passed |
| Frontend production build (`vite build`) | succeeded |

Payroll/attendance modules are not written by record-management paths (documented + helper isolation).

## 7. Historical preservation

- No production data modified during this work
- Soft-void only after an authorized manager acts in production
- Time edits **preserve** `approved_by` / `approved_at` / status; mark `completion_source=corrected` for Rinse exclusion
- Norma / Francis / Florentina verification rows untouched by this branch

## 8. P0 API stability compatibility

- This branch does **not** modify `startup.sh`, `backend/db.py` pool settings, or `/health/live`
- Additive task-dashboard schema/routes only — can merge independently of `fix/api-p0-stability`
- Recommend merge order: Phase 3 first (feature), then P0 (infra) — or reverse; no file overlap expected

## 9. Deploy / rollback (after approval — NOT now)

1. Deploy API + frontend from this branch SHA  
2. Apply `task_dashboard_record_mgmt_v1.sql` (additive) or rely on runtime `ensure_*`  
3. Smoke: manager edit/void on disposable activity; Rinse dashboard lacks log/actions; Floor & Washer shows In Progress when checklist open; PIN shared checklist follow-up after finish  
4. Rollback: redeploy prior SHA; void columns may remain (harmless); do not reverse-migrate blindly

## 10. Out of scope

- API P0 stability branch (`fix/api-p0-stability`) untouched  
- Phases 4–6 Task Management  
- Production Azure / MySQL changes / production migrations
