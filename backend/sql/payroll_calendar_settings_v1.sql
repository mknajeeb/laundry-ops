-- Parameterized payroll calendar / funding forecast settings per org and worker category.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS payroll_calendar_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  worker_category VARCHAR(32) NOT NULL DEFAULT 'default' COMMENT 'w2, contractor_1099, temp, or default',
  work_week_start_day TINYINT NOT NULL DEFAULT 0 COMMENT '0=Mon .. 6=Sun',
  work_week_end_day TINYINT NOT NULL DEFAULT 6,
  pay_frequency VARCHAR(16) NOT NULL DEFAULT 'weekly',
  payment_day_of_week TINYINT NOT NULL DEFAULT 5 COMMENT '0=Mon .. 6=Sun; default Saturday=5',
  payment_lag_days INT NOT NULL DEFAULT 0,
  overtime_threshold_hours DECIMAL(6,2) NULL,
  overtime_enabled TINYINT(1) NOT NULL DEFAULT 1,
  overtime_multiplier DECIMAL(4,2) NULL COMMENT 'e.g. 1.5 for time-and-a-half premium calc',
  include_draft_schedule_in_forecast TINYINT(1) NOT NULL DEFAULT 1,
  include_published_schedule_in_forecast TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pcs_org_cat (organization_id, worker_category),
  INDEX idx_pcs_org (organization_id),
  CONSTRAINT fk_pcs_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;
