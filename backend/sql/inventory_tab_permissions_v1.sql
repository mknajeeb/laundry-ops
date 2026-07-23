-- Inventory tab-level permissions (idempotent).
-- route_key = inventory, section_key = dashboard|check|orders|reports|settings.
-- Keep legacy inventory.view / create / update / delete as module-level access.

SET NAMES utf8mb4;

INSERT IGNORE INTO permissions (perm_key, description) VALUES
('inventory.dashboard.view', 'View Inventory Dashboard tab'),
('inventory.check.view', 'View Inventory Stock Check tab'),
('inventory.check.create', 'Submit / save stock checks'),
('inventory.orders.view', 'View Inventory Purchase Orders tab'),
('inventory.orders.create', 'Create purchase orders'),
('inventory.orders.update', 'Edit / receive purchase orders'),
('inventory.reports.view', 'View Inventory Reports tab'),
('inventory.settings.view', 'View Inventory Settings tab'),
('inventory.settings.manage', 'Manage inventory items, categories, vendors, and settings');

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'dashboard', section_label = 'Dashboard',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1501
WHERE perm_key = 'inventory.dashboard.view';

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'check', section_label = 'Stock Check',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1511
WHERE perm_key = 'inventory.check.view';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'check', section_label = 'Stock Check',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1512
WHERE perm_key = 'inventory.check.create';

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'orders', section_label = 'Purchase Orders',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1521
WHERE perm_key = 'inventory.orders.view';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'orders', section_label = 'Purchase Orders',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1522
WHERE perm_key = 'inventory.orders.create';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'orders', section_label = 'Purchase Orders',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1523
WHERE perm_key = 'inventory.orders.update';

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'reports', section_label = 'Reports',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1531
WHERE perm_key = 'inventory.reports.view';

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'settings', section_label = 'Settings',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1541
WHERE perm_key = 'inventory.settings.view';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'settings', section_label = 'Settings',
  resource_key = '', resource_label = '', action_key = 'manage', sort_order = 1542
WHERE perm_key = 'inventory.settings.manage';

-- Keep legacy module keys labeled under Module access
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1500
WHERE perm_key = 'inventory.view';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1502
WHERE perm_key = 'inventory.create';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1503
WHERE perm_key = 'inventory.update';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1504
WHERE perm_key = 'inventory.delete';

-- Full-access roles
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('ADMIN', 'SUPER_ADMIN', 'PLATFORM_ADMIN')
  AND p.perm_key IN (
    'inventory.dashboard.view',
    'inventory.check.view',
    'inventory.check.create',
    'inventory.orders.view',
    'inventory.orders.create',
    'inventory.orders.update',
    'inventory.reports.view',
    'inventory.settings.view',
    'inventory.settings.manage'
  );

-- OPS / supervisor: everything except settings manage (view settings optional — exclude for now)
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('OPS')
  AND p.perm_key IN (
    'inventory.dashboard.view',
    'inventory.check.view',
    'inventory.check.create',
    'inventory.orders.view',
    'inventory.orders.create',
    'inventory.orders.update',
    'inventory.reports.view'
  );

-- Floor / front desk: dashboard + stock check
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('FRONT_DESK')
  AND p.perm_key IN (
    'inventory.dashboard.view',
    'inventory.check.view',
    'inventory.check.create'
  );

SELECT 'inventory_tab_permissions_v1 complete.' AS note;
