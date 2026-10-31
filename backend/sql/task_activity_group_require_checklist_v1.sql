-- Additive: activity-group "Require Checklist Before Completion".
-- Safe to re-run. Does not update existing rows and does not rewrite activities.
-- NULL is left NULL. Application reads NULL plus required checklist items as ON.
-- Groups with no required items still complete normally. Explicit 0 stays OFF.
-- New groups set the flag in application code (ON when they have required items).

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'task_activity_groups'
    AND COLUMN_NAME = 'require_checklist_before_completion'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE task_activity_groups ADD COLUMN require_checklist_before_completion TINYINT(1) NULL',
  'SELECT ''task_activity_groups.require_checklist_before_completion already present'' AS note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
