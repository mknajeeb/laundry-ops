-- Phase 5B.1 / 5B.2 — Employee Mobile PIN Access
-- Organization-scoped per-employee module grants for the PIN launcher.
-- Independent of org pin_menu flags, Phase 5C work assignments, and weekday assignments.
--
-- Rollout (Phase 5B.2):
--   employee_mobile_pin_access_backfill marks each organization explicitly.
--   init_mode = legacy_grant  → controlled operator backfill (all-true for eligible PIN staff)
--   init_mode = new_org       → org-create hook (zero grants; new employees get all-false)
--   Request paths never auto-backfill. Unmarked orgs keep missing-row → allow-all
--   until an operator migrates them or a new-org marker is written.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS employee_mobile_pin_access (
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  allow_clock TINYINT(1) NOT NULL DEFAULT 0,
  allow_switch_role TINYINT(1) NOT NULL DEFAULT 0,
  allow_checklist TINYINT(1) NOT NULL DEFAULT 0,
  allow_inventory TINYINT(1) NOT NULL DEFAULT 0,
  allow_revenue_cost TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (organization_id, user_id),
  INDEX idx_empa_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS employee_mobile_pin_access_backfill (
  organization_id INT NOT NULL PRIMARY KEY,
  backfilled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  employees_granted INT NOT NULL DEFAULT 0,
  init_mode VARCHAR(32) NOT NULL DEFAULT 'legacy_grant'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Existing DBs created before init_mode:
SET @db = DATABASE();
SET @has := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'employee_mobile_pin_access_backfill'
    AND COLUMN_NAME = 'init_mode'
);
SET @sql := IF(
  @has = 0,
  'ALTER TABLE employee_mobile_pin_access_backfill ADD COLUMN init_mode VARCHAR(32) NOT NULL DEFAULT ''legacy_grant''',
  'SELECT ''skip init_mode'' AS _note'
);
PREPARE _m FROM @sql; EXECUTE _m; DEALLOCATE PREPARE _m;

SELECT 'employee_mobile_pin_access_v1 complete.' AS note;
