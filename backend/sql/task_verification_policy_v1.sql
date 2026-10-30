-- Additive: org-global verification defaults + group/task inherit/override flags.
-- Prospective only. Does not rewrite historical cleaning_task_activities rows.

CREATE TABLE IF NOT EXISTS task_verification_org_settings (
  organization_id INT NOT NULL PRIMARY KEY,
  verification_required TINYINT(1) NOT NULL DEFAULT 1,
  verification_method VARCHAR(32) NOT NULL DEFAULT 'supervisor',
  verification_timing VARCHAR(32) NOT NULL DEFAULT 'same_shift',
  verifier_config_json TEXT NULL,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Activity groups: inherit global by default; explicit override stores method/timing/config.
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'task_activity_groups'
    AND COLUMN_NAME = 'verification_inherits'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE task_activity_groups
     ADD COLUMN verification_inherits TINYINT(1) NOT NULL DEFAULT 1,
     ADD COLUMN verification_required TINYINT(1) NULL,
     ADD COLUMN verification_method VARCHAR(32) NULL,
     ADD COLUMN verification_timing VARCHAR(32) NULL,
     ADD COLUMN verifier_config_json TEXT NULL',
  'SELECT ''task_activity_groups verification columns already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Standalone tasks: existing rows stay explicit (inherits=0) to preserve configured policy.
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'weekly_schedule_roles'
    AND COLUMN_NAME = 'verification_inherits'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE weekly_schedule_roles
     ADD COLUMN verification_inherits TINYINT(1) NOT NULL DEFAULT 0',
  'SELECT ''weekly_schedule_roles.verification_inherits already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'task_verification_policy_v1 complete.' AS note;
