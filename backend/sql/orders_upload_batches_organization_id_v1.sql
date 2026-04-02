-- Laundry Ops: tenant-scope operational tables (re-runnable; skips existing columns/indexes/FKs).
-- Run after organizations / multitenancy exists. BACKUP FIRST.
-- In Workbench: use the correct schema (e.g. USE laundryapp;) not laundrydb unless that is your DB name.
--
-- Error 1060 "Duplicate column": you already have organization_id on that table; this script skips it.

SET NAMES utf8mb4;

-- ---------- orders_staging ----------
SET @t = 'orders_staging';
SET @exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = @t AND COLUMN_NAME = 'organization_id'
);
-- Do not use AFTER id: some tables use batch_id or other PK names; column order does not affect the app.
SET @sql = IF(@exists = 0,
  'ALTER TABLE orders_staging ADD COLUMN organization_id INT NOT NULL DEFAULT 1 COMMENT ''Tenant FK''',
  'SELECT ''skip: orders_staging.organization_id already exists'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @fk = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'orders_staging' AND CONSTRAINT_NAME = 'fk_orders_staging_org'
);
SET @sql = IF(@fk = 0,
  'ALTER TABLE orders_staging ADD CONSTRAINT fk_orders_staging_org FOREIGN KEY (organization_id) REFERENCES organizations(id)',
  'SELECT ''skip: fk_orders_staging_org'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @ix = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders_staging' AND INDEX_NAME = 'idx_orders_staging_org'
);
SET @sql = IF(@ix = 0,
  'CREATE INDEX idx_orders_staging_org ON orders_staging (organization_id, batch_date)',
  'SELECT ''skip: idx_orders_staging_org'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

-- ---------- upload_batches ----------
SET @t = 'upload_batches';
SET @exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = @t AND COLUMN_NAME = 'organization_id'
);
SET @sql = IF(@exists = 0,
  'ALTER TABLE upload_batches ADD COLUMN organization_id INT NOT NULL DEFAULT 1 COMMENT ''Tenant FK''',
  'SELECT ''skip: upload_batches.organization_id already exists'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @fk = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_batches' AND CONSTRAINT_NAME = 'fk_upload_batches_org'
);
SET @sql = IF(@fk = 0,
  'ALTER TABLE upload_batches ADD CONSTRAINT fk_upload_batches_org FOREIGN KEY (organization_id) REFERENCES organizations(id)',
  'SELECT ''skip: fk_upload_batches_org'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @ix = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'upload_batches' AND INDEX_NAME = 'idx_upload_batches_org'
);
SET @sql = IF(@ix = 0,
  'CREATE INDEX idx_upload_batches_org ON upload_batches (organization_id, batch_date)',
  'SELECT ''skip: idx_upload_batches_org'' AS migration_note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

-- ---------- orders_final (only if table exists) ----------
SET @t = 'orders_final';
SET @tbl_orders_final = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders_final'
);
SET @exists = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = @t AND COLUMN_NAME = 'organization_id'
);
SET @sql = IF(@tbl_orders_final = 0,
  'SELECT ''skip: orders_final table missing'' AS migration_note',
  IF(@exists = 0,
    'ALTER TABLE orders_final ADD COLUMN organization_id INT NOT NULL DEFAULT 1 COMMENT ''Tenant FK''',
    'SELECT ''skip: orders_final.organization_id already exists'' AS migration_note'));
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @fk = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'orders_final' AND CONSTRAINT_NAME = 'fk_orders_final_org'
);
SET @sql = IF(@tbl_orders_final = 0,
  'SELECT ''skip: orders_final FK (no table)'' AS migration_note',
  IF(@fk = 0,
    'ALTER TABLE orders_final ADD CONSTRAINT fk_orders_final_org FOREIGN KEY (organization_id) REFERENCES organizations(id)',
    'SELECT ''skip: fk_orders_final_org'' AS migration_note'));
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @ix = (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders_final' AND INDEX_NAME = 'idx_orders_final_org'
);
SET @sql = IF(@tbl_orders_final = 0,
  'SELECT ''skip: orders_final index (no table)'' AS migration_note',
  IF(@ix = 0,
    'CREATE INDEX idx_orders_final_org ON orders_final (organization_id, cleaned_at)',
    'SELECT ''skip: idx_orders_final_org'' AS migration_note'));
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SELECT 'Laundry Ops tenant columns migration finished (idempotent).' AS result;
