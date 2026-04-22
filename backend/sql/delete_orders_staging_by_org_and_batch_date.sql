-- =============================================================================
-- RUN IN MySQL Workbench — removes ALL orders_staging for one org + batch_date
-- (and matching order_processing rows). Use after batches are deleted but rows remain.
--
-- 1) Edit USE database, @organization_id, @batch_date if needed.
-- 2) Run the SELECT only first — confirm these are the rows you want gone.
-- 3) Run the full script (SELECT + DELETEs).
-- =============================================================================

USE laundryapp;

SET @organization_id := 1;
SET @batch_date := '2026-04-16';

-- Preview (same scope as DELETE)
SELECT id, name_clean, date_clean, batch_date, status, logistics_status, organization_id
FROM orders_staging
WHERE organization_id = @organization_id
  AND batch_date = @batch_date
ORDER BY id;

-- Deletes (run after preview looks correct)
DELETE op
FROM order_processing op
INNER JOIN orders_staging o ON o.id = op.order_id
WHERE o.organization_id = @organization_id
  AND o.batch_date = @batch_date;

DELETE FROM orders_staging
WHERE organization_id = @organization_id
  AND batch_date = @batch_date;
