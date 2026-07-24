-- Maintenance Task List v2 — weekday assignee + category snapshots (idempotent).
-- Phase 5B: daily operational checklist assignment (not a maintenance management platform).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_weekday_assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  weekday TINYINT NOT NULL COMMENT 'Python date.weekday(): Mon=0 .. Sun=6',
  employee_id INT NULL,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_mtl_weekday_org_day (organization_id, weekday),
  INDEX idx_mtl_weekday_org_emp (organization_id, employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Category on template definitions (manager-maintained free text).
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'maintenance_task_definitions'
    AND column_name = 'category'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE maintenance_task_definitions ADD COLUMN category VARCHAR(80) NULL AFTER description',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Category snapshotted onto daily items (historical immutability).
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'maintenance_task_list_items'
    AND column_name = 'category_snapshot'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE maintenance_task_list_items ADD COLUMN category_snapshot VARCHAR(80) NULL AFTER task_description_snapshot',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'maintenance_task_list_v2_weekday_assignment complete.' AS note;
