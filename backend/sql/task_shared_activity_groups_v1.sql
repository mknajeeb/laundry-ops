-- Shared Activity Groups: optional collaborative checklist for multi-employee assignments.
-- Additive. Default execution_mode remains 'individual' (existing behavior).

-- Assignment-level mode on weekly schedule responsibilities.
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'planned_weekly_schedule_responsibilities'
    AND COLUMN_NAME = 'execution_mode'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE planned_weekly_schedule_responsibilities ADD COLUMN execution_mode VARCHAR(20) NOT NULL DEFAULT ''individual''',
  'SELECT ''planned_weekly_schedule_responsibilities.execution_mode already present'' AS note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS cleaning_task_shared_sessions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  assignment_group_id VARCHAR(36) NOT NULL,
  business_date DATE NOT NULL,
  role VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  checklist_completed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ctss (organization_id, assignment_group_id, business_date),
  INDEX idx_ctss_org_day (organization_id, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cleaning_task_shared_session_items (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shared_session_id BIGINT NOT NULL,
  task_code VARCHAR(64) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  required TINYINT(1) NOT NULL DEFAULT 1,
  status VARCHAR(32) NOT NULL,
  completed_at DATETIME NULL,
  completed_by_user_id INT NULL,
  completion_input_json TEXT NULL,
  child_activity_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ctssi (shared_session_id, task_code),
  INDEX idx_ctssi_org_session (organization_id, shared_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Link per-employee timers to the shared checklist session.
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'shared_session_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN shared_session_id BIGINT NULL, ADD INDEX idx_cta_shared_session (organization_id, shared_session_id)',
  'SELECT ''cleaning_task_activities.shared_session_id already present'' AS note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'task_shared_activity_groups_v1 complete.' AS note;
