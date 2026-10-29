-- Weekly Schedule task assignment: card order and audited corrections.
-- Applied automatically on first use. Safe to run once on an existing database.

ALTER TABLE planned_weekly_schedule_responsibilities
  ADD COLUMN display_order INT NOT NULL DEFAULT 0;

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
