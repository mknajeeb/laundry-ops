-- Operations Planner v2.1. Explicit, idempotent, non-destructive.
-- Version: operations_planner_v2.2
--
-- Apply this file yourself. Application startup, page loads, and PIN login
-- do not create or alter these tables.
--
-- Order: this file only. It does not depend on another planner migration.
-- Compatibility: additive. It does not alter planned_weekly_schedule_entries,
-- attendance, payroll, users, or responsibility/task tables.
-- Existing weekly-schedule rows keep working when these tables are absent.
-- The planner API returns migration_required until every table below exists.
--
-- Rollback: leave the tables in place and keep ops_planner_org_flags at 0.
-- Do not drop them to undo a schedule: they hold patterns, exceptions, and
-- published snapshots. Dropping them deletes planner history and does not
-- restore attendance or payroll, which this migration never changes.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_org_flags (
  organization_id INT NOT NULL PRIMARY KEY,
  manager_pilot TINYINT(1) NOT NULL DEFAULT 0,
  employee_pilot TINYINT(1) NOT NULL DEFAULT 0,
  paystub_access TINYINT(1) NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_patterns (
  id INT NOT NULL PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  day_of_week TINYINT NOT NULL,
  effective_from DATE NOT NULL,
  effective_until DATE NULL,
  shift_json TEXT NOT NULL,
  INDEX idx_opp_org_user (organization_id, user_id, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_exceptions (
  id INT NOT NULL PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  week_monday DATE NOT NULL,
  day_of_week TINYINT NOT NULL,
  kind VARCHAR(16) NOT NULL,
  shift_json TEXT NULL,
  UNIQUE KEY uq_ope_cell (organization_id, user_id, week_monday, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_weeks (
  organization_id INT NOT NULL,
  week_monday DATE NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'draft',
  revision INT NOT NULL DEFAULT 1,
  published_snapshot LONGTEXT NULL,
  published_revision INT NULL,
  approved_by INT NULL,
  approved_at TIMESTAMP NULL DEFAULT NULL,
  published_by INT NULL,
  published_at TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (organization_id, week_monday)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_audit (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  actor_id INT NULL,
  detail_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_opa_org (organization_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_employee_access (
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  schedule_enabled TINYINT(1) NOT NULL DEFAULT 0,
  hours_enabled TINYINT(1) NOT NULL DEFAULT 0,
  paystub_enabled TINYINT(1) NOT NULL DEFAULT 0,
  updated_by INT NULL,
  updated_at TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (organization_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_role_settings (
  organization_id INT NOT NULL,
  role_key VARCHAR(64) NOT NULL,
  show_on_rinse_dashboard TINYINT(1) NOT NULL DEFAULT 0,
  required_headcount INT NULL,
  PRIMARY KEY (organization_id, role_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_role_hours (
  organization_id INT NOT NULL,
  role_key VARCHAR(64) NOT NULL,
  hour_of_day TINYINT NOT NULL,
  required_headcount INT NOT NULL,
  PRIMARY KEY (organization_id, role_key, hour_of_day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_paystub_codes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  code_hash CHAR(64) NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  used_at TIMESTAMP NULL DEFAULT NULL,
  INDEX idx_paystub_code_user (organization_id, user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Staffing intervals are optional. A missing table, or no row for a role and
-- hour, means that hour is not configured. It does not mean zero people are
-- required. This table is not part of the required 2.2 set: the week request
-- still loads when it is absent.
CREATE TABLE IF NOT EXISTS ops_planner_staffing_requirements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_key VARCHAR(64) NOT NULL,
  day_of_week TINYINT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  required_headcount INT NOT NULL,
  INDEX idx_ops_staff_org (organization_id, role_key, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ops_planner_links (
  organization_id INT NOT NULL,
  week_monday DATE NOT NULL,
  user_id INT NOT NULL,
  day_of_week TINYINT NOT NULL,
  entry_id INT NULL,
  PRIMARY KEY (organization_id, week_monday, user_id, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
