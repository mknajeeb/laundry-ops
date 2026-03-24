-- Batch review workflow schema (run manually on laundryapp)

ALTER TABLE upload_batches
  ADD COLUMN IF NOT EXISTS state VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
  ADD COLUMN IF NOT EXISTS updated_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS confirmed_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS closed_at DATETIME NULL;

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
