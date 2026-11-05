-- Payroll classification cost v1
--
-- Adds two nullable columns. Safe to run more than once.
-- Does not INSERT, UPDATE, or DELETE payroll rows.
-- Does not synchronize batches, change approvals, process payments,
-- or recalculate stored employer taxes.
--
-- NULL payroll_worker_category means "use the profile classification".
-- NULL employer_burden_percent means "not configured".
-- Existing rows stay NULL. Finalized payout lines are not read or written.
-- The live per-record override remains shift_sessions.payroll_classification_override.
-- payroll_worker_category is only a fallback when that override is empty.
-- Neither column is backfilled.
--
-- Older and newer application versions can run with these columns present.
-- Queries name their columns or use a dictionary cursor, so an extra NULL
-- column does not change existing results.
--
-- Rollback that keeps any saved overrides:
--   leave both columns in place and redeploy the previous application.
-- Rollback before any override has been saved:
--   ALTER TABLE shift_sessions DROP COLUMN payroll_worker_category;
--   ALTER TABLE payroll_calendar_settings DROP COLUMN employer_burden_percent;

SET @worker_category_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'shift_sessions'
    AND COLUMN_NAME = 'payroll_worker_category'
);

SET @worker_category_ddl := IF(
  @worker_category_exists = 0,
  'ALTER TABLE shift_sessions ADD COLUMN payroll_worker_category VARCHAR(32) NULL COMMENT ''Per-record classification override. NULL uses the profile category.'' , ALGORITHM=INPLACE, LOCK=NONE',
  'SELECT ''payroll_worker_category already present'' AS migration_status'
);

PREPARE payroll_worker_category_stmt FROM @worker_category_ddl;
EXECUTE payroll_worker_category_stmt;
DEALLOCATE PREPARE payroll_worker_category_stmt;

SET @calendar_table_exists := (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'payroll_calendar_settings'
);

SET @burden_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'payroll_calendar_settings'
    AND COLUMN_NAME = 'employer_burden_percent'
);

SET @burden_ddl := IF(
  @calendar_table_exists = 0,
  'SELECT ''payroll_calendar_settings missing; employer_burden_percent skipped'' AS migration_status',
  IF(
    @burden_exists = 0,
    'ALTER TABLE payroll_calendar_settings ADD COLUMN employer_burden_percent DECIMAL(6,2) NULL COMMENT ''Blank means not configured. 1099 and temp do not inherit W-2 burden.'' , ALGORITHM=INPLACE, LOCK=NONE',
    'SELECT ''employer_burden_percent already present'' AS migration_status'
  )
);

PREPARE employer_burden_stmt FROM @burden_ddl;
EXECUTE employer_burden_stmt;
DEALLOCATE PREPARE employer_burden_stmt;

-- Read-only confirmation. These statements do not modify data.
SELECT
  DATABASE() AS database_name,
  (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'shift_sessions'
      AND COLUMN_NAME = 'payroll_worker_category'
      AND IS_NULLABLE = 'YES'
      AND COLUMN_TYPE = 'varchar(32)'
  ) AS worker_category_column_ok,
  (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'payroll_calendar_settings'
      AND COLUMN_NAME = 'employer_burden_percent'
      AND IS_NULLABLE = 'YES'
      AND DATA_TYPE = 'decimal'
  ) AS burden_column_ok;
