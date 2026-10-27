-- Cleaning / operational task activity (PIN execution + supervisor approval).
-- Assignments remain in planned_weekly_schedule_responsibilities.
-- One activity row per employee membership. Shared assignment_group_id is denormalized.

CREATE TABLE IF NOT EXISTS cleaning_task_activities (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  responsibility_id INT NOT NULL,
  assignment_group_id VARCHAR(36) NULL,
  user_id INT NOT NULL,
  shift_session_id INT NULL,
  business_date DATE NOT NULL,
  role VARCHAR(64) NOT NULL,
  timing_mode VARCHAR(20) NOT NULL DEFAULT 'anytime',
  planned_start_time TIME NULL,
  status VARCHAR(32) NOT NULL,
  started_at DATETIME NOT NULL,
  ended_at DATETIME NULL,
  duration_seconds INT NULL,
  paused_category_id INT NULL,
  paused_role_id INT NULL,
  approved_by_user_id INT NULL,
  approved_at DATETIME NULL,
  rejection_reason VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_cta_org_date (organization_id, business_date),
  INDEX idx_cta_org_user_date (organization_id, user_id, business_date),
  INDEX idx_cta_org_status (organization_id, status),
  INDEX idx_cta_resp (responsibility_id),
  INDEX idx_cta_open_user (organization_id, user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cleaning_task_activity_events (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  activity_id BIGINT NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  actor_user_id INT NULL,
  payload_json TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ctae_activity (activity_id),
  INDEX idx_ctae_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'cleaning_task_activity_v1 complete.' AS note;
