-- Time & Attendance / Payroll module tables (MySQL 8+ / Azure MySQL compatible)
-- Run once against your laundryapp database after backup.

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS payroll_payments;
DROP TABLE IF EXISTS payment_methods;
DROP TABLE IF EXISTS bag_count_summary;
DROP TABLE IF EXISTS bag_rate_maintenance;
DROP TABLE IF EXISTS payroll_adjustments;
DROP TABLE IF EXISTS shift_exceptions;
DROP TABLE IF EXISTS shift_breaks;
DROP TABLE IF EXISTS shift_sessions;
DROP TABLE IF EXISTS payroll_cycles;
DROP TABLE IF EXISTS user_rates;
DROP TABLE IF EXISTS user_employment_categories;
DROP TABLE IF EXISTS user_geofences;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS geofences;
DROP TABLE IF EXISTS employment_categories;
DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS roles;
DROP TABLE IF EXISTS system_settings;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE permissions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  perm_key VARCHAR(128) NOT NULL UNIQUE,
  description VARCHAR(255) NULL
) ENGINE=InnoDB;

CREATE TABLE role_permissions (
  role_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
  CONSTRAINT fk_rp_perm FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE employment_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  active TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE geofences (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  location_description TEXT,
  latitude DECIMAL(10,7) NOT NULL,
  longitude DECIMAL(10,7) NOT NULL,
  radius_meters INT NOT NULL DEFAULT 150,
  active TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  employee_id VARCHAR(64) NULL UNIQUE,
  first_name VARCHAR(128) NOT NULL,
  last_name VARCHAR(128) NOT NULL,
  address TEXT,
  email VARCHAR(255) NOT NULL UNIQUE,
  mobile VARCHAR(32) NULL,
  itin_ssn VARCHAR(32) NULL,
  hire_date DATE NULL,
  termination_date DATE NULL,
  rehired TINYINT(1) DEFAULT 0,
  active TINYINT(1) DEFAULT 1,
  role_id INT NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB;

CREATE TABLE user_geofences (
  user_id INT NOT NULL,
  geofence_id INT NOT NULL,
  is_primary TINYINT(1) DEFAULT 0,
  PRIMARY KEY (user_id, geofence_id),
  CONSTRAINT fk_ug_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ug_geo FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE user_employment_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  employment_category_id INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  CONSTRAINT fk_uec_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_uec_cat FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE user_rates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  employment_category_id INT NOT NULL,
  hourly_rate DECIMAL(12,4) NOT NULL,
  effective_date DATE NOT NULL,
  end_date DATE NULL,
  role_job_function VARCHAR(128) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ur_cat FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id) ON DELETE CASCADE,
  INDEX idx_ur_user_eff (user_id, effective_date)
) ENGINE=InnoDB;

CREATE TABLE payroll_cycles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cycle_ref VARCHAR(64) NOT NULL UNIQUE,
  week_start_date DATE NOT NULL,
  week_end_date DATE NOT NULL,
  status ENUM('open','closed','paid') DEFAULT 'open',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pc_week (week_start_date)
) ENGINE=InnoDB;

CREATE TABLE shift_sessions (
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
  CONSTRAINT fk_ss_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_ss_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id),
  CONSTRAINT fk_ss_geo FOREIGN KEY (geofence_id) REFERENCES geofences(id),
  CONSTRAINT fk_ss_ec FOREIGN KEY (employment_category_id) REFERENCES employment_categories(id),
  INDEX idx_ss_user_in (user_id, clock_in_at),
  INDEX idx_ss_pc (payroll_cycle_id)
) ENGINE=InnoDB;

CREATE TABLE shift_breaks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NOT NULL,
  break_start_at DATETIME NOT NULL,
  break_end_at DATETIME NULL,
  CONSTRAINT fk_sb_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE shift_exceptions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NULL,
  user_id INT NOT NULL,
  exception_type VARCHAR(64) NOT NULL,
  message TEXT,
  severity VARCHAR(32) DEFAULT 'warning',
  resolved TINYINT(1) DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_se_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE SET NULL,
  CONSTRAINT fk_se_user FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_se_user (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE payroll_adjustments (
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
  CONSTRAINT fk_pa_sess FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE SET NULL,
  CONSTRAINT fk_pa_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id) ON DELETE SET NULL,
  CONSTRAINT fk_pa_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_pa_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE bag_rate_maintenance (
  id INT AUTO_INCREMENT PRIMARY KEY,
  rate_per_bag_cents INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  active TINYINT(1) DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE bag_count_summary (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  payroll_cycle_id INT NOT NULL,
  bag_count INT DEFAULT 0,
  deduction_cents INT DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_cycle (user_id, payroll_cycle_id),
  CONSTRAINT fk_bcs_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_bcs_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id)
) ENGINE=InnoDB;

CREATE TABLE payment_methods (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  active TINYINT(1) DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE payroll_payments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  payroll_cycle_id INT NOT NULL,
  user_id INT NOT NULL,
  payment_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  paid_date DATE NULL,
  payment_method_id INT NULL,
  remarks TEXT,
  created_by INT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pp_pc FOREIGN KEY (payroll_cycle_id) REFERENCES payroll_cycles(id),
  CONSTRAINT fk_pp_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_pp_pm FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id),
  CONSTRAINT fk_pp_by FOREIGN KEY (created_by) REFERENCES users(id),
  UNIQUE KEY uq_pp_user_cycle (payroll_cycle_id, user_id)
) ENGINE=InnoDB;

