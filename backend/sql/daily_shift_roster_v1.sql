-- Daily shift roster — end-of-day labor recording (not scheduling).
-- Idempotent.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS daily_shift_roster_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  roster_date DATE NOT NULL,
  employee_name VARCHAR(255) NOT NULL,
  role VARCHAR(16) NOT NULL DEFAULT 'folder' COMMENT 'folder | operator',
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  break_minutes INT NOT NULL DEFAULT 0,
  rate DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_dsr_org_date (organization_id, roster_date),
  INDEX idx_dsr_org_date_role (organization_id, roster_date, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
