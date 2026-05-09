-- =============================================================================
-- Washpro: grant tenant ADMIN + PLATFORM_ADMIN + SUPER_ADMIN to veeadmin (VeeWash)
-- =============================================================================
-- Run after the user row exists (organization_id = veewash org).
-- Uses platform template roles (roles.organization_id = 0). Idempotent (INSERT IGNORE).
--
-- Select your DB in Workbench, or uncomment:
-- USE laundryapp;
-- =============================================================================

SET NAMES utf8mb4;

-- -----------------------------------------------------------------------------
-- Target: change these if you use a different login or tenant slug
-- -----------------------------------------------------------------------------
SET @org_slug = 'veewash';
SET @username = 'veeadmin';

-- -----------------------------------------------------------------------------
-- 1) Resolve Washpro user id (must be exactly one row)
-- -----------------------------------------------------------------------------
SELECT u.id,
       u.username,
       u.organization_id,
       o.slug,
       o.display_name AS org_display_name
FROM users u
JOIN organizations o ON o.id = u.organization_id
WHERE o.slug = @org_slug
  AND u.username = @username;

SELECT u.id INTO @user_id
FROM users u
JOIN organizations o ON o.id = u.organization_id
WHERE o.slug = @org_slug
  AND u.username = @username
LIMIT 1;

-- -----------------------------------------------------------------------------
-- 2) Ensure platform template roles exist (safe to re-run)
-- -----------------------------------------------------------------------------
-- If your roles table has no organization_id / is_system, use the legacy block
-- at the bottom of this file instead (and comment this section out).

INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('ADMIN', 'Administrator', 0, 1);

INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('PLATFORM_ADMIN', 'Platform administrator', 0, 1);

INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('SUPER_ADMIN', 'Super administrator', 0, 1);

-- -----------------------------------------------------------------------------
-- 3) Attach all three roles to the user (skips pairs already present)
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT @user_id, r.id
FROM roles r
WHERE @user_id IS NOT NULL
  AND UPPER(TRIM(r.code)) IN ('ADMIN', 'PLATFORM_ADMIN', 'SUPER_ADMIN')
  AND (r.organization_id = 0 OR r.organization_id IS NULL);

-- -----------------------------------------------------------------------------
-- 4) Verify
-- -----------------------------------------------------------------------------
SELECT IF(
         @user_id IS NULL,
         'ERROR: user not found — check @org_slug and @username',
         CONCAT('OK: linked roles for users.id=', @user_id)
       ) AS status;

SELECT r.code,
       r.name,
       r.organization_id AS role_org_id
FROM user_roles ur
JOIN roles r ON r.id = ur.role_id
WHERE ur.user_id = @user_id
ORDER BY r.code;

-- =============================================================================
-- LEGACY (only if INSERT INTO roles above fails: unknown organization_id)
-- =============================================================================
-- INSERT IGNORE INTO roles (code, name) VALUES ('ADMIN', 'Administrator');
-- INSERT IGNORE INTO roles (code, name) VALUES ('PLATFORM_ADMIN', 'Platform administrator');
-- INSERT IGNORE INTO roles (code, name) VALUES ('SUPER_ADMIN', 'Super administrator');
--
-- INSERT IGNORE INTO user_roles (user_id, role_id)
-- SELECT @user_id, r.id
-- FROM roles r
-- WHERE @user_id IS NOT NULL
--   AND UPPER(TRIM(r.code)) IN ('ADMIN', 'PLATFORM_ADMIN', 'SUPER_ADMIN');
