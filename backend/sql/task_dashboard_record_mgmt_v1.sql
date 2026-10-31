-- Additive: soft-void + record-management audit for Task Dashboard (Phase 3).
-- Safe to re-run (idempotent). Does not physically delete rows.
-- Does not alter historical PIN verification, payroll, or attendance tables.
-- Compatible with existing production data: nullable columns only; no backfill required.

-- ---------------------------------------------------------------------------
-- 1) Soft-void / supersede columns on cleaning_task_activities
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 2) Revisions table (create if missing) + change_type column
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cleaning_task_completion_revisions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  activity_id BIGINT NOT NULL,
  revised_by_user_id INT NOT NULL,
  change_type VARCHAR(32) NOT NULL DEFAULT 'correction',
  reason VARCHAR(500) NOT NULL,
  remarks VARCHAR(1000) NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ctcr_activity (organization_id, activity_id),
  INDEX idx_ctcr_org_created (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @table_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_completion_revisions'
);
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'cleaning_task_completion_revisions'
    AND COLUMN_NAME = 'change_type'
);
SET @sql := IF(
  @table_exists > 0 AND @col_exists = 0,
  'ALTER TABLE cleaning_task_completion_revisions
     ADD COLUMN change_type VARCHAR(32) NOT NULL DEFAULT ''correction'' AFTER revised_by_user_id',
  'SELECT ''cleaning_task_completion_revisions.change_type ready'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT 'task_dashboard_record_mgmt_v1 complete (idempotent).' AS note;
