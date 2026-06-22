-- HR Timeline — manager-only discipline/performance log (no worker signatures).
-- Apply: scripts/apply_hr_timeline_mysql.sh

CREATE TABLE IF NOT EXISTS hr_timeline_entries (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  entry_type VARCHAR(32) NOT NULL,
  category VARCHAR(64) NOT NULL,
  description TEXT NOT NULL,
  entry_date DATE NOT NULL,
  manager_user_id INT NOT NULL,
  manager_name_snapshot VARCHAR(255) NULL,
  attachment_uri VARCHAR(512) NULL,
  email_template_id VARCHAR(64) NULL,
  email_subject VARCHAR(512) NULL,
  email_body TEXT NULL,
  email_sent_at DATETIME NULL,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_hr_timeline_org_user (organization_id, user_id),
  INDEX idx_hr_timeline_entry_date (entry_date),
  INDEX idx_hr_timeline_type (entry_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
