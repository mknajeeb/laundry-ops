# Phase 1 — Official Pay Date & Payroll Report basis

**Status:** Implemented (code). No historical auto-fill.

## Design decisions (approved)

| Decision | Choice |
|----------|--------|
| Monthly Payroll Paid key | Batch-level `payout_batches.official_pay_date` |
| Line inheritance | Report rows inherit batch official date; no wage rewrite |
| JSON date = period end | Treat as **untrusted**; do **not** promote to official |
| YTD (Phase 1) | Unchanged: `COALESCE(payment_date, period_end)` |
| Backfill | None |

## Migration safety

- SQL file uses information_schema + prepared statement — **idempotent** if re-run.
- Runtime `ensure_payout_details_columns()` also guards with `table_has_column` before `ALTER`.
- Safe for existing finalized batches (column remains NULL until assigned).

No line-column changes. No finalized amount rewrites.

## Audit-event structure

Appended to `payout_batches.payout_details_audit_json.events[]`:

```json
{
  "event": "official_pay_date_set | official_pay_date_corrected | payout_details_finalized",
  "actor_id": 41,
  "at": "2026-07-20T18:00:00",
  "detail": "Report membership only; wages/taxes unchanged",
  "old_value": null,
  "new_value": "2026-07-10",
  "reason": "finalization | <user-entered reason>"
}
```

Correction requires `reason` (≥3 chars). Does not change wages, taxes, gross, or net.

## How `official_pay_date` is exposed

| Surface | Fields |
|---------|--------|
| Batch details / workflow | `official_pay_date`, `pay_date_missing`, `pay_date_status` (`set`\|`missing`), `suggested_pay_date` (UI hint only), `finalize_cost_summary` |
| Report row | `official_pay_date`, `pay_date` (= official or empty), `pay_date_missing`, `pay_date_display` (`YYYY-MM-DD` or `Pay Date Missing`), `total_payroll_cost` |
| Finalize API | `POST .../finalize-details` body: `{ official_pay_date, confirm_pay_date: true }` |
| Correction API | `POST .../official-pay-date` body: `{ official_pay_date, reason }` |

Suggested date may equal period end for convenience; it is **never** stored as official unless the user confirms.

## Historical impact counts (read-only, at Phase 1 kickoff)

| Org | Finalized batches | Finalized lines | JSON = period end (untrusted) | JSON ≠ period end | Missing both |
|-----|-------------------|-----------------|-------------------------------|-------------------|--------------|
| veewash (3) | **19** | **75** | **25** | **50** | 0 |
| washpro / washmate / platform | 0 | 0 | 0 | 0 | 0 |

After migration, **all 19** finalized veewash batches have `official_pay_date = NULL` → **Pay Date Missing**, excluded from Monthly Payroll Paid until finance assigns a date with reason.

## UI behavior — missing Pay Date

- Finalized batch without `official_pay_date`: badge **Pay Date Missing** / Needs Review.
- Finalize dialog: require explicit Pay Date + confirmation checkbox; show period, employee count, gross, net, employer taxes, **Total Payroll Cost** (gross + stored ER taxes only), and note: *The Pay Date determines which monthly payroll report this batch appears in.*
- Monthly Payroll Paid: exclude missing; do not use period end or line JSON defaults.
- Period / all-history / custom reports: rows still appear; Pay Date column shows **Pay Date Missing**.
- Admin/finance can set/correct Pay Date with required reason (audit).

## Report types (Phase 1)

1. **Payroll Period Report** — exact period pairs (existing).
2. **Monthly Payroll Paid — Based on Pay Date** — month/year on `official_pay_date` only.
3. **Custom Date Range** — basis **Pay Date** (default) or **Payroll Period Overlap** (explicit). Combined OR removed as default.
4. **All payroll history** — unchanged membership; missing pay dates labeled.

## YTD note (unchanged in Phase 1)

Tax engine YTD still uses:

`YEAR(COALESCE(pbl.payment_date, pb.pay_period_end))`

**Do not** show period end as a confirmed Pay Date in UI or monthly reports.

### YTD consumers to revisit before Phase 2 is complete

| Consumer | Path | Current year basis |
|----------|------|--------------------|
| W-2 YTD gross / quarterly / deductions | `backend/w2_payroll_tax_engine.py` | `COALESCE(payment_date, period_end)` |
| Paystub YTD | `payroll_payout_details` finalized lines | primarily `pay_period_end` |
| Accountant YTD summary | `payroll_operations.accountant_ytd_summary` | inspect before Phase 2 |
| Contractor YTD | `contractor_management.sum_payments_ytd` | `COALESCE(payment_date, invoice_date, period_end, created_at)` |
| Sick / PTO ledger YTD | `payroll_accrual.get_ledger_ytd_totals` | calendar year on ledger (separate) |

**Recommendation (for Phase 2 planning, not implemented now):** migrate W-2 tax YTD to `COALESCE(pb.official_pay_date, pbl.payment_date, pb.pay_period_end)` only after historical official dates are assigned, with a dry-run parity report. Do not flip YTD while official_pay_date is still null on historical batches.

## Rollback plan

1. Deploy previous app revision **or** leave column in place (null-safe).
2. To remove column: `ALTER TABLE payout_batches DROP COLUMN official_pay_date;`
3. Audit JSON events remain harmless historical metadata.
4. No wage/tax data to restore (none rewritten).
