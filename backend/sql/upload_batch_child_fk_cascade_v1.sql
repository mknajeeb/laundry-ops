-- Orphan cleanup + ON DELETE CASCADE for upload batch children (all tenants).
-- Idempotent: run via scripts/check_upload_batch_orphans.py --fix or app migration helper.
-- BACKUP FIRST.

SET NAMES utf8mb4;

-- Orphan upload_batch_rows (no parent batch)
DELETE ubr FROM upload_batch_rows ubr
LEFT JOIN upload_batches ub ON ubr.upload_batch_id = ub.id
WHERE ub.id IS NULL;

-- If your PK is batch_id instead of id, also run (uncomment one set that matches your schema):
-- DELETE ubr FROM upload_batch_rows ubr
-- LEFT JOIN upload_batches ub ON ubr.upload_batch_id = ub.batch_id
-- WHERE ub.batch_id IS NULL;

-- Orphan upload_batch_scan_events
DELETE ubse FROM upload_batch_scan_events ubse
LEFT JOIN upload_batches ub ON ubse.upload_batch_id = ub.id
WHERE ub.id IS NULL;

-- FK upload_batch_rows (adjust parent column id vs batch_id to match SHOW COLUMNS FROM upload_batches)
SET @fk = (
  SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'upload_batch_rows'
    AND CONSTRAINT_NAME = 'fk_ubr_upload_batch'
);
SET @sql = IF(@fk = 0,
  'ALTER TABLE upload_batch_rows ADD CONSTRAINT fk_ubr_upload_batch FOREIGN KEY (upload_batch_id) REFERENCES upload_batches(id) ON DELETE CASCADE',
  'SELECT ''skip: fk_ubr_upload_batch'' AS note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SET @fk = (
  SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'upload_batch_scan_events'
    AND CONSTRAINT_NAME = 'fk_ubse_upload_batch'
);
SET @sql = IF(@fk = 0,
  'ALTER TABLE upload_batch_scan_events ADD CONSTRAINT fk_ubse_upload_batch FOREIGN KEY (upload_batch_id) REFERENCES upload_batches(id) ON DELETE CASCADE',
  'SELECT ''skip: fk_ubse_upload_batch'' AS note');
PREPARE _stmt FROM @sql;
EXECUTE _stmt;
DEALLOCATE PREPARE _stmt;

SELECT 'upload_batch_child_fk_cascade_v1 finished' AS result;
