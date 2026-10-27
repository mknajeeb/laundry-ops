-- Checklist Groups: named sections inside a verification checklist.
-- Distinct from task_activity_groups (PIN timers) and assignment_group_id (shared employees).
-- Additive: existing flat checklist items migrate into a default "General" group.

CREATE TABLE IF NOT EXISTS task_checklist_groups (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  checklist_id INT NOT NULL,
  name VARCHAR(80) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_tclg_checklist (organization_id, checklist_id, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- group_id nullable for backward compatibility; ensure_* migrates NULLs into a default group.
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'task_checklist_items'
    AND COLUMN_NAME = 'group_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE task_checklist_items ADD COLUMN group_id INT NULL, ADD INDEX idx_task_cli_group (checklist_id, group_id)',
  'SELECT ''task_checklist_items.group_id already present'' AS note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT 'task_checklist_groups_v1 complete.' AS note;
