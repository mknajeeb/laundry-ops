-- Employer fields for HR forms (I-9, W-4, etc.): structured address + EIN on organizations.
-- Idempotent. Run after organizations exists.

SET NAMES utf8mb4;

SET @db = DATABASE();

-- employer_legal_name: legal entity name on government forms (falls back to display_name in app if null)
SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_legal_name'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_legal_name VARCHAR(255) NULL COMMENT ''Legal employer name for forms'' AFTER display_name',
  'SELECT ''employer_legal_name exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_street'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_street VARCHAR(255) NULL COMMENT ''Street number and name'' AFTER address',
  'SELECT ''employer_street exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_apt'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_apt VARCHAR(64) NULL AFTER employer_street',
  'SELECT ''employer_apt exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_city'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_city VARCHAR(128) NULL AFTER employer_apt',
  'SELECT ''employer_city exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_state'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_state VARCHAR(32) NULL AFTER employer_city',
  'SELECT ''employer_state exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_zip'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_zip VARCHAR(20) NULL AFTER employer_state',
  'SELECT ''employer_zip exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'employer_ein'
);
SET @sql := IF(@c = 0,
  'ALTER TABLE organizations ADD COLUMN employer_ein VARCHAR(32) NULL COMMENT ''Federal EIN (forms)'' AFTER employer_zip',
  'SELECT ''employer_ein exists'' AS note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
