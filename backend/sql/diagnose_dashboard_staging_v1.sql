-- Find which orders_staging rows the Operations Dashboard is counting (same table, same idea as GET /dashboard).
-- Run this FIRST when counts do not match what you expect after cleanup.
--
-- 1) Set @organization_id to YOUR tenant (see query A — do not assume 1).
-- 2) Run query B — these rows are what drive "All orders" / WF / HD on the dashboard.

SET NAMES utf8mb4;

-- A) Pick the correct organization_id (tenant)
SELECT id AS organization_id, slug, display_name, active
FROM organizations
ORDER BY id;

-- <<< SET THIS after you find your tenant from query A
SET @organization_id := 1;

-- B) Rows that count as "active at Washpro" (typical schema: both logistics_status and legacy status)
SELECT
  o.id,
  o.name_clean,
  o.service_type,
  o.date_clean,
  o.batch_date,
  o.status,
  o.logistics_status,
  o.processing_status,
  COALESCE(
    o.logistics_status,
    CASE
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) IN ('FORCED_CHECKOUT', 'FORCE_CHECKOUT') THEN 'FORCE_CHECKOUT'
      ELSE 'AT_WASHPRO'
    END
  ) AS eff_logistics
FROM orders_staging o
WHERE o.organization_id = @organization_id
  AND COALESCE(
    o.logistics_status,
    CASE
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) IN ('FORCED_CHECKOUT', 'FORCE_CHECKOUT') THEN 'FORCE_CHECKOUT'
      ELSE 'AT_WASHPRO'
    END
  ) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT')
ORDER BY o.id;

-- C) Quick counts (should match dashboard cards when schema matches above)
SELECT
  COUNT(*) AS total_orders,
  MAX(o.batch_date) AS max_batch_date,
  SUM(o.service_type = 'WF') AS wf_total,
  SUM(o.service_type = 'HD') AS hd_total
FROM orders_staging o
WHERE o.organization_id = @organization_id
  AND COALESCE(
    o.logistics_status,
    CASE
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) = 'CHECKED_OUT' THEN 'SENT_TO_RINSE'
      WHEN UPPER(TRIM(COALESCE(o.status, ''))) IN ('FORCED_CHECKOUT', 'FORCE_CHECKOUT') THEN 'FORCE_CHECKOUT'
      ELSE 'AT_WASHPRO'
    END
  ) NOT IN ('SENT_TO_RINSE', 'FORCE_CHECKOUT', 'CHECKED_OUT');
