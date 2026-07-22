-- VeeWash Step-1 daily Shift Monitor snapshots + close/reopen audit.
-- Source scan tables are never modified by this schema.

CREATE TABLE IF NOT EXISTS rinse_shift_monitor_days (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
  opened_at DATETIME NULL,
  last_sync_at DATETIME NULL,
  closed_at DATETIME NULL,
  closed_by_user_id INT NULL,
  closed_by_display_name VARCHAR(255) NULL,
  close_reason TEXT NULL,
  close_override TINYINT(1) NOT NULL DEFAULT 0,
  reopen_count INT NOT NULL DEFAULT 0,
  review_required_count INT NOT NULL DEFAULT 0,
  headline_json LONGTEXT NULL,
  workload_meta_json LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_shift_monitor_day (organization_id, shift_date_et),
  KEY idx_shift_monitor_day_status (organization_id, status, shift_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_shift_monitor_day_bags (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  service_type VARCHAR(16) NULL,
  rush_status VARCHAR(32) NULL,
  new_or_carryover VARCHAR(32) NULL,
  workload_entry_type VARCHAR(64) NULL,
  workload_entry_timestamp DATETIME NULL,
  pre_weight_lbs DECIMAL(10,4) NULL,
  post_weight_lbs DECIMAL(10,4) NULL,
  weight_lbs DECIMAL(10,4) NULL,
  canonical_completion_status VARCHAR(64) NULL,
  canonical_completion_timestamp DATETIME NULL,
  canonical_completion_employee VARCHAR(255) NULL,
  effective_status VARCHAR(64) NULL,
  review_reason_codes_json TEXT NULL,
  portal_status_at_sync VARCHAR(64) NULL,
  last_present_scrape DATETIME NULL,
  first_confirmed_absent_scrape DATETIME NULL,
  disposition VARCHAR(64) NULL,
  bag_snapshot_json LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_shift_monitor_day_bag (organization_id, shift_date_et, bag_id),
  KEY idx_shift_monitor_day_bag_status (organization_id, shift_date_et, effective_status),
  KEY idx_shift_monitor_day_bag_svc (organization_id, shift_date_et, service_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_shift_monitor_close_audit (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  action VARCHAR(64) NOT NULL,
  actor_user_id INT NULL,
  actor_display_name VARCHAR(255) NULL,
  reason TEXT NULL,
  previous_status VARCHAR(32) NULL,
  new_status VARCHAR(32) NULL,
  checklist_json LONGTEXT NULL,
  totals_json LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_shift_close_audit_day (organization_id, shift_date_et, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
