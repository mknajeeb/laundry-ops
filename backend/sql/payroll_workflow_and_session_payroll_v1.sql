-- Payroll cycle review workflow + session-level pay adjustments (idempotent).
-- Run once against the app database after backup.

SET @db := DATABASE();

-- payroll_cycles: batch review (submit → approve before broad monitor visibility)
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND COLUMN_NAME = 'review_state');
SET @sql := IF(@c = 0, 'ALTER TABLE payroll_cycles ADD COLUMN review_state VARCHAR(32) NULL', 'SELECT ''skip payroll_cycles.review_state'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE payroll_cycles SET review_state = 'approved' WHERE review_state IS NULL;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND COLUMN_NAME = 'review_state');
SET @sql := IF(@c > 0,
  'ALTER TABLE payroll_cycles MODIFY COLUMN review_state VARCHAR(32) NOT NULL DEFAULT ''open''',
  'SELECT ''skip modify review_state'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND COLUMN_NAME = 'submitted_at');
SET @sql := IF(@c = 0, 'ALTER TABLE payroll_cycles ADD COLUMN submitted_at DATETIME NULL', 'SELECT ''skip submitted_at'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND COLUMN_NAME = 'approved_at');
SET @sql := IF(@c = 0, 'ALTER TABLE payroll_cycles ADD COLUMN approved_at DATETIME NULL', 'SELECT ''skip approved_at'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- shift_sessions: include/exclude outside-geofence time from pay + period-close $ lines
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'geofence_outside_payable');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN geofence_outside_payable TINYINT(1) NOT NULL DEFAULT 1', 'SELECT ''skip geofence_outside_payable'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'period_bonus_cents');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN period_bonus_cents INT NOT NULL DEFAULT 0', 'SELECT ''skip period_bonus_cents'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'period_deduction_cents');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN period_deduction_cents INT NOT NULL DEFAULT 0', 'SELECT ''skip period_deduction_cents'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
