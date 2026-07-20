# Release notes — Payroll Report & OT Premium

**Date:** 2026-07-19  
**Status:** Complete (production verified 2026-07-20) · Phase 1 Official Pay Date implemented (additive; no historical backfill)

## Summary

- New **Payroll Report** tab with period, date-range, employee, category, payroll-status, and payment-status filters
- Excel and PDF exports
- OT columns now show only the premium paid above the regular rate
- No changes to stored payroll values or gross-pay calculations

## Phase 1 — Official Pay Date (2026-07-20)

- Batch-level `official_pay_date` required for new finalizations (explicit confirm)
- Report types: Payroll Period · Monthly Payroll Paid (pay date only) · Custom Date Range (Pay Date default | Period Overlap) · All history
- Missing official dates show **Pay Date Missing**; excluded from Monthly Payroll Paid
- Finance/admin correction requires reason + audit; report membership only
- Total Payroll Cost on finalize confirmation = Gross + stored employer taxes
- Grouped PDF by report type; Excel remains record-level
- YTD unchanged: still `COALESCE(payment_date, period_end)` — see `docs/payroll-qa/PHASE1_OFFICIAL_PAY_DATE.md`
- No Phase 2–4 labor-cost / volume work in this change

## Production verification (final QA)

**Commit:** `2c9e4cefb247e89ceb37ce09e74c9dddbef19d2a`

| Check | Result |
|--------|--------|
| Payroll Report all-history | 96 records |
| Custom July report | 27 records; gross $16,262.29; OT Premium $73.53 |
| Category totals | W-2 44; 1099 18; Temp 34 |
| Register / paystub (OT) | Varun Kumar Mongia — 8.65 OT hours; Base $827.05; OT Premium $73.53; Gross $900.58 |
| Excel / PDF / screen / register / paystub | Matched |
| Unauthorized user | 403 |
| Unauthenticated request | 401 |
| Migrations / backfills / payroll recalcs / stored-value changes | None |
| Production mismatches | None |

**Feature status:** Complete.

**Infrastructure follow-up (not payroll):** sync GitHub secret `AZURE_STATIC_WEB_APPS_API_TOKEN_ZEALOUS_BAY_0FB502610` with the current Azure Static Web Apps deployment token when CLI auth is available.
