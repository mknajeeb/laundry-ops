-- Track time outside geofence during active shift + optional checkout fields.
-- Safe to run multiple times.

SET @db := DATABASE();

-- shift_sessions: outside geofence accumulation + optional checkout
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'outside_geofence_seconds');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN outside_geofence_seconds INT NOT NULL DEFAULT 0', 'SELECT ''skip outside_geofence_seconds'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'last_geofence_poll_at');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN last_geofence_poll_at DATETIME NULL', 'SELECT ''skip last_geofence_poll_at'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'last_geofence_inside');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN last_geofence_inside TINYINT(1) NULL', 'SELECT ''skip last_geofence_inside'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'personal_laundry_bags');
SET @sql := IF(@c = 0, 'ALTER TABLE shift_sessions ADD COLUMN personal_laundry_bags INT NULL', 'SELECT ''skip personal_laundry_bags'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
