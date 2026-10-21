-- Supplemental payout batches.
-- Additive and reversible. Does not update, delete, or backfill any payroll row.
--
-- Idempotent: safe to run more than once.
-- Apply explicitly before deploying the supplemental payout code:
--   python3 scripts/apply_sql_mysql_connector.py backend/sql/payout_batch_supplemental_v1.sql
--
-- Rollback, only when no supplemental batch has been created:
--   ALTER TABLE payout_batches DROP COLUMN supplemental_reason;
--   ALTER TABLE payout_batches DROP COLUMN supplemental_for_user_id;
--
-- NULL means a normal payout batch. Paid batches, time records, approvals,
-- rates, and payment statuses are not modified.

SET @db := DATABASE();

SET @c := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'payout_batches'
    AND COLUMN_NAME = 'supplemental_for_user_id'
);
SET @sql := IF(
  @c = 0,
  'ALTER TABLE payout_batches ADD COLUMN supplemental_for_user_id INT NULL',
  'SELECT ''skip supplemental_for_user_id'' AS migration_status'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'payout_batches'
    AND COLUMN_NAME = 'supplemental_reason'
);
SET @sql := IF(
  @c = 0,
  'ALTER TABLE payout_batches ADD COLUMN supplemental_reason VARCHAR(500) NULL',
  'SELECT ''skip supplemental_reason'' AS migration_status'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
