-- Rinse scan-events rows attached to an upload batch (separate from upload_batch_rows).
-- Run manually on laundryapp if auto-migrate via API is not used yet.

CREATE TABLE IF NOT EXISTS upload_batch_scan_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  upload_batch_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  scan_index INT NULL,
  rack VARCHAR(64) NULL,
  time_scanned_raw VARCHAR(255) NULL,
  scanned_at_parsed DATETIME NULL,
  user_name VARCHAR(255) NULL,
  purpose VARCHAR(255) NULL,
  last_location VARCHAR(8) NULL,
  last_scan VARCHAR(8) NULL,
  raw_json JSON NULL,
  source_filename VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ubse_batch (upload_batch_id),
  INDEX idx_ubse_org_batch (organization_id, upload_batch_id),
  INDEX idx_ubse_bag (bag_id),
  INDEX idx_ubse_batch_bag (upload_batch_id, bag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
