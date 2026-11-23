-- Explicit role-code migration. Do not run this from a catalog read.
--
-- Adds a nullable three-character label on weekly_schedule_roles.
-- It does not change role ids, codes, or names, and it does not read or
-- write planned_weekly_schedule_entries, planned_weekly_schedule_responsibilities,
-- task execution, payroll, or attendance.
--
-- The previous API ignores this column. A frontend rollback keeps working
-- because inserts that omit short_code store NULL.
--
-- Rollback, only before any saved code must be kept:
--   ALTER TABLE weekly_schedule_roles DROP COLUMN short_code;
-- Dropping the column removes stored codes only. Schedules and tasks stay.

SET NAMES utf8mb4;

SET @has_roles := (
  SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'weekly_schedule_roles'
);
SET @has_short := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'weekly_schedule_roles'
    AND COLUMN_NAME = 'short_code'
);
SET @ddl := IF(
  @has_roles = 1 AND @has_short = 0,
  'ALTER TABLE weekly_schedule_roles ADD COLUMN short_code CHAR(3) NULL DEFAULT NULL',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
