# Task Dashboard Phase 3 — Release preparation

**Status:** Release-ready. **Production deployment NOT authorized.**  
**Approved commit / release SHA:** `4236bc5344b7c4854f1fdff2cd636281d89ee0cf`  
**Branch:** `feat/task-dashboard-redesign-record-mgmt`  
**Base (production main at prep time):** `07f3338bb21d42e5dd9521a818d0871f430187c1`  
  (TVP Phases 1–2 already on main)

**Screenshots (keep with release review):** [`docs/phase3-screenshots/`](./phase3-screenshots/)

---

## 1. Production compatibility (P0 API stability)

| Item | Finding |
|---|---|
| `origin/main` tip | `07f3338b` — TVP independent verification |
| P0 commit `8c20b4a7` on main? | **No** (`fix/api-p0-stability` only) |
| File overlap Phase 3 ↔ P0 | **None** |
| Integration into Phase 3 | **Not required** — P0 not deployed |

Do **not** cherry-pick or merge P0 into this release. When P0 is later approved, merge it separately; no overwrite risk with Phase 3 paths (`startup.sh` / `backend/db.py` / `/health/live` untouched here).

---

## 2. Release contents verification

Release delta vs `origin/main` is **exactly one commit** (`4236bc53`) plus any subsequent release-prep docs/SQL hardening on this branch.

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

Out of release: Phases 4–6, Azure config changes, P0 stability patch.

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
- [ ] Confirm P0 still separate / not accidentally reverted
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
- [ ] Redeploy prior SHA (`07f3338b` or last known-good)
- [ ] Leave additive columns in place (harmless); do not DROP without review
- [ ] Soft-voided rows remain voided if managers already acted — restore via support only if needed

### F. Post-deploy monitoring (30–60 min)
- [ ] `/health` (and existing probes) healthy
- [ ] Error rates / 5xx for `/api/management/task-dashboard*`
- [ ] PIN cleaning-task start/complete latency
- [ ] No MySQL migration locks lingering
- [ ] Spot-check Floor & Washer / shared groups for the business day

---

## 5. GO / NO-GO

| Decision | Recommendation |
|---|---|
| Merge / release prep | **GO** (approved SHA + additive migration ready) |
| Production deploy / apply migration | **NO-GO** until explicit final deployment approval |
| Include P0 in this release | **NO** — not on main; keep separate |

---

## 6. Safety constraints (active)

- Do not deploy
- Do not apply production migrations
- Do not change Azure configuration
- Do not modify production records
- Do not start Phases 4–6
