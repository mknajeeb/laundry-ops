-- Session pay flags: outside/bag deduction exclusions + adjustment remarks (idempotent).

SET @db := DATABASE();

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'geofence_outside_deduction_excluded');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN geofence_outside_deduction_excluded TINYINT(1) NOT NULL DEFAULT 0', 'SELECT ''skip geofence_outside_deduction_excluded'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'laundry_bag_deduction_excluded');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN laundry_bag_deduction_excluded TINYINT(1) NOT NULL DEFAULT 0', 'SELECT ''skip laundry_bag_deduction_excluded'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'period_adjustment_remarks');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN period_adjustment_remarks TEXT NULL', 'SELECT ''skip period_adjustment_remarks'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Legacy: geofence_outside_payable=1 meant "pay for outside" (do not deduct). Map to deduction_excluded=1.
UPDATE shift_sessions SET geofence_outside_deduction_excluded = 1
WHERE geofence_outside_deduction_excluded = 0 AND geofence_outside_payable = 1;
