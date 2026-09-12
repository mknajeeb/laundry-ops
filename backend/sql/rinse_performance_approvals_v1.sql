-- Generic published performance snapshots for Rinse external dashboard.
-- CALCULATED != PUBLISHED: Rinse reads only APPROVED, non-invalidated rows.
CREATE TABLE IF NOT EXISTS rinse_performance_session_approvals (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date_et DATE NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  segment_id INT NULL,
  employee_user_id INT NULL,
  employee_name VARCHAR(255) NOT NULL,
  metric_key VARCHAR(64) NOT NULL,
  metric_unit VARCHAR(32) NOT NULL,
  published_numerator DECIMAL(14,4) NOT NULL,
  published_denominator DECIMAL(14,4) NOT NULL,
  published_metric_value DECIMAL(14,4) NOT NULL,
  published_quantity DECIMAL(14,4) NULL,
  published_duration_hours DECIMAL(14,4) NULL,
  published_session_start_et DATETIME NULL,
  published_session_end_et DATETIME NULL,
  approved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  approved_by INT NULL,
  content_fingerprint VARCHAR(128) NOT NULL,
  invalidated_at DATETIME NULL,
  invalidated_reason VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rinse_perf_appr_org_role_session (organization_id, role_key, session_id),
  KEY idx_rinse_perf_appr_org_role_date (organization_id, role_key, business_date_et),
  KEY idx_rinse_perf_appr_org_emp_date (organization_id, employee_user_id, business_date_et),
  KEY idx_rinse_perf_appr_active (organization_id, role_key, invalidated_at, business_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Append-only approval audit trail.
CREATE TABLE IF NOT EXISTS rinse_performance_approval_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  session_id VARCHAR(64) NOT NULL,
  business_date_et DATE NULL,
  action VARCHAR(32) NOT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  reason VARCHAR(255) NULL,
  snapshot_metric_value DECIMAL(14,4) NULL,
  content_fingerprint VARCHAR(128) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_rinse_perf_ev_org_role_session (organization_id, role_key, session_id),
  KEY idx_rinse_perf_ev_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
