-- =============================================================================
-- Washpro: remove ALL login sessions for a user (auth_sessions)
-- =============================================================================
-- Effect: Every device/browser using an old token must sign in again.
-- Table:   auth_sessions (see backend/sql/maintenance_inventory_auth.sql)
--
-- This is NOT shift/time-clock history. For shift_sessions, see:
--   scripts/clear_shift_sessions_for_testing.sql
-- =============================================================================
-- Select your DB in Workbench, or uncomment:
-- USE laundryapp;

-- -----------------------------------------------------------------------------
-- 1) Find the Washpro user (by name — adjust the pattern if needed)
-- -----------------------------------------------------------------------------
SELECT id,
       username,
       display_name,
       active
FROM users
WHERE LOWER(COALESCE(display_name, '')) LIKE '%noemi%'
   OR LOWER(username) LIKE '%noemi%';

-- If multiple rows appear, pick the correct id and set it below.
-- If you already know the numeric user id, skip the SELECT and set @user_id only.

-- -----------------------------------------------------------------------------
-- 2) Set target user id (REQUIRED)
-- -----------------------------------------------------------------------------
SET @user_id = NULL;  -- <<< replace NULL with the users.id from step 1, e.g. 42

-- -----------------------------------------------------------------------------
-- 3) Preview sessions that will be removed
-- -----------------------------------------------------------------------------
SELECT id,
       user_id,
       token,
       created_at,
       expires_at,
       revoked,
       last_seen_at
FROM auth_sessions
WHERE user_id = @user_id
ORDER BY id DESC;

-- -----------------------------------------------------------------------------
-- 4) Delete all Washpro sessions for that user
-- -----------------------------------------------------------------------------
-- START TRANSACTION;
-- DELETE FROM auth_sessions WHERE user_id = @user_id;
-- COMMIT;

-- Optional: soft-revoke instead of delete (app honors revoked; verify your backend)
-- START TRANSACTION;
-- UPDATE auth_sessions SET revoked = TRUE WHERE user_id = @user_id;
-- COMMIT;
