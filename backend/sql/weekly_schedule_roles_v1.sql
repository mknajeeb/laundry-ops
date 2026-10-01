-- Weekly schedule: configurable operational roles, per-role time ranges/remarks inside a shift,
-- and daily responsibilities (roles without time slots). Idempotent.
-- Runtime ensure_* functions apply the same DDL lazily; this file is for manual/CI runs.
-- Operational roles only — account permission roles stay in roles / user_roles.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS weekly_schedule_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(40) NOT NULL COMMENT 'Built-in code (sort, lint_cleaning, …) or custom_<slug>',
  name VARCHAR(64) NOT NULL,
  role_group VARCHAR(32) NULL DEFAULT NULL COMMENT 'RINSE_WF | RINSE_HD | DROP_OFF | DHS | SELF_SERVICE | CLEANING',
  display_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  uses_time_slots TINYINT(1) NOT NULL DEFAULT 1,
  remarks_enabled TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wsr_org_code (organization_id, code),
  INDEX idx_wsr_org_order (organization_id, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS planned_weekly_schedule_responsibilities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  week_start DATE NOT NULL COMMENT 'Sunday (YYYY-MM-DD) anchoring the schedule week',
  user_id INT NOT NULL COMMENT 'Payroll worker users.id',
  day_of_week TINYINT NOT NULL COMMENT '0=Sun … 6=Sat',
  role VARCHAR(40) NOT NULL,
  remarks VARCHAR(255) NULL DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pwsr_assignment (organization_id, week_start, user_id, day_of_week, role),
  INDEX idx_pwsr_org_week (organization_id, week_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Fresh databases: planned_weekly_schedule_entries is created at runtime with role_assignments.
SET @has_table := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'planned_weekly_schedule_entries'
);
SET @has_col := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'planned_weekly_schedule_entries'
    AND COLUMN_NAME = 'role_assignments'
);
SET @ddl := IF(
  @has_table = 1 AND @has_col = 0,
  'ALTER TABLE planned_weekly_schedule_entries ADD COLUMN role_assignments TEXT NULL DEFAULT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
