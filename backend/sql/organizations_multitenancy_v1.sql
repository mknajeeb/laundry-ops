-- Multi-tenant foundation: organizations + row-level segregation (IDEMPOTENT).
-- BACKUP FIRST. In Workbench: select your schema as default, or uncomment USE below.
--
-- Safe to re-run after partial success (duplicate column / duplicate key errors avoided).

SET NAMES utf8mb4;

-- Uncomment if you see "No database selected" (1046):
-- USE laundryapp;

CREATE TABLE IF NOT EXISTS organizations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  slug VARCHAR(64) NOT NULL COMMENT 'Stable key: washpro, veewash, …',
  display_name VARCHAR(200) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_org_slug (slug)
) ENGINE=InnoDB;

-- MySQL 8.0.19+ (avoids deprecated VALUES() in ON DUPLICATE KEY UPDATE)
INSERT INTO organizations (id, slug, display_name, active) VALUES
  (1, 'washpro', 'Washpro', 1),
  (2, 'washmate', 'Washmate', 1),
  (3, 'veewash', 'VeeWash', 1) AS new
ON DUPLICATE KEY UPDATE
  display_name = new.display_name,
  active = new.active;

-- --- helpers: run dynamic DDL only when needed --------------------------------

-- users.organization_id
SET @db = DATABASE();
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'users' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE users ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip users.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE users SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'users' AND CONSTRAINT_NAME = 'fk_users_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE users ADD CONSTRAINT fk_users_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_users_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'users' AND INDEX_NAME = 'username');
SET @sql := IF(@ix > 0, 'ALTER TABLE users DROP INDEX username', 'SELECT ''skip drop users.username'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'users' AND INDEX_NAME = 'uq_users_org_username');
SET @sql := IF(@ix = 0, 'ALTER TABLE users ADD UNIQUE KEY uq_users_org_username (organization_id, username)', 'SELECT ''skip uq_users_org_username'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- payroll_period_settings
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_period_settings' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE payroll_period_settings ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip pps.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE payroll_period_settings SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @ai := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_period_settings' AND COLUMN_NAME = 'id' AND EXTRA LIKE '%auto_increment%');
SET @sql := IF(@ai = 0, 'ALTER TABLE payroll_period_settings MODIFY COLUMN id INT NOT NULL AUTO_INCREMENT', 'SELECT ''skip pps id MODIFY'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_period_settings' AND INDEX_NAME = 'uq_payroll_period_org');
SET @sql := IF(@ix = 0, 'ALTER TABLE payroll_period_settings ADD UNIQUE KEY uq_payroll_period_org (organization_id)', 'SELECT ''skip uq_payroll_period_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

INSERT IGNORE INTO payroll_period_settings (organization_id, week_starts_on, ref_prefix)
VALUES (2, 0, 'WM'), (3, 0, 'VW');

-- payroll_cycles
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE payroll_cycles ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip pc.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE payroll_cycles SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND INDEX_NAME = 'cycle_ref');
SET @sql := IF(@ix > 0, 'ALTER TABLE payroll_cycles DROP INDEX cycle_ref', 'SELECT ''skip drop cycle_ref'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND INDEX_NAME = 'uq_org_cycle_ref');
SET @sql := IF(@ix = 0, 'ALTER TABLE payroll_cycles ADD UNIQUE KEY uq_org_cycle_ref (organization_id, cycle_ref)', 'SELECT ''skip uq_org_cycle_ref'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'payroll_cycles' AND CONSTRAINT_NAME = 'fk_payroll_cycles_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE payroll_cycles ADD CONSTRAINT fk_payroll_cycles_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_payroll_cycles_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- geofences
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'geofences' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE geofences ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip geofences.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE geofences SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'geofences' AND CONSTRAINT_NAME = 'fk_geofences_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE geofences ADD CONSTRAINT fk_geofences_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_geofences_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- employment_categories
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'employment_categories' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE employment_categories ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip ec.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE employment_categories SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'employment_categories' AND INDEX_NAME = 'uq_org_ec_code');
SET @sql := IF(@ix = 0, 'ALTER TABLE employment_categories ADD UNIQUE KEY uq_org_ec_code (organization_id, code)', 'SELECT ''skip uq_org_ec_code'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'employment_categories' AND CONSTRAINT_NAME = 'fk_employment_categories_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE employment_categories ADD CONSTRAINT fk_employment_categories_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_employment_categories_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- system_settings (composite PK)
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'system_settings' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE system_settings ADD COLUMN organization_id INT NOT NULL DEFAULT 1 FIRST', 'SELECT ''skip system_settings.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE system_settings SET organization_id = 1 WHERE organization_id IS NULL OR organization_id = 0;

SET @pkcols := (SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION) FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'system_settings' AND CONSTRAINT_NAME = 'PRIMARY');
SET @sql := IF(@pkcols IS NOT NULL AND @pkcols <> 'organization_id,skey', 'ALTER TABLE system_settings DROP PRIMARY KEY, ADD PRIMARY KEY (organization_id, skey)', 'SELECT ''skip system_settings PK'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'system_settings' AND CONSTRAINT_NAME = 'fk_system_settings_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE system_settings ADD CONSTRAINT fk_system_settings_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_system_settings_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- shift_sessions
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE shift_sessions ADD COLUMN organization_id INT NOT NULL DEFAULT 1', 'SELECT ''skip shift_sessions.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE shift_sessions ss
JOIN users u ON u.id = ss.user_id
SET ss.organization_id = IFNULL(u.organization_id, 1);

SET @fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND CONSTRAINT_NAME = 'fk_shift_sessions_org');
SET @sql := IF(@fk = 0, 'ALTER TABLE shift_sessions ADD CONSTRAINT fk_shift_sessions_org FOREIGN KEY (organization_id) REFERENCES organizations(id)', 'SELECT ''skip fk_shift_sessions_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'shift_sessions' AND INDEX_NAME = 'idx_shift_sessions_org');
SET @sql := IF(@ix = 0, 'CREATE INDEX idx_shift_sessions_org ON shift_sessions (organization_id, clock_in_at)', 'SELECT ''skip idx_shift_sessions_org'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- audit_log (optional table)
SET @texist := (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'audit_log');
SET @has := IF(@texist = 0, 1, (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'organization_id'));
SET @sql := IF(@texist > 0 AND @has = 0, 'ALTER TABLE audit_log ADD COLUMN organization_id INT NULL', 'SELECT ''skip audit_log.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @sql := IF(@texist > 0, 'UPDATE audit_log SET organization_id = 1 WHERE organization_id IS NULL', 'SELECT ''skip audit_log update'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SELECT 'organizations_multitenancy_v1 idempotent pass complete.' AS note;
