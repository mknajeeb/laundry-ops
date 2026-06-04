# Payroll Monitor Planning Layer — QA Report

**Report date:** 2026-06-04  
**Phase:** Employee Profile → Scheduling → Partner Roster → Funding Forecast  
**Environment assessed:** Local dev (git workspace) + automated tests  
**Manual UI pass:** Required on staging before sign-off

---

## 1. Production freeze confirmation

| Component | Deployed to production? | Evidence |
|-----------|-------------------------|----------|
| Scheduling Planner | **No** | All files untracked/uncommitted on `main`; no commits on `origin/main` for planning-layer paths |
| Employee Scheduling Profile | **No** | `WorkerSchedulingProfilePanel.jsx`, `worker/` components untracked |
| Partner Roster Share | **No** | `payroll_roster_share.py`, `PartnerRosterPage.jsx`, SQL untracked |
| Payroll Funding Forecast | **No** | `payroll_funding_forecast.py`, `PayrollFundingForecastPanel.jsx` untracked |
| Payroll planning DB migrations | **Not from this repo deploy** | SQL files local only; prior Workbench run of `payroll_roster_share_v1.sql` assumed dev/staging |

**Git:** `main` @ `63aedf0` = `origin/main`. Planning layer is **local working tree only** (`??` / modified, not committed).

**No production deployment date, file list, or migration log** exists in this repository for this phase.

**Rollback:** N/A for production. Do not run planning SQL on production until approved.

**Recommendation:** **Dev/staging only** until staging QA sign-off and explicit deploy approval.

---

## 2. Phase scope

**In scope:** Employee Scheduling Profile, Scheduling Planner, Partner Roster Share, Payroll Funding Forecast.

**Out of scope:** Payroll batch, accountant approval, payout export, W-2/1099 final reporting, pay stubs, approved hours workflow.

---

## 3. Automated tests — 22 passed

```bash
pytest backend/tests/test_payroll_schedule.py \
       backend/tests/test_payroll_roster_share.py \
       backend/tests/test_payroll_funding_forecast.py -q
```

| Area | Status |
|------|--------|
| Schedule math & parameterized defaults | Pass |
| Profile gaps / completeness / readiness | Pass |
| Rate snapshot on save | Pass |
| Partner roster security (9 cases) | Pass |
| Funding forecast (week, draft/publish, categories) | Pass |

Frontend: `npx vitest run src/payroll/schedulePlanner.test.js` (import path fixed).

---

## 4. E2E scenario — manual staging required

Use sample workers: 2× W-2, 2× 1099, 1× Temp, plus Frank (no rate), Grace (no availability), Henry (no skills), Irene (OT), Jake (wrong location).

| Steps 1–20 (profile → schedule → draft → publish → roster → revoke) | Code/logic | Browser |
|---------------------------------------------------------------------|--------------|---------|
| Warnings, live recalc, draft/publish split | Covered by unit tests + client planner | **Pending staging** |

---

## 5. Funding forecast QA

| Check | Status |
|-------|--------|
| Mon–Sun week, Saturday payment | Pass (automated) |
| W-2 / 1099 / Temp breakdown | Pass |
| Draft vs published | Pass |
| Exclude cancelled/replaced/absent/no-show | Pass (code + tests) |
| Sick separate | Pass (code review) |
| W-2 OT; 1099/Temp OT off default | Pass |
| Live update on schedule edit | Pass (client forecast) |
| No forecast on partner roster | Pass |

---

## 6. Snapshot QA

| Behavior | Status |
|----------|--------|
| Publish stores `hourly_rate_snapshot` | Pass |
| Profile rate change does not auto-update published rows | Pass |
| New entries use current profile rate | Pass |
| Draft stale-profile warning | Pass |

**Note:** Editing a published entry and saving re-applies profile rate (explicit edit only).

---

## 7. Partner roster security — Pass (automated)

No rate, cost, OT, forecast, or warnings in public API. Token/PIN/revoke/expired covered by tests. Read-only public page.

---

## 8. UI QA — Pending manual

Review on phone + desktop: scheduling summary, forecast card, drawers, share drawer, public roster. Responsive patterns in code; not browser-verified here.

---

## 9. Remaining issues

- Planning layer **not committed** — needs branch/PR for staging deploy
- Staging migration runbook: `payroll_schedule_v1`, `v2`, `payroll_roster_share_v1`, `payroll_calendar_settings_v1`
- Full browser E2E not executed in this report
- Frontend tests not in CI `package.json`

---

## 10. Verdict

| | |
|--|--|
| **Production deployed?** | **No** |
| **Ready for staging review?** | **Yes — with manual E2E walkthrough** |
| **Ready for production?** | **No** |
| **Proceed to payroll batch?** | **No** |

See also: [SCHEDULING_QA.md](./SCHEDULING_QA.md)
