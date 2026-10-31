-- Additive: soft-void + record-management audit for Task Dashboard (Phase 3).
-- Does not physically delete rows. Does not alter historical PIN verification.

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'voided_at'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities
     ADD COLUMN voided_at DATETIME NULL,
     ADD COLUMN voided_by_user_id INT NULL,
     ADD COLUMN void_reason VARCHAR(500) NULL',
  'SELECT ''cleaning_task_activities.voided_at already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND COLUMN_NAME = 'superseded_by_activity_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD COLUMN superseded_by_activity_id BIGINT NULL',
  'SELECT ''cleaning_task_activities.superseded_by_activity_id already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_activities'
    AND INDEX_NAME = 'idx_cta_org_voided'
);
SET @sql := IF(
  @idx_exists = 0,
  'ALTER TABLE cleaning_task_activities ADD INDEX idx_cta_org_voided (organization_id, voided_at)',
  'SELECT ''idx_cta_org_voided already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_completion_revisions'
    AND COLUMN_NAME = 'change_type'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE cleaning_task_completion_revisions
     ADD COLUMN change_type VARCHAR(32) NOT NULL DEFAULT ''correction'' AFTER revised_by_user_id',
  'SELECT ''cleaning_task_completion_revisions.change_type already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'task_dashboard_record_mgmt_v1 complete.' AS note;
