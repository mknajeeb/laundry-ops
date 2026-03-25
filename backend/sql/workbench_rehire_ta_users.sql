-- ============================================================
-- MySQL Workbench: run this ONCE against your app database
--
-- 1) Connect to Azure MySQL in Workbench (same host/user as your app).
-- 2) Change USE ... below if needed. Default here is laundryapp (matches backend/db.py).
-- 3) Select all → click the lightning bolt (Execute).
--
-- If you see "Duplicate column name" / "Duplicate key name", the migration
-- was already applied — you can stop.
--
-- Requires table `ta_users` to exist (from ta_washpro_bridge.sql or similar).
-- ============================================================

-- Must be utf8mb4 (not "utf8mb8" — that will error).
SET NAMES utf8mb4;

USE laundryapp;

ALTER TABLE ta_users
  ADD COLUMN rehire_parent_id INT NULL COMMENT 'Prior ta_users.id when this row is a rehire' AFTER rehired,
  ADD COLUMN prior_employee_id VARCHAR(64) NULL COMMENT 'Snapshot of old employee_id for audit' AFTER rehire_parent_id;

ALTER TABLE ta_users
  ADD CONSTRAINT fk_ta_users_rehire_parent
  FOREIGN KEY (rehire_parent_id) REFERENCES ta_users(id) ON DELETE SET NULL;

CREATE INDEX idx_ta_users_rehire_parent ON ta_users (rehire_parent_id);
