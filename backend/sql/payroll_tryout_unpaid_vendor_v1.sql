-- Additive payroll category + vendor seed. Safe to re-run.
-- Does not UPDATE or DELETE existing payroll/payment rows.
-- Runtime also applies EC_TRYOUT via seed_worker_categories_if_missing()
-- and VeeWash via ensure_payment_vendors().

-- Try Out employment category (per organization).
INSERT INTO employment_categories (organization_id, code, name, active)
SELECT o.id, 'EC_TRYOUT', 'Try Out', 1
FROM organizations o
WHERE NOT EXISTS (
  SELECT 1 FROM employment_categories e
  WHERE e.organization_id = o.id AND e.code = 'EC_TRYOUT'
);

-- VeeWash payment vendor (Washmate Inc already seeded as org default).
INSERT INTO payroll_vendors (organization_id, name, active)
SELECT o.id, 'VeeWash', 1
FROM organizations o
WHERE EXISTS (SELECT 1 FROM information_schema.TABLES
              WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'payroll_vendors')
  AND NOT EXISTS (
    SELECT 1 FROM payroll_vendors v
    WHERE v.organization_id = o.id AND v.name = 'VeeWash'
  );
