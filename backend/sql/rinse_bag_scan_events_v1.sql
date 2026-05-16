-- Persistent Rinse scan history by Bag ID (survives daily operational reset).
CREATE TABLE IF NOT EXISTS rinse_bag_scan_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  scan_index INT NULL,
  rack VARCHAR(128) NULL,
  time_scanned_raw VARCHAR(255) NULL,
  scanned_at_parsed DATETIME NULL,
  user_name VARCHAR(255) NULL,
  purpose VARCHAR(255) NULL,
  last_location VARCHAR(8) NULL,
  last_scan VARCHAR(8) NULL,
  source_upload_batch_id INT NULL,
  source_filename VARCHAR(512) NULL,
  raw_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_rbse_org_bag (organization_id, bag_id),
  KEY idx_rbse_org_bag_time (organization_id, bag_id, scanned_at_parsed, scan_index),
  KEY idx_rbse_batch (source_upload_batch_id),
  KEY idx_rbse_org_batch_bag (organization_id, source_upload_batch_id, bag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
