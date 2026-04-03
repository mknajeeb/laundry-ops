-- Idempotent: ensure username `admin` exists for organization slug `washmate`
-- so /login/washmate works. Multitenant login matches (username + organization slug);
-- an `admin` row tied only to org `washpro` (id 1) will NOT authenticate on washmate.
--
-- This copies password_hash from the `admin` user in organization_id = 1 (Washpro).
-- Run in Workbench against your app schema (e.g. laundryapp). Backup first.
--
-- USE laundryapp;

SET NAMES utf8mb4;

INSERT INTO users (organization_id, username, password_hash, display_name, active, created_at, updated_at)
SELECT o.id,
       'admin',
       src.password_hash,
       COALESCE(src.display_name, 'Administrator'),
       1,
       NOW(),
       NOW()
FROM organizations o
INNER JOIN users src ON src.organization_id = 1 AND LOWER(src.username) = 'admin' AND src.active = 1
WHERE LOWER(o.slug) = 'washmate'
  AND o.active = 1
  AND NOT EXISTS (
    SELECT 1 FROM users u2 WHERE u2.organization_id = o.id AND LOWER(u2.username) = 'admin'
  )
LIMIT 1;

-- Assign ADMIN (platform template role organization_id = 0, or legacy row without org column)
INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id,
       (SELECT r.id
        FROM roles r
        WHERE UPPER(r.code) = 'ADMIN'
        ORDER BY (CASE WHEN r.organization_id = 0 OR r.organization_id IS NULL THEN 0 ELSE 1 END),
                 r.id
        LIMIT 1)
FROM users u
JOIN organizations o ON o.id = u.organization_id
WHERE LOWER(o.slug) = 'washmate'
  AND LOWER(u.username) = 'admin';

SELECT 'dev_washmate_admin_v1: ensure admin exists for washmate (password same as org-1 admin).' AS note;
