-- Fast kiosk PIN lookup: filter candidates by last 4 digits before bcrypt verify.
SET @db := DATABASE();

SET @c := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_profiles' AND COLUMN_NAME = 'attendance_pin_last4'
);
SET @sql := IF(
  @c = 0,
  'ALTER TABLE payroll_profiles ADD COLUMN attendance_pin_last4 VARCHAR(4) NULL',
  'SELECT ''skip attendance_pin_last4'' AS _note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ix := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_profiles' AND INDEX_NAME = 'idx_pp_pin_last4'
);
SET @sql := IF(
  @ix = 0,
  'CREATE INDEX idx_pp_pin_last4 ON payroll_profiles (attendance_pin_last4)',
  'SELECT ''skip idx_pp_pin_last4'' AS _note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
