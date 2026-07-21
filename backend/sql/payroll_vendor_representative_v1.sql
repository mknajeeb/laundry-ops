-- Vendor-level authorized representative (signer) for temp / 1099 receipts.
-- Additive + idempotent. Nullable. Does not touch wages, taxes, gross, net,
-- OT, YTD, Official Pay Dates, or existing vendor identity snapshots.

SET @col_rep_name := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payroll_vendors'
    AND column_name = 'representative_name'
);
SET @ddl_rep_name := IF(
  @col_rep_name = 0,
  'ALTER TABLE payroll_vendors ADD COLUMN representative_name VARCHAR(255) NULL',
  'SELECT 1'
);
PREPARE stmt_rep_name FROM @ddl_rep_name;
EXECUTE stmt_rep_name;
DEALLOCATE PREPARE stmt_rep_name;

SET @col_rep_title := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payroll_vendors'
    AND column_name = 'representative_title'
);
SET @ddl_rep_title := IF(
  @col_rep_title = 0,
  'ALTER TABLE payroll_vendors ADD COLUMN representative_title VARCHAR(255) NULL',
  'SELECT 1'
);
PREPARE stmt_rep_title FROM @ddl_rep_title;
EXECUTE stmt_rep_title;
DEALLOCATE PREPARE stmt_rep_title;
