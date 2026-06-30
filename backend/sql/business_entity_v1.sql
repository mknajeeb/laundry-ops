-- Business entity column on worker profiles + legacy shift value cleanup (IDEMPOTENT).
-- WashPro / WashMate / VeeWash are separate entities within tenant scheduling.

SET NAMES utf8mb4;

SET @db = DATABASE();

SET @has := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payroll_worker_profiles' AND COLUMN_NAME = 'business_entity'
);
SET @sql := IF(
  @has = 0,
  'ALTER TABLE payroll_worker_profiles ADD COLUMN business_entity VARCHAR(32) NULL DEFAULT NULL AFTER can_work_both',
  'SELECT ''skip payroll_worker_profiles.business_entity'' AS _note'
);
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

-- Backfill worker entity from legacy stream flags + org slug.
UPDATE payroll_worker_profiles pwp
JOIN users u ON u.id = pwp.user_id
JOIN organizations o ON o.id = u.organization_id
SET pwp.business_entity = CASE
  WHEN pwp.can_work_rinse = 0 AND pwp.can_work_drop_off = 0 AND pwp.can_work_both = 0 THEN 'none'
  WHEN pwp.can_work_rinse = 1 AND pwp.can_work_drop_off = 1 AND pwp.can_work_both = 1 THEN 'shared'
  WHEN pwp.can_work_rinse = 1 AND pwp.can_work_drop_off = 0 THEN 'rinse_exclusive'
  WHEN pwp.can_work_drop_off = 1 AND pwp.can_work_rinse = 0 THEN
    CASE
      WHEN LOWER(o.slug) = 'veewash' THEN 'veewash'
      WHEN LOWER(o.slug) = 'washmate' THEN 'washmate'
      ELSE 'washpro'
    END
  ELSE 'washpro'
END
WHERE pwp.business_entity IS NULL OR TRIM(pwp.business_entity) = '';

-- Legacy shift rows stored employer_affiliation=veewash meant WashPro on non-VeeWash orgs.
UPDATE planned_weekly_schedule_entries e
JOIN organizations o ON o.id = e.organization_id
SET e.employer_affiliation = 'washpro'
WHERE LOWER(COALESCE(e.employer_affiliation, '')) = 'veewash'
  AND LOWER(o.slug) <> 'veewash';

SELECT 'business_entity_v1 applied' AS note;
