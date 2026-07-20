-- Phase 1: batch-level official Pay Date for Monthly Payroll Paid reporting.
-- Additive and reversible. Does NOT backfill historical rows.
--
-- Idempotent: safe to run multiple times. Runtime also ensures the column via
-- ensure_payout_details_columns() which checks table_has_column before ALTER.
--
-- Rollback:
--   ALTER TABLE payout_batches DROP COLUMN official_pay_date;
--
-- Notes:
-- - NULL means Pay Date Missing for finalized batches; excluded from Monthly Payroll Paid.
-- - Do not auto-copy line payment.date or period_end into this column.
-- - YTD remains COALESCE(payment_date, period_end) during Phase 1 (see docs).

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'payout_batches'
    AND COLUMN_NAME = 'official_pay_date'
);

SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE payout_batches ADD COLUMN official_pay_date DATE NULL COMMENT ''Official Pay Date for Monthly Payroll Paid; NULL = missing/needs review''',
  'SELECT ''official_pay_date already present'' AS migration_status'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
