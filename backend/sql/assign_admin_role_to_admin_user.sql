-- Run in MySQL Workbench against `laundryapp`.
-- Assigns Washpro RBAC role ADMIN to the login user with username `admin`.

USE laundryapp;

-- 1) Ensure ADMIN role row exists (skip if you already have it)
INSERT IGNORE INTO roles (code, name) VALUES ('ADMIN', 'Administrator');

-- 2) Link user `admin` → ADMIN role (composite PK avoids duplicates)
INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id, r.id
FROM users u
CROSS JOIN roles r
WHERE u.username = 'admin'
  AND UPPER(r.code) = 'ADMIN'
LIMIT 1;

-- 3) Verify (optional — run and check the result grid)
-- SELECT u.id, u.username, u.display_name, r.code AS role_code
-- FROM users u
-- JOIN user_roles ur ON ur.user_id = u.id
-- JOIN roles r ON r.id = ur.role_id
-- WHERE u.username = 'admin';
