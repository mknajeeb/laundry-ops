-- Payroll scheduling v2: draft/publish, coverage targets, change log, balancing thresholds.

SET NAMES utf8mb4;

-- Column adds are applied idempotently by ensure_payroll_schedule_v2() in payroll_schedule_planner.py
-- (MySQL 8.0 on Azure does not support ADD COLUMN IF NOT EXISTS in ALTER TABLE).

CREATE TABLE IF NOT EXISTS payroll_schedule_coverage_targets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  day_of_week TINYINT NULL COMMENT '0=Mon .. 6=Sun, NULL=all days',
  shift_id INT NOT NULL,
  work_stream_id INT NOT NULL,
  role_id INT NOT NULL,
  required_count INT NOT NULL DEFAULT 1,
  active TINYINT(1) NOT NULL DEFAULT 1,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_psct_org (organization_id, active),
  CONSTRAINT fk_psct_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_psct_shift FOREIGN KEY (shift_id) REFERENCES payroll_shifts(id) ON DELETE CASCADE,
  CONSTRAINT fk_psct_stream FOREIGN KEY (work_stream_id) REFERENCES payroll_work_streams(id) ON DELETE CASCADE,
  CONSTRAINT fk_psct_role FOREIGN KEY (role_id) REFERENCES payroll_roles(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_schedule_change_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  schedule_entry_id INT NULL,
  action VARCHAR(32) NOT NULL,
  old_snapshot JSON NULL,
  new_snapshot JSON NULL,
  changed_by INT NULL,
  change_note TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pscl_org_date (organization_id, created_at),
  INDEX idx_pscl_entry (schedule_entry_id),
  CONSTRAINT fk_pscl_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_pscl_entry FOREIGN KEY (schedule_entry_id) REFERENCES payroll_schedule_entries(id) ON DELETE SET NULL
) ENGINE=InnoDB;
