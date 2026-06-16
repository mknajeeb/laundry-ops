-- Laundry Ops: hierarchical permission metadata + tenant-scoped custom roles (IDEMPOTENT).
-- BACKUP FIRST. Select default schema in Workbench or: USE laundryapp;
--
-- Safe to re-run after partial success (error 1060 duplicate column avoided).

SET NAMES utf8mb4;

-- USE laundryapp;

SET @db = DATABASE();

-- ---------- permissions: add columns only if missing -------------------------
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'route_key');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN route_key VARCHAR(64) NOT NULL DEFAULT ''general'' COMMENT ''Top: app area / route group'' AFTER description', 'SELECT ''skip permissions.route_key'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'route_label');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN route_label VARCHAR(128) NULL COMMENT ''Display for route'' AFTER route_key', 'SELECT ''skip permissions.route_label'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'section_key');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN section_key VARCHAR(64) NOT NULL DEFAULT '''' COMMENT ''Tab or sub-area within route'' AFTER route_label', 'SELECT ''skip permissions.section_key'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'section_label');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN section_label VARCHAR(128) NULL AFTER section_key', 'SELECT ''skip permissions.section_label'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'resource_key');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN resource_key VARCHAR(64) NOT NULL DEFAULT '''' COMMENT ''Optional finer grouping'' AFTER section_label', 'SELECT ''skip permissions.resource_key'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'resource_label');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN resource_label VARCHAR(128) NULL AFTER resource_key', 'SELECT ''skip permissions.resource_label'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'action_key');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN action_key VARCHAR(32) NOT NULL DEFAULT ''view'' COMMENT ''view|create|update|delete|manage'' AFTER resource_label', 'SELECT ''skip permissions.action_key'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'permissions' AND COLUMN_NAME = 'sort_order');
SET @sql := IF(@has = 0, 'ALTER TABLE permissions ADD COLUMN sort_order INT NOT NULL DEFAULT 0 AFTER action_key', 'SELECT ''skip permissions.sort_order'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- Backfill from existing catalog (safe to re-run)
UPDATE permissions SET
  route_key = 'access',
  route_label = 'People & access',
  section_key = 'users',
  section_label = 'User accounts',
  resource_key = '',
  resource_label = '',
  action_key = 'view',
  sort_order = 10
WHERE perm_key = 'users.view';

UPDATE permissions SET
  route_key = 'access',
  route_label = 'People & access',
  section_key = 'users',
  section_label = 'User accounts',
  action_key = 'create',
  sort_order = 20,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'users.add';

UPDATE permissions SET
  route_key = 'access',
  route_label = 'People & access',
  section_key = 'users',
  section_label = 'User accounts',
  action_key = 'update',
  sort_order = 30,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'users.edit';

UPDATE permissions SET
  route_key = 'access',
  route_label = 'People & access',
  section_key = 'users',
  section_label = 'User accounts',
  action_key = 'delete',
  sort_order = 40,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'users.deactivate';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'clock',
  section_label = 'Clock / sessions',
  action_key = 'manage',
  sort_order = 50,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'ta.clock';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'monitor',
  section_label = 'Live monitor',
  action_key = 'view',
  sort_order = 60,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'ta.monitor';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'adjustments',
  section_label = 'Overrides & corrections',
  action_key = 'update',
  sort_order = 70,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'ta.override';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'configuration',
  section_label = 'Geofences, categories, settings',
  action_key = 'manage',
  sort_order = 80,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'ta.settings';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'reports',
  section_label = 'Reports & exports',
  action_key = 'view',
  sort_order = 90,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'ta.reports';

UPDATE permissions SET
  route_key = 'time_attendance',
  route_label = 'Time & attendance',
  section_key = 'payments',
  section_label = 'Payroll payments',
  action_key = 'update',
  sort_order = 100,
  resource_key = '',
  resource_label = ''
WHERE perm_key = 'finance.payments';

UPDATE permissions SET route_label = route_key WHERE route_label IS NULL OR route_label = '';
UPDATE permissions SET section_label = section_key WHERE (section_label IS NULL OR section_label = '') AND section_key <> '';
UPDATE permissions SET section_label = 'General' WHERE section_key = '' AND (section_label IS NULL OR section_label = '');

-- ---------- roles: tenant scope ------------------------------------------------
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'roles' AND COLUMN_NAME = 'organization_id');
SET @sql := IF(@has = 0, 'ALTER TABLE roles ADD COLUMN organization_id INT NOT NULL DEFAULT 0 COMMENT ''0 = platform template roles visible to all tenants'' AFTER name', 'SELECT ''skip roles.organization_id'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'roles' AND COLUMN_NAME = 'is_system');
SET @sql := IF(@has = 0, 'ALTER TABLE roles ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 = built-in; cannot delete'' AFTER organization_id', 'SELECT ''skip roles.is_system'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

UPDATE roles SET organization_id = 0, is_system = 1
WHERE UPPER(code) IN (
  'ADMIN', 'OPS', 'FRONT_DESK', 'OPERATIONS', 'SUPERVISOR', 'PAYROLL_ADMIN', 'FINANCE', 'ACCOUNTANT', 'PLATFORM_ADMIN', 'SUPER_ADMIN'
);

-- Drop legacy UNIQUE on code only if it still exists (Workbench: SHOW INDEX FROM roles; if name differs, edit below).
SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'roles' AND INDEX_NAME = 'code');
SET @sql := IF(@ix > 0, 'ALTER TABLE roles DROP INDEX code', 'SELECT ''skip roles DROP INDEX code'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SET @ix := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'roles' AND INDEX_NAME = 'uq_roles_org_code');
SET @sql := IF(@ix = 0, 'ALTER TABLE roles ADD UNIQUE KEY uq_roles_org_code (organization_id, code)', 'SELECT ''skip uq_roles_org_code'' AS _note');
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SELECT 'permissions_hierarchy_custom_roles_v1 idempotent pass complete.' AS note;
