-- Additive Folding Performance auto-approval metadata and supervisor adjustments.
-- Does not rewrite scans, shift sessions, payroll hours, or historical approvals.
-- Do not apply to production until a separate deploy authorization.
-- Auto-approval stays off until rinse_folding_auto_approve_at_target is set to 1.

ALTER TABLE rinse_performance_session_approvals
  ADD COLUMN approval_source VARCHAR(16) NULL AFTER approved_by,
  ADD COLUMN applied_target_lbs_per_hour DECIMAL(14,4) NULL AFTER approval_source;

CREATE TABLE IF NOT EXISTS rinse_performance_auto_approve_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date_et DATE NOT NULL,
  shift_session_id INT NULL,
  segment_id INT NULL,
  enqueued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at DATETIME NULL,
  UNIQUE KEY uq_perf_auto_q (organization_id, business_date_et, segment_id),
  KEY idx_perf_auto_q_open (organization_id, processed_at, business_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_performance_supervisor_adjustments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date_et DATE NOT NULL,
  adjustment_key VARCHAR(64) NOT NULL,
  employee_user_id INT NOT NULL,
  employee_name VARCHAR(255) NOT NULL,
  target_session_id VARCHAR(64) NULL,
  raw_orders INT NULL,
  raw_lbs DECIMAL(14,4) NULL,
  raw_hours DECIMAL(14,4) NULL,
  raw_lbs_per_hour DECIMAL(14,4) NULL,
  corrected_orders INT NULL,
  corrected_lbs DECIMAL(14,4) NULL,
  corrected_hours DECIMAL(14,4) NULL,
  corrected_lbs_per_hour DECIMAL(14,4) NULL,
  approved_orders INT NULL,
  approved_lbs DECIMAL(14,4) NULL,
  approved_hours DECIMAL(14,4) NULL,
  approved_lbs_per_hour DECIMAL(14,4) NULL,
  reason VARCHAR(255) NOT NULL,
  notes TEXT NULL,
  publication_status VARCHAR(32) NOT NULL DEFAULT 'NEEDS_APPROVAL',
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by INT NULL,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_perf_sup_adj (organization_id, adjustment_key),
  KEY idx_perf_sup_adj_day (organization_id, business_date_et, employee_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_performance_supervisor_adjustment_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  adjustment_key VARCHAR(64) NOT NULL,
  business_date_et DATE NOT NULL,
  action VARCHAR(32) NOT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  reason VARCHAR(255) NULL,
  before_json MEDIUMTEXT NULL,
  after_json MEDIUMTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_perf_sup_adj_ev (organization_id, adjustment_key, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One active credit per processing cycle. released_at IS NULL → active_token '1'.
-- Released rows store NULL and may repeat a cycle_key. Reprocessing uses a new
-- order_instance cycle_key, so a later cycle can be credited again.
CREATE TABLE IF NOT EXISTS rinse_performance_bag_credits (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  order_instance_id BIGINT NULL,
  cycle_key VARCHAR(160) NOT NULL,
  employee_user_id INT NULL,
  employee_name VARCHAR(255) NOT NULL,
  session_id VARCHAR(64) NULL,
  adjustment_key VARCHAR(64) NULL,
  weight_lbs DECIMAL(14,4) NULL,
  released_at DATETIME NULL,
  active_token VARCHAR(8) AS (IF(released_at IS NULL, '1', NULL)) STORED,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_perf_bag_cycle_active (organization_id, cycle_key, active_token),
  KEY idx_perf_bag_credit_day (organization_id, business_date_et, bag_id),
  KEY idx_perf_bag_credit_adj (organization_id, adjustment_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
