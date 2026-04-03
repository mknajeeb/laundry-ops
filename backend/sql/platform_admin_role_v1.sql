-- Platform operator: may list and create organizations (tenants).
-- Run after `roles` exists. Prefer running after permissions_hierarchy_custom_roles_v1.sql
-- so roles carry organization_id / is_system; if that migration is not applied yet,
-- use the legacy INSERT in the comment block instead of the main INSERT.

SET NAMES utf8mb4;

-- Main path: tenant-scoped roles (organization_id column present)
INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('PLATFORM_ADMIN', 'Platform administrator', 0, 1);

INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('SUPER_ADMIN', 'Super administrator', 0, 1);

-- Legacy path (uncomment ONLY if INSERT above fails with "Unknown column 'organization_id'"):
-- INSERT IGNORE INTO roles (code, name)
-- VALUES ('PLATFORM_ADMIN', 'Platform administrator');

-- Assign to your bootstrap account (replace 1 with users.id). Run once.
-- INSERT IGNORE INTO user_roles (user_id, role_id)
-- SELECT 1, id FROM roles WHERE UPPER(code) = 'PLATFORM_ADMIN' AND (organization_id = 0 OR organization_id IS NULL)
-- ORDER BY id DESC LIMIT 1;
