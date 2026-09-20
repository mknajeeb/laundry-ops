-- Day-level WF Folder Performance overrides (Average Weight lb/bag).
-- Scope: organization_id + role_key (FOLDER) + business_date_et + employee_key
-- employee_key = u:{user_id} preferred; n:{normalized_name} only if no user_id.
-- End Time edits write shift_job_segments.ended_at (final included session) and audit here.
-- Apply explicitly before deploy when practical (additive CREATE IF NOT EXISTS).
CREATE TABLE IF NOT EXISTS rinse_performance_employee_day_overrides (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  business_date_et DATE NOT NULL,
  employee_key VARCHAR(96) NOT NULL,
  employee_user_id INT NULL,
  employee_name VARCHAR(255) NOT NULL,
  average_weight_lbs DECIMAL(10,4) NULL,
  reason VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by INT NULL,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  updated_by INT NULL,
  UNIQUE KEY uq_rinse_perf_day_ov
    (organization_id, role_key, business_date_et, employee_key),
  KEY idx_rinse_perf_day_ov_emp
    (organization_id, role_key, business_date_et, employee_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_performance_employee_day_override_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  business_date_et DATE NOT NULL,
  employee_key VARCHAR(96) NULL,
  employee_user_id INT NULL,
  employee_name VARCHAR(255) NOT NULL,
  action VARCHAR(32) NOT NULL,
  average_weight_lbs DECIMAL(10,4) NULL,
  end_time_et VARCHAR(64) NULL,
  target_session_id VARCHAR(64) NULL,
  target_segment_id INT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  reason VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_rinse_perf_day_ov_ev
    (organization_id, role_key, business_date_et, employee_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
