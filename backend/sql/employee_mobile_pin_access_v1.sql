-- Phase 5B.1 / 5B.2 — Employee Mobile PIN Access
-- Organization-scoped per-employee module grants for the PIN launcher.
-- Independent of org pin_menu flags, Phase 5C work assignments, and weekday assignments.
--
-- Rollout (Phase 5B.2):
--   employee_mobile_pin_access_backfill marks each organization explicitly.
--   init_mode = legacy_grant  → controlled operator backfill (all-true for eligible PIN staff)
--   init_mode = new_org       → org-create hook (zero grants, new employees get all-false)
--   Request paths never auto-backfill. Unmarked orgs keep missing-row → allow-all
--   until an operator migrates them or a new-org marker is written.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS employee_mobile_pin_access (
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  allow_clock TINYINT(1) NOT NULL DEFAULT 0,
  allow_switch_role TINYINT(1) NOT NULL DEFAULT 0,
  allow_take_break TINYINT(1) NOT NULL DEFAULT 1,
  allow_checklist TINYINT(1) NOT NULL DEFAULT 0,
  allow_inventory TINYINT(1) NOT NULL DEFAULT 0,
  allow_revenue_cost TINYINT(1) NOT NULL DEFAULT 0,
  allow_team_status TINYINT(1) NOT NULL DEFAULT 0,
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

-- Team Status (manager-only Mobile Ops): default OFF for all existing rows.
SET @has_ts := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'employee_mobile_pin_access'
    AND COLUMN_NAME = 'allow_team_status'
);
SET @sql_ts := IF(
  @has_ts = 0,
  'ALTER TABLE employee_mobile_pin_access ADD COLUMN allow_team_status TINYINT(1) NOT NULL DEFAULT 0 AFTER allow_revenue_cost',
  'SELECT ''skip allow_team_status'' AS _note'
);
PREPARE _ts FROM @sql_ts; EXECUTE _ts; DEALLOCATE PREPARE _ts;

-- Take a Break: default ON so existing floor staff keep break access.
SET @has_tb := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'employee_mobile_pin_access'
    AND COLUMN_NAME = 'allow_take_break'
);
SET @sql_tb := IF(
  @has_tb = 0,
  'ALTER TABLE employee_mobile_pin_access ADD COLUMN allow_take_break TINYINT(1) NOT NULL DEFAULT 1 AFTER allow_switch_role',
  'SELECT ''skip allow_take_break'' AS _note'
);
PREPARE _tb FROM @sql_tb; EXECUTE _tb; DEALLOCATE PREPARE _tb;

CREATE TABLE IF NOT EXISTS employee_mobile_pin_access_migrations (
  organization_id INT NOT NULL,
  migration_key VARCHAR(64) NOT NULL,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (organization_id, migration_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'employee_mobile_pin_access_v1 complete.' AS note;
