-- Optional one-time repair: auto-linked TA rows used legacy role code OPERATIONS (no row in your `roles` table).
-- Symptoms: 403 / empty permissions / "Load failed" on TA pages for Washpro OPS/FRONT_DESK users.
-- Safe to run once; backup first.

UPDATE ta_users tu
JOIN roles r_bad ON r_bad.id = tu.role_id AND UPPER(r_bad.code) IN ('OPERATIONS')
SET tu.role_id = (SELECT id FROM roles WHERE UPPER(code) = 'OPS' LIMIT 1)
WHERE tu.washpro_user_id IS NOT NULL;
