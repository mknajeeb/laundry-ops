-- Super admin role, tenant contact fields on organizations, per-tenant module entitlements.
-- Idempotent. BACKUP FIRST. USE laundryapp or select schema in Workbench.

SET NAMES utf8mb4;

SET @db = DATABASE();

-- ---- organizations: contact (tenant-editable profile) -------------------------
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'address');
SET @sql := IF(@has = 0, 'ALTER TABLE organizations ADD COLUMN address TEXT NULL COMMENT ''Tenant mailing / street'' AFTER display_name', 'SELECT ''skip organizations.address'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'phone');
SET @sql := IF(@has = 0, 'ALTER TABLE organizations ADD COLUMN phone VARCHAR(64) NULL AFTER address', 'SELECT ''skip organizations.phone'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'organizations' AND COLUMN_NAME = 'email');
SET @sql := IF(@has = 0, 'ALTER TABLE organizations ADD COLUMN email VARCHAR(255) NULL AFTER phone', 'SELECT ''skip organizations.email'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- ---- SUPER_ADMIN role (platform: tenants + module entitlements only) --------
INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('SUPER_ADMIN', 'Super administrator', 0, 1);

UPDATE roles SET organization_id = 0, is_system = 1 WHERE UPPER(code) = 'SUPER_ADMIN';

-- ---- tenant_entitlements: super admin toggles nav / feature areas ------------
CREATE TABLE IF NOT EXISTS tenant_entitlements (
  organization_id INT NOT NULL,
  module_key VARCHAR(64) NOT NULL COMMENT 'home|orders|payroll|...',
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (organization_id, module_key),
  CONSTRAINT fk_tenant_entitlements_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

SELECT 'super_admin_entitlements_v1 complete.' AS note;
