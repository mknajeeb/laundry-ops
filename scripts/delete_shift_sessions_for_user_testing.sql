-- =============================================================================
-- TEST / DEV — Remove clock-in / clock-out rows (shift_sessions) for one person
-- =============================================================================
-- Use this to re-test "first session of the day" (Eastern) and personal-laundry
-- bag prompts. This is what **Payroll → Live sessions** shows — NOT Washpro
-- login tokens (those are in `auth_sessions`; see delete_washpro_auth_sessions…).
--
-- After payroll unification, `shift_sessions.user_id` = `users.id` (Washpro).
-- If your DB still has `ta_users` and old FKs, use the alternate @uid resolution
-- in the comment block at the bottom.
-- =============================================================================
-- USE laundryapp;   -- if needed

-- -----------------------------------------------------------------------------
-- 1) Find the Washpro user (match your tenant’s username / email)
-- -----------------------------------------------------------------------------
-- Example from UI: noemi.12@washpro.local  /  "Noemi Flores"

SELECT id, username, display_name, active, organization_id
FROM users
WHERE LOWER(username) = 'noemi.12@washpro.local'
   OR LOWER(COALESCE(display_name, '')) LIKE '%noemi%'
ORDER BY id;

-- Set this to the `id` from the row above (Washpro `users.id`).
SET @washpro_user_id = NULL;  -- <<< e.g. 12

-- Optional: limit to one tenant if the same user id should not exist across orgs
-- (usually @washpro_user_id is enough).
SET @org_id = NULL;  -- <<< set to organizations.id, or leave NULL for all orgs for this user

-- -----------------------------------------------------------------------------
-- 2) Preview rows that will be deleted (same as Live sessions list)
-- -----------------------------------------------------------------------------
SELECT ss.id,
       ss.user_id,
       ss.organization_id,
       ss.payroll_cycle_id,
       ss.clock_in_at,
       ss.clock_out_at,
       ss.status,
       u.username,
       u.display_name
FROM shift_sessions ss
INNER JOIN users u ON u.id = ss.user_id
WHERE ss.user_id = @washpro_user_id
  AND (@org_id IS NULL OR ss.organization_id = @org_id)
ORDER BY ss.id DESC;

-- If the query above returns **no rows** but Live sessions still shows data, your
-- `shift_sessions.user_id` may still be `ta_users.id`. Run the preview in the
-- bottom comment block, then use the legacy DELETE there.

-- -----------------------------------------------------------------------------
-- 3) Delete those shift sessions
-- (shift_breaks children usually CASCADE; shift_exceptions / adjustments may SET NULL)
-- -----------------------------------------------------------------------------
-- START TRANSACTION;
-- DELETE FROM shift_sessions
-- WHERE user_id = @washpro_user_id
--   AND (@org_id IS NULL OR organization_id = @org_id);
-- COMMIT;

-- =============================================================================
-- Optional: delete only specific session ids (e.g. 112, 113, 114 from the UI)
-- =============================================================================
-- START TRANSACTION;
-- DELETE FROM shift_sessions
-- WHERE id IN (112, 113, 114);
-- COMMIT;

-- =============================================================================
-- Legacy DB (ta_users still present): resolve clock user id, then delete
-- =============================================================================
-- SET @washpro_user_id = 12;  -- users.id
-- SELECT t.id AS ta_user_id, t.washpro_user_id
-- FROM ta_users t
-- WHERE t.washpro_user_id = @washpro_user_id;
--
-- If shift_sessions.user_id matches ta_users.id:
-- DELETE FROM shift_sessions WHERE user_id = (SELECT id FROM ta_users WHERE washpro_user_id = @washpro_user_id LIMIT 1);
