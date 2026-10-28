-- Additive: supervisor manual completion + correction audit for Task Dashboard.
-- Does not alter historical PIN completions; defaults keep source='pin'.

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'completion_source'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN completion_source VARCHAR(32) NOT NULL DEFAULT ''pin''',
  'SELECT ''cleaning_task_activities.completion_source already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'recorded_by_user_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN recorded_by_user_id INT NULL',
  'SELECT ''cleaning_task_activities.recorded_by_user_id already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'manual_reason'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN manual_reason VARCHAR(500) NULL',
  'SELECT ''cleaning_task_activities.manual_reason already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'manual_remarks'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN manual_remarks VARCHAR(1000) NULL',
  'SELECT ''cleaning_task_activities.manual_remarks already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'times_manual'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN times_manual TINYINT(1) NOT NULL DEFAULT 0',
  'SELECT ''cleaning_task_activities.times_manual already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS cleaning_task_completion_revisions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  activity_id BIGINT NOT NULL,
  revised_by_user_id INT NOT NULL,
  reason VARCHAR(500) NOT NULL,
  remarks VARCHAR(1000) NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ctcr_activity (organization_id, activity_id),
  INDEX idx_ctcr_org_created (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'task_dashboard_manual_completion_v1 complete.' AS note;
