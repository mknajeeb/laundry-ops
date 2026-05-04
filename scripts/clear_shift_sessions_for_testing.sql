-- =============================================================================
-- TEST / DEV ONLY — Clear time-clock (shift) history for a user or organization
-- =============================================================================
-- Use to reset clock-in / clock-out / breaks so you can re-test "first clock-in
-- of the day" (Eastern) and personal laundry bag prompts.
--
-- shift_breaks: CASCADE when parent shift_sessions row is deleted (typical).
-- shift_exceptions, payroll_adjustments: shift_session_id becomes NULL (SET NULL).
--
-- SET VARIABLES, REVIEW, THEN UNCOMMENT THE DELETE AND RUN.
-- =============================================================================

-- @org_id  = organizations.id (tenant) — required if shift_sessions has organization_id
-- @user_id = payroll subject id on shift_sessions — usually Washpro `users.id` after
--            payroll unification; legacy DBs may still use `ta_users.id` (see
--            scripts/delete_shift_sessions_for_user_testing.sql).

SET @org_id  = 1;     -- <<< change
SET @user_id = NULL;  -- <<< users.id (Washpro) or ta_users.id per your schema

-- Optional: preview what would be removed
-- SELECT id, user_id, status, clock_in_at, clock_out_at, personal_laundry_bags
-- FROM shift_sessions
-- WHERE organization_id = @org_id
--   AND (@user_id IS NULL OR user_id = @user_id)
-- ORDER BY id DESC
-- LIMIT 50;

-- START TRANSACTION;

-- If your MySQL build does not CASCADE delete children, run this first:
-- DELETE sb FROM shift_breaks sb
-- INNER JOIN shift_sessions ss ON ss.id = sb.shift_session_id
-- WHERE ss.organization_id = @org_id AND (@user_id IS NULL OR ss.user_id = @user_id);

-- DELETE FROM shift_sessions
-- WHERE organization_id = @org_id
--   AND (@user_id IS NULL OR user_id = @user_id);

-- COMMIT;

-- =============================================================================
-- Nuclear option (entire table — ALL TENANTS): DO NOT USE IN PRODUCTION
-- =============================================================================
-- TRUNCATE TABLE shift_breaks;
-- TRUNCATE TABLE shift_sessions;
