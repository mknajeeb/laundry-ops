-- Auditable WF Folder Performance attribution overrides (wrong-scanner correction).
-- Does NOT rewrite rinse_bag_scan_events or day-bag completion scans.
-- Effective credit/session is layered on top of original scanner attribution.
CREATE TABLE IF NOT EXISTS rinse_wf_folder_attribution_overrides (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  selected_date_et DATE NOT NULL,
  original_employee_name VARCHAR(255) NOT NULL,
  original_scanner_name VARCHAR(255) NULL,
  original_completion_et DATETIME NULL,
  effective_employee_name VARCHAR(255) NOT NULL,
  effective_session_id VARCHAR(64) NULL,
  effective_segment_id INT NULL,
  override_status VARCHAR(32) NOT NULL DEFAULT 'active',
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  note VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wf_folder_attr_org_bag_date (organization_id, bag_id, selected_date_et),
  KEY idx_wf_folder_attr_org_date (organization_id, selected_date_et),
  KEY idx_wf_folder_attr_status (organization_id, override_status, selected_date_et),
  KEY idx_wf_folder_attr_effective_emp (organization_id, effective_employee_name, selected_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Append-only audit trail for Move / Reset actions.
CREATE TABLE IF NOT EXISTS rinse_wf_folder_attribution_override_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  selected_date_et DATE NOT NULL,
  action VARCHAR(32) NOT NULL,
  original_employee_name VARCHAR(255) NULL,
  from_employee_name VARCHAR(255) NULL,
  to_employee_name VARCHAR(255) NULL,
  from_session_id VARCHAR(64) NULL,
  to_session_id VARCHAR(64) NULL,
  to_segment_id INT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  note VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_wf_folder_attr_ev_org_date (organization_id, selected_date_et),
  KEY idx_wf_folder_attr_ev_bag (organization_id, bag_id),
  KEY idx_wf_folder_attr_ev_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
