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

## 5. Hold for P0 (active)

P0 API stability takes priority over Phase 3 deploy.

| Gate | State (as of last check) |
|---|---|
| Production `origin/main` | `07f3338b` |
| P0 `8c20b4a7` on main | **Not yet** |
| Phase 3 release tip | `7209cf4211118f5b9c4433807d0162b1cea2b365` |

**After P0 deploys successfully, before Phase 3 deploy:**

1. Reconfirm new production `origin/main` SHA (must include P0)
2. Merge/rebase deployed P0 into `feat/task-dashboard-redesign-record-mgmt` without dropping Phase 3
3. Preserve all Phase 3 functionality (dashboard, Rinse scope, record mgmt, shared checklist)
4. Rerun affected backend + frontend regression tests
5. Re-verify `task_dashboard_record_mgmt_v1.sql` compatibility
6. Confirm VeeWash + Rinse UI behavior unchanged
7. Return final integrated release SHA + readiness; **STOP** for Phase 3 deploy approval

Do not apply Phase 3 migration or modify production data during the hold.

## 6. GO / NO-GO

| Decision | Recommendation |
|---|---|
| Keep Phase 3 release ready | **GO** (`7209cf42`) |
| Production Phase 3 deploy / migration | **NO-GO** — waiting on P0 deploy + re-integration |
| Cherry-pick undeployed P0 into Phase 3 now | **NO** — wait for P0 on production main first |

---

## 7. Safety constraints (active)

- Do not deploy Phase 3
- Do not apply production migrations
- Do not change Azure configuration
- Do not modify production records
- Do not start Phases 4–6
- Do not integrate P0 until it is on production main
