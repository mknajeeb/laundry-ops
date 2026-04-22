-- =============================================================================
-- MANUAL CLEANUP — orders_staging (+ order_processing)
-- =============================================================================
--
-- WHY YOU STILL SEE 4 ORDERS ON THE DASHBOARD
--   • The dashboard counts rows in orders_staging (GET /dashboard). If DELETE did not run, they stay.
--   • The default script used organization_id = 1. Your real tenant id is often NOT 1 — run
--     diagnose_dashboard_staging_v1.sql and use the correct organizations.id.
--   • The DELETE statements below are inside /* ... */ — MySQL WILL NOT DELETE until you remove
--     those comment markers around the block you want to run.
--
-- STEPS
--   1) Run diagnose_dashboard_staging_v1.sql — confirm @organization_id and which rows appear (B).
--   2) Set @batch_date and @organization_id below.
--   3) Run PREVIEW queries — row count should match what you want gone.
--   4) Uncomment ONE delete block (1 or 2), run it, refresh the app.

SET NAMES utf8mb4;

SET @batch_date := '2026-04-16';   -- YYYY-MM-DD
SET @organization_id := 1;       -- MUST match organizations.id for your store

-- ---------------------------------------------------------------------------
-- PREVIEW 1: rows with this batch_date (normal)
-- ---------------------------------------------------------------------------
SELECT id, name_clean, date_clean, batch_date, logistics_status, status, organization_id
FROM orders_staging
WHERE batch_date = @batch_date
  AND organization_id = @organization_id
ORDER BY id;

-- ---------------------------------------------------------------------------
-- PREVIEW 2: batch_date NULL but date_clean matches (common stuck pattern)
-- ---------------------------------------------------------------------------
SELECT id, name_clean, date_clean, batch_date, logistics_status, status, organization_id
FROM orders_staging
WHERE batch_date IS NULL
  AND date_clean = @batch_date
  AND organization_id = @organization_id
ORDER BY id;

-- ---------------------------------------------------------------------------
-- DELETE 1: remove everything with batch_date = @batch_date for this tenant
-- (Remove the slash-star line below AND the star-slash line after the deletes to execute.)
-- ---------------------------------------------------------------------------
/*
DELETE op FROM order_processing op
INNER JOIN orders_staging o ON o.id = op.order_id
WHERE o.batch_date = @batch_date AND o.organization_id = @organization_id;

DELETE FROM orders_staging
WHERE batch_date = @batch_date AND organization_id = @organization_id;
*/

-- ---------------------------------------------------------------------------
-- DELETE 2: remove NULL batch_date rows for this date_clean + tenant
-- ---------------------------------------------------------------------------
/*
DELETE op FROM order_processing op
INNER JOIN orders_staging o ON o.id = op.order_id
WHERE o.batch_date IS NULL AND o.date_clean = @batch_date AND o.organization_id = @organization_id;

DELETE FROM orders_staging
WHERE batch_date IS NULL AND date_clean = @batch_date AND organization_id = @organization_id;
*/
