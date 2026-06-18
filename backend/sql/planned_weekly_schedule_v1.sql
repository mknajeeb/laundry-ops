-- Planned weekly schedule — manager-authored labor plan (separate from daily shift roster actuals).
-- Idempotent.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS planned_weekly_schedule_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  week_start DATE NOT NULL COMMENT 'Sunday (YYYY-MM-DD) anchoring the schedule week',
  user_id INT NOT NULL COMMENT 'Payroll worker users.id',
  day_of_week TINYINT NOT NULL COMMENT '0=Sunday .. 6=Saturday',
  role VARCHAR(16) NOT NULL DEFAULT 'folder' COMMENT 'folder | operator',
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  break_minutes INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_pwse_org_week (organization_id, week_start),
  INDEX idx_pwse_org_week_user_day (organization_id, week_start, user_id, day_of_week),
  CONSTRAINT fk_pwse_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwse_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
