-- Run in Workbench if Payroll / Attendance pages say "no access" but you are Washpro ADMIN/OPS.
-- Problem: TA API checks permissions (ta.monitor, ta.settings, …), not only the Washpro role name.
-- This links your existing `roles` rows to the `permissions` rows (requires ta_washpro_bridge.sql run first).

USE laundryapp;

-- ADMIN gets every TA permission
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) = 'ADMIN';

-- OPS + FRONT_DESK: clock + monitor + view users
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) IN ('OPS', 'FRONT_DESK')
  AND p.perm_key IN ('ta.clock', 'ta.monitor', 'users.view');

-- MAINTENANCE: optional minimal access
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE UPPER(r.code) = 'MAINTENANCE'
  AND p.perm_key IN ('ta.clock', 'users.view');
