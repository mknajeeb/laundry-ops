-- Canonical Rinse WF service-cycle lifecycle (durable; survives midnight).
-- day_bags remain a compatibility projection only.

CREATE TABLE IF NOT EXISTS rinse_wf_service_cycles (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  ticket_uid VARCHAR(64) NOT NULL,
  cycle_anchor_at DATETIME NOT NULL,
  admitted_at DATETIME NOT NULL,
  admitted_source VARCHAR(64) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
  completed_at DATETIME NULL,
  completion_source VARCHAR(64) NULL,
  rush_status VARCHAR(32) NULL,
  estimated_delivery_date DATE NULL,
  pre_weight_lbs DECIMAL(10,4) NULL,
  post_weight_lbs DECIMAL(10,4) NULL,
  review_reason VARCHAR(255) NULL,
  review_resolved_at DATETIME NULL,
  review_resolution_note TEXT NULL,
  review_resolved_by VARCHAR(255) NULL,
  portal_last_seen_at DATETIME NULL,
  disappeared_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wf_service_cycle (organization_id, bag_id, cycle_anchor_at),
  KEY idx_wf_cycle_org_status (organization_id, status),
  KEY idx_wf_cycle_admitted (organization_id, admitted_at),
  KEY idx_wf_cycle_completed (organization_id, completed_at),
  KEY idx_wf_cycle_bag_active (organization_id, bag_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
