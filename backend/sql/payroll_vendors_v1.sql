-- Staffing vendors for temp / 1099 workers (source company / agency branding).
-- Additive + idempotent. Does not touch wages, taxes, gross, net, OT, or YTD.

CREATE TABLE IF NOT EXISTS payroll_vendors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  address TEXT NULL,
  logo_url VARCHAR(1024) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_vendor_org_name (organization_id, name)
);

-- Worker-level default vendor (guarded via information_schema so re-runs are safe).
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payroll_profiles'
    AND column_name = 'default_vendor_id'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE payroll_profiles ADD COLUMN default_vendor_id INT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Per batch-line vendor override.
SET @col_exists2 := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'payout_batch_lines'
    AND column_name = 'vendor_id'
);
SET @ddl2 := IF(
  @col_exists2 = 0,
  'ALTER TABLE payout_batch_lines ADD COLUMN vendor_id INT NULL',
  'SELECT 1'
);
PREPARE stmt2 FROM @ddl2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;
