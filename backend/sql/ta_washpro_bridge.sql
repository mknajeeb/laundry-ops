-- Run once on `laundryapp` (after backup).
-- Creates TA support tables + `ta_users` (payroll identities), separate from Washpro `users`.
-- Requires existing `roles` table (Washpro RBAC).

SET NAMES utf8mb4;

-- 1) Permission catalog + role→permission map (safe if missing)
CREATE TABLE IF NOT EXISTS permissions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  perm_key VARCHAR(128) NOT NULL UNIQUE,
  description VARCHAR(255) NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_ta_rp_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
  CONSTRAINT fk_ta_rp_perm FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 2) TA staff rows (linked to Washpro login via washpro_user_id)
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

-- Map Washpro roles → TA permissions (Payroll UI uses /api/ta/* which checks these, not only Washpro ADMIN)
-- ADMIN: full TA access
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) = 'ADMIN';

-- OPS / FRONT_DESK: clock + payroll monitor + view staff
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) IN ('OPS', 'FRONT_DESK')
  AND p.perm_key IN ('ta.clock', 'ta.monitor', 'users.view');

-- Legacy role codes (if present from older TA seed)
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) IN ('OPERATIONS', 'SUPERVISOR', 'PAYROLL_ADMIN', 'FINANCE')
  AND p.perm_key IN ('ta.clock', 'ta.monitor', 'users.view', 'ta.override', 'ta.reports', 'finance.payments');