CREATE TABLE audit_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor_user_id INT NULL,
  entity_type VARCHAR(64) NOT NULL,
  entity_id VARCHAR(64) NULL,
  action VARCHAR(64) NOT NULL,
  old_value JSON NULL,
  new_value JSON NULL,
  remarks TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_al_actor FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_al_entity (entity_type, entity_id),
  INDEX idx_al_created (created_at)
) ENGINE=InnoDB;

CREATE TABLE system_settings (
  skey VARCHAR(128) PRIMARY KEY,
  svalue TEXT NOT NULL
) ENGINE=InnoDB;

-- Seed roles
INSERT INTO roles (code, name) VALUES
('ADMIN', 'Admin'),
('PAYROLL_ADMIN', 'Payroll Admin'),
('SUPERVISOR', 'Supervisor'),
('OPERATIONS', 'Operations User'),
('FINANCE', 'Finance User'),
('ACCOUNTANT', 'Accountant');

-- Seed permissions (function-level keys)
INSERT INTO permissions (perm_key, description) VALUES
('users.view', 'View users'),
('users.add', 'Add users'),
('users.edit', 'Edit users'),
('users.deactivate', 'Deactivate users'),
('ta.clock', 'Clock in/out and breaks'),
('ta.monitor', 'Payroll monitor and sessions'),
('ta.override', 'Force clock-out, edit times, adjustments'),
('ta.settings', 'System settings and maintenance'),
('ta.reports', 'Reports and exports'),
('finance.payments', 'Mark payroll paid');

-- Admin gets all
INSERT INTO role_permissions (role_id, permission_id)
SELECT 1, id FROM permissions;

-- Payroll Admin
INSERT INTO role_permissions (role_id, permission_id)
SELECT 2, id FROM permissions WHERE perm_key IN (
  'users.view','ta.clock','ta.monitor','ta.override','ta.reports','finance.payments'
);

-- Supervisor
INSERT INTO role_permissions (role_id, permission_id)
SELECT 3, id FROM permissions WHERE perm_key IN ('users.view','ta.clock','ta.monitor');

-- Operations
INSERT INTO role_permissions (role_id, permission_id)
SELECT 4, id FROM permissions WHERE perm_key IN ('ta.clock');

-- Finance
INSERT INTO role_permissions (role_id, permission_id)
SELECT 5, id FROM permissions WHERE perm_key IN ('users.view','ta.monitor','ta.reports','finance.payments');

-- Accountant (read-only: W-2 documents, approved batches, YTD — users.view only)
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON p.perm_key = 'users.view'
WHERE r.code = 'ACCOUNTANT';

-- Default categories
INSERT INTO employment_categories (code, name, active) VALUES
('WASHPRO_W2', 'Washpro W-2', 1),
('WASHMATE_1099', 'Washmate 1099', 1),
('WASHPRO_1099', 'Washpro 1099', 1);

-- Payment methods
INSERT INTO payment_methods (code, name, active) VALUES
('ACH', 'ACH', 1),
('ZELLE', 'Zelle', 1),
('CHECK', 'Check', 1),
('CASH', 'Cash', 1),
('OTHER', 'Other', 1);

-- System defaults
INSERT INTO system_settings (skey, svalue) VALUES
('max_shift_hours', '14'),
('bag_deduction_enabled', '0');

-- Default bag rate (optional)
INSERT INTO bag_rate_maintenance (rate_per_bag_cents, effective_from, active) VALUES
(0, CURDATE(), 1);

-- Placeholder geofence (replace lat/lng with your facility)
INSERT INTO geofences (name, location_description, latitude, longitude, radius_meters, active) VALUES
('Main Plant', 'Update coordinates to your site', 40.712776, -74.005974, 200, 1);

-- First admin user: run  python backend/seed_ta.py  after applying this schema
