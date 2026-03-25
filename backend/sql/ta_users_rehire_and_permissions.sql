-- Run once on your payroll DB (after backup). Adds rehire linking on ta_users.
-- Safe to re-run if your MySQL supports duplicate-check manually.

SET NAMES utf8mb4;

-- Link to prior TA profile when someone is rehired (new row or updated row).
ALTER TABLE ta_users
  ADD COLUMN rehire_parent_id INT NULL COMMENT 'Prior ta_users.id when this row is a rehire' AFTER rehired,
  ADD COLUMN prior_employee_id VARCHAR(64) NULL COMMENT 'Snapshot of old employee_id for audit' AFTER rehire_parent_id;

ALTER TABLE ta_users
  ADD CONSTRAINT fk_ta_users_rehire_parent
  FOREIGN KEY (rehire_parent_id) REFERENCES ta_users(id) ON DELETE SET NULL;

CREATE INDEX idx_ta_users_rehire_parent ON ta_users (rehire_parent_id);
