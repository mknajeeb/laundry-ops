-- Multi-tenant foundation: organizations + row-level segregation.
-- BACKUP FIRST. Run against your laundryapp database.
--
-- Resolves:
--   • Multiple operators (Washpro, Washmate, VeeWash, …) sharing one deployment.
--   • Payroll/TA rows scoped by organization_id with existing data defaulted to org 1.
--
-- Verify before running:
--   SHOW CREATE TABLE users;
--   SHOW INDEX FROM users;
--   SHOW CREATE TABLE payroll_period_settings;
--   SHOW INDEX FROM payroll_cycles;
--
-- If any ALTER fails (duplicate FK, index name differs), adjust the statement and re-run the remaining blocks.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS organizations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  slug VARCHAR(64) NOT NULL COMMENT 'Stable key: washpro, veewash, …',
  display_name VARCHAR(200) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_org_slug (slug)
) ENGINE=InnoDB;

INSERT INTO organizations (id, slug, display_name, active) VALUES
  (1, 'washpro', 'Washpro', 1),
  (2, 'washmate', 'Washmate', 1),
  (3, 'veewash', 'VeeWash', 1)
ON DUPLICATE KEY UPDATE
  display_name = VALUES(display_name),
  active = VALUES(active);

-- --- Users: per-org username uniqueness ------------------------------------
ALTER TABLE users ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE users SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

ALTER TABLE users ADD CONSTRAINT fk_users_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

-- Replace global unique username (index name may be `username` — change if needed)
ALTER TABLE users DROP INDEX username;

ALTER TABLE users ADD UNIQUE KEY uq_users_org_username (organization_id, username);

-- --- Payroll period settings: one row per org -----------------------------
ALTER TABLE payroll_period_settings ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE payroll_period_settings SET organization_id = 1;

ALTER TABLE payroll_period_settings MODIFY COLUMN id INT NOT NULL AUTO_INCREMENT;

ALTER TABLE payroll_period_settings ADD UNIQUE KEY uq_payroll_period_org (organization_id);

INSERT IGNORE INTO payroll_period_settings (organization_id, week_starts_on, ref_prefix)
VALUES (2, 0, 'WM'), (3, 0, 'VW');

-- --- Payroll cycles --------------------------------------------------------
ALTER TABLE payroll_cycles ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE payroll_cycles SET organization_id = 1;

ALTER TABLE payroll_cycles DROP INDEX cycle_ref;

ALTER TABLE payroll_cycles ADD UNIQUE KEY uq_org_cycle_ref (organization_id, cycle_ref);

ALTER TABLE payroll_cycles ADD CONSTRAINT fk_payroll_cycles_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

-- --- Geofences & employment categories -------------------------------------
ALTER TABLE geofences ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE geofences SET organization_id = 1;

ALTER TABLE geofences ADD CONSTRAINT fk_geofences_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

ALTER TABLE employment_categories ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE employment_categories SET organization_id = 1;

ALTER TABLE employment_categories ADD UNIQUE KEY uq_org_ec_code (organization_id, code);

ALTER TABLE employment_categories ADD CONSTRAINT fk_employment_categories_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

-- --- system_settings: per-org key/value ------------------------------------
ALTER TABLE system_settings ADD COLUMN organization_id INT NOT NULL DEFAULT 1 FIRST;

UPDATE system_settings SET organization_id = 1;

ALTER TABLE system_settings DROP PRIMARY KEY, ADD PRIMARY KEY (organization_id, skey);

ALTER TABLE system_settings ADD CONSTRAINT fk_system_settings_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

-- --- Shift sessions ---------------------------------------------------------
ALTER TABLE shift_sessions ADD COLUMN organization_id INT NOT NULL DEFAULT 1;

UPDATE shift_sessions ss
JOIN users u ON u.id = ss.user_id
SET ss.organization_id = IFNULL(u.organization_id, 1);

ALTER TABLE shift_sessions ADD CONSTRAINT fk_shift_sessions_org FOREIGN KEY (organization_id) REFERENCES organizations(id);

CREATE INDEX idx_shift_sessions_org ON shift_sessions (organization_id, clock_in_at);

-- --- Audit log (optional tenant filter) ------------------------------------
ALTER TABLE audit_log ADD COLUMN organization_id INT NULL;

UPDATE audit_log SET organization_id = 1 WHERE organization_id IS NULL;
