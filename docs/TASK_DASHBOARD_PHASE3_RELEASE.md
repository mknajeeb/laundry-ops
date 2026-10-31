# Task Dashboard Phase 3 — Release preparation

**Status:** Integrated with deployed P0. **Production deployment NOT authorized.**  
**Branch:** `feat/task-dashboard-redesign-record-mgmt`  
**Production `origin/main`:** `457c9d5c1384bbdeca8226c5b424a87c6990725c` (P0 API stability)  
**Phase 3 parent:** `a9023bc77d9e81ca6af222c376da6c8937c953bb`  
**Integration merge:** `8536b1cbc0550e9112f04847fe8dd3ad2b0c6b63`

**Screenshots (keep with release review):** [`docs/phase3-screenshots/`](./phase3-screenshots/)

---

## 1. Production compatibility (P0 API stability)

| Item | Finding |
|---|---|
| `origin/main` tip | `457c9d5c` — deployed P0 API stability |
| P0 commits on this branch | `8c20b4a7` and `457c9d5c`, via merge `8536b1cb` |
| File overlap Phase 3 ↔ P0 | **None.** Merge was clean |
| Phase 3 paths | Task dashboard, record management, Rinse scope |
| P0 paths kept | `startup.sh`, `backend/db.py`, `backend/app.py` health/pool handling, `/health/live` |

Do **not** drop either side. Do **not** change Azure worker, pool, or health settings in the Phase 3 deploy.

---

## 2. Release contents verification

Release delta vs production `origin/main` (`457c9d5c`) is the Phase 3 dashboard work only. P0 is already the base.

| Check | Status |
|---|---|
| VeeWash dashboard layout | `ManagementTasksPage` + `TaskAssignmentCard` + `VEEWASH_DASHBOARD` tokens |
| Rinse read-only dashboard | `apply_rinse_task_dashboard_scope` + `read_only` / write 403 |
| Shared checklist completion | `apply_shared_checklist_to_assignment_status`; PIN follow-up; manual bypass blocked |
| Management edit / add / void | `update-record`, `manual-complete`, `void-activity` |
| Correction audit history | `cleaning_task_completion_revisions` + `activity-history` |
| Rinse excludes manual/corrected/voided/superseded | `activity_is_rinse_eligible` + monthly `rinse_eligible_only` |
| Existing approvals preserved | Time edits keep `approved_*` / status; mark `corrected` only |
| Payroll / attendance isolation | No writes to payroll or attendance tables |

Out of release: Phases 4–6 and any Azure worker, pool, or health-check changes. P0 stays in place.

---

## 3. Migration readiness

**File:** `backend/sql/task_dashboard_record_mgmt_v1.sql`

| Property | Notes |
|---|---|
| Additive | Nullable void/supersede columns; optional index; revisions table / `change_type` |
| Idempotent | INFORMATION_SCHEMA guards + `CREATE TABLE IF NOT EXISTS` |
| Prod data | No row rewrites; no NOT NULL without default on existing rows |
| Runtime fallback | `ensure_record_management_schema` / `ensure_manual_completion_schema` |
| Apply now? | **No** — wait for deployment approval |

---

## 4. Deployment checklist (execute only after GO)

### A. Pre-deploy
- [ ] Confirm release SHA still matches approved commit (or documented prep follow-ups)
- [ ] Confirm the release still contains P0 `457c9d5c` and the Phase 3 dashboard commits
- [ ] Production DB backup (MySQL dump or Azure backup point)
- [ ] Confirm screenshots reviewed: `docs/phase3-screenshots/`

### B. Migration
- [ ] Apply `backend/sql/task_dashboard_record_mgmt_v1.sql` on production MySQL
- [ ] Verify columns: `voided_at`, `voided_by_user_id`, `void_reason`, `superseded_by_activity_id`
- [ ] Verify `cleaning_task_completion_revisions.change_type` exists
- [ ] Re-run script once → idempotent “already present” notes

### C. Deploy
- [ ] Deploy API (App Service) from release SHA
- [ ] Deploy frontend (Static Web App / bundled) from same SHA
- [ ] Do **not** change Azure `WORKERS` / pool / health settings in this release

### D. Smoke
- [ ] PIN login works
- [ ] Management Task Dashboard loads (VeeWash layout, Oct-style dates)
- [ ] Expand shared assignment; unfinished checklist → **In Progress**
- [ ] Manager edit times (disposable activity) + reason; duration recalculated
- [ ] Manager void (disposable) → soft-remove; row remains in DB
- [ ] Audit history shows before/after
- [ ] Rinse user: read-only; no Activity Log / Edit / Add / Remove / labor
- [ ] Rinse API: manual/corrected/voided/superseded absent from totals
- [ ] Existing verification approvals unchanged
- [ ] Payroll / attendance punch screens unaffected

### E. Rollback
- [ ] Redeploy production SHA `457c9d5c` if Phase 3 must come off. That keeps the P0 API stability patch
- [ ] Leave additive columns in place (harmless); do not DROP without review
- [ ] Soft-voided rows remain voided if managers already acted — restore via support only if needed

### F. Post-deploy monitoring (30–60 min)
- [ ] `/health` (and existing probes) healthy
- [ ] Error rates / 5xx for `/api/management/task-dashboard*`
- [ ] PIN cleaning-task start/complete latency
- [ ] No MySQL migration locks lingering
- [ ] Spot-check Floor & Washer / shared groups for the business day

---

## 5. P0 integration (done)

| Gate | State |
|---|---|
| Production `origin/main` | `457c9d5c` |
| P0 merged into Phase 3 | **Yes** — merge `8536b1cb` |
| Phase 3 functionality retained | **Yes** — no overlapping files |
| Backend + frontend regression | 64 backend passed, 7 frontend passed |
| Migration applied in production | **No** — wait for deployment approval |

## 6. GO / NO-GO

| Decision | Recommendation |
|---|---|
| Integrated release ready for approval | **GO** — branch tip after this checklist update |
| Production Phase 3 deploy / migration | **NO-GO** until a separate approval |
| Azure P0 settings | **Leave as deployed.** This release does not change them |

---

## 7. Safety constraints (active)

- Do not deploy Phase 3
- Do not apply production migrations
- Do not change Azure configuration
- Do not modify production records
- Do not start Phases 4–6
- P0 is already on production main and on this branch. Do not revert it
