-- Run once on `laundryapp` (after backup).
-- Creates `ta_users` (payroll / TA identities) separate from Washpro login `users`.
-- Links a TA row to a Washpro account via washpro_user_id (auto-filled on first /api/ta/* call).
--
-- You also need: `roles`, `permissions`, `role_permissions`, `geofences`, shift tables, etc.
-- If those are missing, apply `backend/schema_ta.sql` on a copy first and merge, or run a fresh TA install on a dev DB.
-- Minimum: `permissions` rows for ta.clock (see INSERT IGNORE below) and `roles` + `role_permissions` so staff have ta.clock.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ta_users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  washpro_user_id INT NULL UNIQUE,
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
  CONSTRAINT fk_ta_users_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB;

INSERT IGNORE INTO permissions (perm_key, description) VALUES
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

-- Allow clock permission for common Washpro role codes (adjust list to match your `roles.code` values)
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE p.perm_key = 'ta.clock'
  AND UPPER(r.code) IN ('ADMIN', 'OPS', 'OPERATIONS', 'FRONT_DESK', 'SUPERVISOR', 'PAYROLL_ADMIN', 'FINANCE');
