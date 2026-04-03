-- Tenant app modules → permission catalog (aligns with TENANT_MODULE_KEYS / tenant_entitlements).
-- Run after permissions_hierarchy_custom_roles_v1.sql so `permissions.route_key`, etc. exist.
-- Idempotent: INSERT IGNORE + UPDATE by perm_key.
--
-- Note: New keys are stored for role packages and future route checks. Most laundry APIs still
-- use Washpro ADMIN today; assigning these on platform roles prepares granular enforcement later.
--
-- Tenant entitlement key `people` matches sidebar "People" and is covered here by module
-- `access` / User accounts (users.*), not a separate route_key.

SET NAMES utf8mb4;

-- ---------- Seed rows (perm_key + description only; safe if hierarchy columns missing) ----------
INSERT IGNORE INTO permissions (perm_key, description) VALUES
('home.view', 'Open Home area'),
('dashboard.view', 'View dashboard'),
('dashboard.update', 'Edit dashboard layout / widgets'),
('orders.view', 'View orders'),
('orders.create', 'Create orders'),
('orders.update', 'Edit orders'),
('orders.delete', 'Cancel / delete orders'),
('checkout.view', 'Open checkout'),
('checkout.create', 'Start checkout sessions'),
('checkout.update', 'Edit checkout'),
('checkout.delete', 'Void checkout'),
('upload.view', 'View upload & staging'),
('upload.create', 'Upload batches / files'),
('upload.delete', 'Remove uploads'),
('discrepancies.view', 'View discrepancies'),
('discrepancies.update', 'Resolve discrepancies'),
('discrepancies.delete', 'Delete discrepancy records'),
('inventory.view', 'View inventory'),
('inventory.create', 'Add inventory'),
('inventory.update', 'Edit inventory'),
('inventory.delete', 'Remove inventory'),
('clock.view', 'Show clock / attendance entry (UI); pair with TA clock API permission where needed'),
('issues.view', 'View issues'),
('issues.create', 'Create issues'),
('issues.update', 'Edit issues'),
('issues.delete', 'Delete issues'),
('production.view', 'View production'),
('production.update', 'Edit production'),
('production.delete', 'Delete production records'),
('scoreboard.view', 'View scoreboard'),
('maintenance.view', 'View maintenance'),
('maintenance.create', 'Create maintenance items'),
('maintenance.update', 'Edit maintenance'),
('maintenance.delete', 'Delete maintenance'),
('payroll.view', 'Open payroll management workspace'),
('payroll.update', 'Edit payroll management data'),
('organization.view', 'View organization profile & settings'),
('organization.update', 'Edit organization profile & settings'),
('permissions.view', 'View TA permissions by role'),
('permissions.update', 'Edit roles and permission bundles');

-- ---------- Hierarchy columns (requires permissions_hierarchy_custom_roles_v1.sql) ----------
UPDATE permissions SET
  route_key = 'home', route_label = 'Home', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1000
WHERE perm_key = 'home.view';

UPDATE permissions SET
  route_key = 'dashboard', route_label = 'Dashboard', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1010
WHERE perm_key = 'dashboard.view';
UPDATE permissions SET
  route_key = 'dashboard', route_label = 'Dashboard', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1020
WHERE perm_key = 'dashboard.update';

UPDATE permissions SET
  route_key = 'orders', route_label = 'Orders', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1100
WHERE perm_key = 'orders.view';
UPDATE permissions SET
  route_key = 'orders', route_label = 'Orders', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1110
WHERE perm_key = 'orders.create';
UPDATE permissions SET
  route_key = 'orders', route_label = 'Orders', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1120
WHERE perm_key = 'orders.update';
UPDATE permissions SET
  route_key = 'orders', route_label = 'Orders', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1130
WHERE perm_key = 'orders.delete';

UPDATE permissions SET
  route_key = 'checkout', route_label = 'Checkout', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1200
WHERE perm_key = 'checkout.view';
UPDATE permissions SET
  route_key = 'checkout', route_label = 'Checkout', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1210
WHERE perm_key = 'checkout.create';
UPDATE permissions SET
  route_key = 'checkout', route_label = 'Checkout', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1220
