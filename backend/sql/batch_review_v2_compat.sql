-- Compatible migration for older MySQL versions (no ADD COLUMN IF NOT EXISTS support)
-- Schema: laundryapp

SET @db_name = DATABASE();

-- upload_batches.state
SET @sql = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = @db_name
        AND table_name = 'upload_batches'
        AND column_name = 'state'
    ),
    'SELECT "upload_batches.state exists"',
    'ALTER TABLE upload_batches ADD COLUMN state VARCHAR(20) NOT NULL DEFAULT ''DRAFT''' 
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- upload_batches.updated_at
SET @sql = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = @db_name
        AND table_name = 'upload_batches'
        AND column_name = 'updated_at'
    ),
    'SELECT "upload_batches.updated_at exists"',
    'ALTER TABLE upload_batches ADD COLUMN updated_at DATETIME NULL'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- upload_batches.confirmed_at
SET @sql = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = @db_name
        AND table_name = 'upload_batches'
        AND column_name = 'confirmed_at'
    ),
    'SELECT "upload_batches.confirmed_at exists"',
    'ALTER TABLE upload_batches ADD COLUMN confirmed_at DATETIME NULL'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- upload_batches.closed_at
SET @sql = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = @db_name
        AND table_name = 'upload_batches'
        AND column_name = 'closed_at'
    ),
    'SELECT "upload_batches.closed_at exists"',
    'ALTER TABLE upload_batches ADD COLUMN closed_at DATETIME NULL'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- upload_batch_rows table
CREATE TABLE IF NOT EXISTS upload_batch_rows (
  id INT AUTO_INCREMENT PRIMARY KEY,
  upload_batch_id INT NOT NULL,
  date_clean DATE NOT NULL,
  name_clean VARCHAR(255) NOT NULL,
  weight_num DECIMAL(8,2) NULL,
  service_type VARCHAR(10) NOT NULL,
  rush_type VARCHAR(20) NOT NULL DEFAULT 'NON-RUSH',
  row_status VARCHAR(40) NOT NULL DEFAULT 'ACCEPTED',
  reason VARCHAR(100) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,
  INDEX idx_upload_batch_rows_batch (upload_batch_id),
  INDEX idx_upload_batch_rows_status (row_status)
);
