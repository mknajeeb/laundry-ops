-- Immutable Rinse order occurrence identity (additive).
-- bag_id remains reusable; order_instance_id is one real service/order occurrence.
-- Seeded from authoritative rinse_wf_service_cycles (cycle_anchor_at).

CREATE TABLE IF NOT EXISTS rinse_order_instances (
  order_instance_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  service_type VARCHAR(10) NOT NULL DEFAULT 'WF',
  cycle_anchor_at DATETIME NOT NULL,
  source_cycle_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME NULL,
  completed_by_user_id INT NULL,
  completed_by_employee_name VARCHAR(255) NULL,
  completion_source VARCHAR(64) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_order_instance_cycle (
    organization_id, bag_id, service_type, cycle_anchor_at
  ),
  UNIQUE KEY uq_order_instance_source_cycle (source_cycle_id),
  KEY idx_order_instance_org_bag (organization_id, bag_id),
  KEY idx_order_instance_org_completed (organization_id, completed_at),
  KEY idx_order_instance_org_anchor (organization_id, cycle_anchor_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
