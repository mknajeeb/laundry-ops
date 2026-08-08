-- Phase 5E — mobile Revenue & Cost section entry.
-- Amounts authority remains dr_daily_entries / dr_daily_entry_lines.
-- These tables own weekday assignment + section draft/submit/review overlay.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS drc_weekday_section_assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  weekday TINYINT NOT NULL COMMENT 'Python date.weekday(): Mon=0 .. Sun=6',
  section_key VARCHAR(40) NOT NULL,
  employee_id INT NULL,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_drc_weekday_org_day_section (organization_id, weekday, section_key),
  INDEX idx_drc_weekday_org_emp (organization_id, employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS drc_mobile_section_submissions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  entry_date DATE NOT NULL COMMENT 'ET business date via business_today()',
  section_key VARCHAR(40) NOT NULL,
  assigned_employee_id INT NOT NULL,
  assigned_employee_name VARCHAR(150) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  draft_revision INT NOT NULL DEFAULT 0,
  values_json JSON NULL,
  calculated_json JSON NULL,
  rate_snapshot_json JSON NULL,
  note VARCHAR(500) NULL,
  rejection_reason VARCHAR(500) NULL,
  daily_entry_id INT NULL COMMENT 'FK soft-link to applied dr_daily_entries.id',
  submitted_at DATETIME NULL,
  submitted_by_user_id INT NULL,
  reviewed_at DATETIME NULL,
  reviewed_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_drc_mobile_org_date_section (organization_id, entry_date, section_key),
  INDEX idx_drc_mobile_org_status (organization_id, status),
  INDEX idx_drc_mobile_org_emp (organization_id, assigned_employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS drc_mobile_section_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  submission_id INT NOT NULL,
  organization_id INT NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  actor_user_id INT NULL,
  detail_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_drc_mobile_evt_sub (submission_id),
  INDEX idx_drc_mobile_evt_org (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'drc_mobile_entry_v1 complete.' AS note;
