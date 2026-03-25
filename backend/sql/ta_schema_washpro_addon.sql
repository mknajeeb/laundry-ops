-- Add Time & Attendance / payroll tables for Washpro (ta_users), without touching Washpro `users`.
-- Run in MySQL Workbench against the SAME database the API uses (e.g. laundryapp).
-- Prerequisites: backup first; `ta_users` + `roles` must already exist (ta_washpro_bridge.sql).
-- Do NOT run backend/schema_ta.sql on production — it DROPs legacy TA tables and can remove Washpro data.

USE laundryapp;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Core lookup / config
CREATE TABLE IF NOT EXISTS employment_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  active TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS geofences (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  location_description TEXT,
  latitude DECIMAL(10,7) NOT NULL,
  longitude DECIMAL(10,7) NOT NULL,
  radius_meters INT NOT NULL DEFAULT 150,
  active TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_cycles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cycle_ref VARCHAR(64) NOT NULL UNIQUE,
  week_start_date DATE NOT NULL,
  week_end_date DATE NOT NULL,
  status ENUM('open','closed','paid') DEFAULT 'open',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pc_week (week_start_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_geofences (
  user_id INT NOT NULL,
  geofence_id INT NOT NULL,
  is_primary TINYINT(1) DEFAULT 0,
  PRIMARY KEY (user_id, geofence_id),
  CONSTRAINT fk_ta_ug_user FOREIGN KEY (user_id) REFERENCES ta_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ta_ug_geo FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_employment_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  employment_category_id INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  CONSTRAINT fk_ta_uec_user FOREIGN KEY (user_id) REFERENCES ta_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ta_uec_cat FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_rates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  employment_category_id INT NOT NULL,
  hourly_rate DECIMAL(12,4) NOT NULL,
  effective_date DATE NOT NULL,
  end_date DATE NULL,
  role_job_function VARCHAR(128) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ta_ur_user FOREIGN KEY (user_id) REFERENCES ta_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ta_ur_cat FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id) ON DELETE CASCADE,
  INDEX idx_ur_user_eff (user_id, effective_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shift_sessions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  payroll_cycle_id INT NOT NULL,
  geofence_id INT NOT NULL,
  employment_category_id INT NULL,
  clock_in_at DATETIME NOT NULL,
  clock_out_at DATETIME NULL,
  clock_in_lat DECIMAL(10,7) NULL,
  clock_in_lng DECIMAL(10,7) NULL,
  clock_out_lat DECIMAL(10,7) NULL,
  clock_out_lng DECIMAL(10,7) NULL,
  total_break_seconds INT DEFAULT 0,
  net_work_seconds INT NULL,
  status ENUM('active','completed','auto_closed') DEFAULT 'active',
  manual_override TINYINT(1) DEFAULT 0,
  CONSTRAINT fk_ta_ss_user FOREIGN KEY (user_id) REFERENCES ta_users(id),
  CONSTRAINT fk_ta_ss_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id),
  CONSTRAINT fk_ta_ss_geo FOREIGN KEY (geofence_id) REFERENCES geofences(id),
  CONSTRAINT fk_ta_ss_ec FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id),
  INDEX idx_ss_user_in (user_id, clock_in_at),
  INDEX idx_ss_pc (payroll_cycle_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shift_breaks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NOT NULL,
  break_start_at DATETIME NOT NULL,
  break_end_at DATETIME NULL,
  CONSTRAINT fk_ta_sb_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shift_exceptions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NULL,
  user_id INT NOT NULL,
  exception_type VARCHAR(64) NOT NULL,
  message TEXT,
  severity VARCHAR(32) DEFAULT 'warning',
  resolved TINYINT(1) DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ta_se_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE SET NULL,
  CONSTRAINT fk_ta_se_user FOREIGN KEY (user_id) REFERENCES ta_users(id),
  INDEX idx_se_user (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_adjustments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NULL,
  payroll_cycle_id INT NULL,
  user_id INT NOT NULL,
  adjustment_type VARCHAR(64) NOT NULL,
  amount_cents INT DEFAULT 0,
  slack_minutes INT DEFAULT 0,
  remarks TEXT NOT NULL,
  created_by INT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ta_pa_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE SET NULL,
  CONSTRAINT fk_ta_pa_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id) ON DELETE SET NULL,
  CONSTRAINT fk_ta_pa_user FOREIGN KEY (user_id) REFERENCES ta_users(id),
  CONSTRAINT fk_ta_pa_by FOREIGN KEY (created_by) REFERENCES ta_users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS bag_rate_maintenance (
  id INT AUTO_INCREMENT PRIMARY KEY,
  rate_per_bag_cents INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  active TINYINT(1) DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS bag_count_summary (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  payroll_cycle_id INT NOT NULL,
  bag_count INT DEFAULT 0,
  deduction_cents INT DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_cycle (user_id, payroll_cycle_id),
  CONSTRAINT fk_ta_bcs_user FOREIGN KEY (user_id) REFERENCES ta_users(id),
  CONSTRAINT fk_ta_bcs_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payment_methods (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  active TINYINT(1) DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_payments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  payroll_cycle_id INT NOT NULL,
  user_id INT NOT NULL,
  payment_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  paid_date DATE NULL,
  payment_method_id INT NULL,
  remarks TEXT,
  created_by INT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ta_pp_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id),
  CONSTRAINT fk_ta_pp_user FOREIGN KEY (user_id) REFERENCES ta_users(id),
  CONSTRAINT fk_ta_pp_pm FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id),
  CONSTRAINT fk_ta_pp_by FOREIGN KEY (created_by) REFERENCES ta_users(id),
  UNIQUE KEY uq_pp_user_cycle (payroll_cycle_id, user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor_user_id INT NULL,
  entity_type VARCHAR(64) NOT NULL,
  entity_id VARCHAR(64) NULL,
  action VARCHAR(64) NOT NULL,
  old_value JSON NULL,
  new_value JSON NULL,
  remarks TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ta_al_actor FOREIGN KEY (actor_user_id) REFERENCES ta_users(id) ON DELETE SET NULL,
  INDEX idx_al_entity (entity_type, entity_id),
  INDEX idx_al_created (created_at)
) ENGINE=InnoDB;

-- TA API expects columns skey + svalue (see backend/ta_routes.py). Some DBs already have a
-- different system_settings shape; CREATE IF NOT EXISTS would skip and seeds would fail.
SET @db := DATABASE();
SET @ss_exists := (
  SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'system_settings'
);
SET @ss_has_skey := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'system_settings' AND COLUMN_NAME = 'skey'
);
SET @ss_backup_exists := (
  SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'system_settings_pre_ta_backup'
);
SET @ss_needs_fix := IF(@ss_exists > 0 AND @ss_has_skey = 0, 1, 0);

SET @ss_fix_sql := IF(
  @ss_needs_fix = 0,
  'DO 0',
  IF(
    @ss_backup_exists > 0,
    CONCAT(
      'SELECT ''system_settings has wrong columns AND system_settings_pre_ta_backup already exists. ',
      'Inspect both tables, merge data if needed, drop the backup name, then re-run this script section.'' AS migration_error'
    ),
    'RENAME TABLE system_settings TO system_settings_pre_ta_backup'
  )
);
PREPARE ss_fix_stmt FROM @ss_fix_sql;
EXECUTE ss_fix_stmt;
DEALLOCATE PREPARE ss_fix_stmt;

CREATE TABLE IF NOT EXISTS system_settings (
  skey VARCHAR(128) PRIMARY KEY,
  svalue TEXT NOT NULL
) ENGINE=InnoDB;

SET FOREIGN_KEY_CHECKS = 1;

-- Minimal seed (idempotent)
INSERT INTO employment_categories (code, name, active)
SELECT 'WASHPRO_W2', 'Washpro W-2', 1
WHERE NOT EXISTS (SELECT 1 FROM employment_categories WHERE code = 'WASHPRO_W2' LIMIT 1);

INSERT INTO employment_categories (code, name, active)
SELECT 'WASHMATE_1099', 'Washmate 1099', 1
WHERE NOT EXISTS (SELECT 1 FROM employment_categories WHERE code = 'WASHMATE_1099' LIMIT 1);

INSERT INTO employment_categories (code, name, active)
SELECT 'WASHPRO_1099', 'Washpro 1099', 1
WHERE NOT EXISTS (SELECT 1 FROM employment_categories WHERE code = 'WASHPRO_1099' LIMIT 1);

INSERT INTO payment_methods (code, name, active)
SELECT 'ACH', 'ACH', 1 WHERE NOT EXISTS (SELECT 1 FROM payment_methods WHERE code = 'ACH' LIMIT 1);
INSERT INTO payment_methods (code, name, active)
SELECT 'ZELLE', 'Zelle', 1 WHERE NOT EXISTS (SELECT 1 FROM payment_methods WHERE code = 'ZELLE' LIMIT 1);
INSERT INTO payment_methods (code, name, active)
SELECT 'CHECK', 'Check', 1 WHERE NOT EXISTS (SELECT 1 FROM payment_methods WHERE code = 'CHECK' LIMIT 1);
INSERT INTO payment_methods (code, name, active)
SELECT 'CASH', 'Cash', 1 WHERE NOT EXISTS (SELECT 1 FROM payment_methods WHERE code = 'CASH' LIMIT 1);
INSERT INTO payment_methods (code, name, active)
SELECT 'OTHER', 'Other', 1 WHERE NOT EXISTS (SELECT 1 FROM payment_methods WHERE code = 'OTHER' LIMIT 1);

INSERT INTO system_settings (skey, svalue)
SELECT 'max_shift_hours', '14'
WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE skey = 'max_shift_hours' LIMIT 1);

INSERT INTO system_settings (skey, svalue)
SELECT 'bag_deduction_enabled', '0'
WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE skey = 'bag_deduction_enabled' LIMIT 1);

INSERT INTO bag_rate_maintenance (rate_per_bag_cents, effective_from, active)
SELECT 0, CURDATE(), 1
WHERE NOT EXISTS (SELECT 1 FROM bag_rate_maintenance LIMIT 1);

INSERT INTO geofences (name, location_description, latitude, longitude, radius_meters, active)
SELECT 'Main Plant', 'Update coordinates to your site', 40.7127760, -74.0059740, 200, 1
WHERE NOT EXISTS (SELECT 1 FROM geofences LIMIT 1);