WHERE perm_key = 'checkout.update';
UPDATE permissions SET
  route_key = 'checkout', route_label = 'Checkout', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1230
WHERE perm_key = 'checkout.delete';

UPDATE permissions SET
  route_key = 'upload', route_label = 'Upload', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1300
WHERE perm_key = 'upload.view';
UPDATE permissions SET
  route_key = 'upload', route_label = 'Upload', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1310
WHERE perm_key = 'upload.create';
UPDATE permissions SET
  route_key = 'upload', route_label = 'Upload', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1320
WHERE perm_key = 'upload.delete';

UPDATE permissions SET
  route_key = 'discrepancies', route_label = 'Discrepancies', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1400
WHERE perm_key = 'discrepancies.view';
UPDATE permissions SET
  route_key = 'discrepancies', route_label = 'Discrepancies', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1410
WHERE perm_key = 'discrepancies.update';
UPDATE permissions SET
  route_key = 'discrepancies', route_label = 'Discrepancies', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1420
WHERE perm_key = 'discrepancies.delete';

UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1500
WHERE perm_key = 'inventory.view';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1510
WHERE perm_key = 'inventory.create';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1520
WHERE perm_key = 'inventory.update';
UPDATE permissions SET
  route_key = 'inventory', route_label = 'Inventory', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1530
WHERE perm_key = 'inventory.delete';

UPDATE permissions SET
  route_key = 'clock', route_label = 'Clock', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1600
WHERE perm_key = 'clock.view';

UPDATE permissions SET
  route_key = 'issues', route_label = 'Issues', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1700
WHERE perm_key = 'issues.view';
UPDATE permissions SET
  route_key = 'issues', route_label = 'Issues', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 1710
WHERE perm_key = 'issues.create';
UPDATE permissions SET
  route_key = 'issues', route_label = 'Issues', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1720
WHERE perm_key = 'issues.update';
UPDATE permissions SET
  route_key = 'issues', route_label = 'Issues', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1730
WHERE perm_key = 'issues.delete';

UPDATE permissions SET
  route_key = 'production', route_label = 'Production', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1800
WHERE perm_key = 'production.view';
UPDATE permissions SET
  route_key = 'production', route_label = 'Production', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1810
WHERE perm_key = 'production.update';
UPDATE permissions SET
  route_key = 'production', route_label = 'Production', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1820
WHERE perm_key = 'production.delete';

UPDATE permissions SET
  route_key = 'scoreboard', route_label = 'Scoreboard', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1900
WHERE perm_key = 'scoreboard.view';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 2000
WHERE perm_key = 'maintenance.view';
UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'create', sort_order = 2010
WHERE perm_key = 'maintenance.create';
UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 2020
WHERE perm_key = 'maintenance.update';
UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 2030
WHERE perm_key = 'maintenance.delete';

UPDATE permissions SET
  route_key = 'payroll', route_label = 'Payroll', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 2100
WHERE perm_key = 'payroll.view';
UPDATE permissions SET
  route_key = 'payroll', route_label = 'Payroll', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 2110
WHERE perm_key = 'payroll.update';

UPDATE permissions SET
  route_key = 'organization', route_label = 'Organization', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 2200
WHERE perm_key = 'organization.view';
UPDATE permissions SET
  route_key = 'organization', route_label = 'Organization', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 2210
WHERE perm_key = 'organization.update';

UPDATE permissions SET
  route_key = 'permissions', route_label = 'TA permissions', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 2300
WHERE perm_key = 'permissions.view';
UPDATE permissions SET
  route_key = 'permissions', route_label = 'TA permissions', section_key = 'main', section_label = 'Module access',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 2310
WHERE perm_key = 'permissions.update';

-- ---------- Grant new catalog to full-access template roles (if present) ----------
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('ADMIN', 'SUPER_ADMIN', 'PLATFORM_ADMIN')
  AND p.perm_key REGEXP '^(home|dashboard|orders|checkout|upload|discrepancies|inventory|clock|issues|production|scoreboard|maintenance|payroll|organization|permissions)\\.[a-z]+';

SELECT 'tenant_modules_permissions_catalog_v1 complete.' AS note;
