-- Per-organization branding: logo_url on organizations.
-- Idempotent: safe to run multiple times. Run after organizations table exists
-- (e.g. after organizations_multitenancy_v1.sql).

SET NAMES utf8mb4;

SET @db = DATABASE();
SET @has_logo := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'logo_url'
);

SET @sql := IF(
  @has_logo = 0,
  'ALTER TABLE organizations ADD COLUMN logo_url VARCHAR(768) NULL COMMENT ''HTTPS URL to organization logo image'' AFTER display_name',
  'SELECT ''organizations.logo_url already exists'' AS note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
