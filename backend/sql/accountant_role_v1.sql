-- Dedicated read-only ACCOUNTANT role (external payroll accountants).
-- Idempotent. Run after permissions_hierarchy_custom_roles_v1.sql on existing DBs.
-- Grants users.view only — no users.edit, ta.settings, ta.monitor, or finance.payments.

SET NAMES utf8mb4;

INSERT IGNORE INTO permissions (perm_key, description) VALUES
('users.view', 'View users');

INSERT INTO roles (organization_id, code, name, is_system)
SELECT 0, 'ACCOUNTANT', 'Accountant', 1 FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM roles WHERE UPPER(TRIM(code)) = 'ACCOUNTANT'
);

UPDATE roles
SET organization_id = 0, is_system = 1, name = 'Accountant'
WHERE UPPER(TRIM(code)) = 'ACCOUNTANT';

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.perm_key = 'users.view'
WHERE UPPER(TRIM(r.code)) = 'ACCOUNTANT';

-- Strip any elevated permissions if ACCOUNTANT was previously over-assigned
DELETE rp FROM role_permissions rp
INNER JOIN roles r ON r.id = rp.role_id
INNER JOIN permissions p ON p.id = rp.permission_id
WHERE UPPER(TRIM(r.code)) = 'ACCOUNTANT'
  AND p.perm_key <> 'users.view';

SELECT 'accountant_role_v1: ACCOUNTANT role seeded (users.view only).' AS note;
