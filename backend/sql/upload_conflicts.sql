CREATE TABLE IF NOT EXISTS upload_conflicts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  upload_batch_id INT NOT NULL,
  name_clean VARCHAR(255) NOT NULL,
  weight_num DECIMAL(8,2) NULL,
  service_type VARCHAR(10) NOT NULL,
  date_clean DATE NULL,
  rush_type VARCHAR(20) NOT NULL DEFAULT 'NON-RUSH',
  reason VARCHAR(80) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
  overridden_by VARCHAR(100) NULL,
  overridden_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_upload_conflicts_batch (upload_batch_id),
  INDEX idx_upload_conflicts_status (status)
);
