-- Weekly Schedule assignment audit.
--
-- Provision this table BEFORE deploying application code that records
-- assignment corrections. The application does not create it. If the table
-- is missing, an audited assignment write fails with
-- "assignment audit table is not provisioned" and discards the assignment.
--
-- Idempotent. Production inspection on 2026-11-13 found this table absent
-- and found planned_weekly_schedule_responsibilities.display_order already
-- present. This script does not ALTER that table and does not insert rows.
--
-- Apply with the target database in MYSQL_* / DB_* (the worktree has no .env):
--   python3 scripts/apply_sql_mysql_connector.py backend/sql/weekly_schedule_task_assignment_v1.sql

CREATE TABLE IF NOT EXISTS planned_weekly_schedule_assignment_corrections (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  assignment_group_id VARCHAR(36) NULL,
  responsibility_id INT NULL,
  action VARCHAR(40) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  actor_user_id INT NULL,
  before_json TEXT NULL,
  after_json TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pws_corr_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
