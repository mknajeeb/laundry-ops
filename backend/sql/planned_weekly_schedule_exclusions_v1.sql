-- Per-week employee exclusions from planned weekly schedule grid/totals.
-- Idempotent.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS planned_weekly_schedule_exclusions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  week_start DATE NOT NULL COMMENT 'Sunday (YYYY-MM-DD) anchoring the schedule week',
  user_id INT NOT NULL COMMENT 'Payroll worker users.id',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pwse_org_week_user (organization_id, week_start, user_id),
  INDEX idx_pwse_org_week (organization_id, week_start),
  CONSTRAINT fk_pwse_excl_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwse_excl_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
