-- Laundry Ops: hierarchical permission metadata + tenant-scoped custom roles.
-- BACKUP FIRST. Run against your app database (e.g. USE laundryapp;).
--
-- 1) Extends `permissions` with route / section / resource / action (for UI + future checks).
-- 2) Extends `roles` with organization_id (0 = platform templates) and is_system (1 = cannot delete).
-- 3) Replaces UNIQUE(code) with UNIQUE(organization_id, code) so each tenant can define e.g. MANAGER.

SET NAMES utf8mb4;

-- ---------- permissions: add columns (skip manually if already present / error 1060) ----------
ALTER TABLE permissions
  ADD COLUMN route_key VARCHAR(64) NOT NULL DEFAULT 'general' COMMENT 'Top: app area / route group' AFTER description;

ALTER TABLE permissions
  ADD COLUMN route_label VARCHAR(128) NULL COMMENT 'Display for route' AFTER route_key;

ALTER TABLE permissions
  ADD COLUMN section_key VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'Tab or sub-area within route' AFTER route_label;

ALTER TABLE permissions
  ADD COLUMN section_label VARCHAR(128) NULL AFTER section_key;

ALTER TABLE permissions
  ADD COLUMN resource_key VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'Optional finer grouping' AFTER section_label;

ALTER TABLE permissions
  ADD COLUMN resource_label VARCHAR(128) NULL AFTER resource_key;

ALTER TABLE permissions
  ADD COLUMN action_key VARCHAR(32) NOT NULL DEFAULT 'view'
    COMMENT 'view|create|update|delete|manage'
    AFTER resource_label;

ALTER TABLE permissions
  ADD COLUMN sort_order INT NOT NULL DEFAULT 0 AFTER action_key;

-- Backfill from existing catalog (adjust labels as you like)
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

-- ---------- roles: tenant scope ----------
ALTER TABLE roles
  ADD COLUMN organization_id INT NOT NULL DEFAULT 0
    COMMENT '0 = platform template roles visible to all tenants'
    AFTER name;

ALTER TABLE roles
  ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0
    COMMENT '1 = built-in; cannot delete'
    AFTER organization_id;

-- Built-in roles only become non-deletable platform templates (adjust list to match your roles table).
UPDATE roles SET organization_id = 0, is_system = 1
WHERE UPPER(code) IN (
  'ADMIN', 'OPS', 'FRONT_DESK', 'OPERATIONS', 'SUPERVISOR', 'PAYROLL_ADMIN', 'FINANCE'
);

-- Drop single-column UNIQUE on `code` if this fails with "Can't DROP ...", run:
--   SHOW INDEX FROM roles;
-- and replace `code` below with the correct UNIQUE key name (e.g. roles_code_unique).
ALTER TABLE roles DROP INDEX code;

ALTER TABLE roles
  ADD UNIQUE KEY uq_roles_org_code (organization_id, code);

SELECT 'permissions_hierarchy_custom_roles_v1 applied.' AS note;
