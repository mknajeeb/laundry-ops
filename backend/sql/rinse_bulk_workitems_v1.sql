-- WF Bulk Workitem maintenance + bag assignments (price snapshots).
-- Historical unit prices are immutable once written to bag lines.

CREATE TABLE IF NOT EXISTS rinse_bulk_workitems (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  current_unit_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  active TINYINT(1) NOT NULL DEFAULT 1,
  display_order INT NOT NULL DEFAULT 100,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_by_user_id INT NULL,
  created_by_display_name VARCHAR(255) NULL,
  updated_by_user_id INT NULL,
  updated_by_display_name VARCHAR(255) NULL,
  UNIQUE KEY uq_bulk_workitem_org_name (organization_id, name),
  KEY idx_bulk_workitem_org_active (organization_id, active, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitems (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  workitem_id BIGINT NULL,
  workitem_name_snapshot VARCHAR(255) NOT NULL,
  unit_price_snapshot DECIMAL(10,2) NOT NULL,
  quantity INT NOT NULL DEFAULT 0,
  line_total DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  entered_by_user_id INT NULL,
  entered_by_display_name VARCHAR(255) NULL,
  entered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_by_user_id INT NULL,
  updated_by_display_name VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_bag_bulk_org_date_bag (organization_id, shift_date_et, bag_id),
  KEY idx_bag_bulk_workitem (organization_id, workitem_id),
  KEY idx_bag_bulk_bag (organization_id, bag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Resolution clears WF_BULK_WORKITEM_REVIEW only (items saved OR no-chargeable).
CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitem_resolutions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  resolution_type VARCHAR(32) NOT NULL,
  no_charge_reason VARCHAR(512) NULL,
  items_total DECIMAL(12,2) NULL,
  resolved_by_user_id INT NULL,
  resolved_by_display_name VARCHAR(255) NULL,
  resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_bag_bulk_resolution (organization_id, shift_date_et, bag_id),
  KEY idx_bag_bulk_resolution_date (organization_id, shift_date_et, resolution_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_bag_bulk_workitem_audits (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  previous_items_json LONGTEXT NULL,
  new_items_json LONGTEXT NULL,
  previous_total DECIMAL(12,2) NULL,
  new_total DECIMAL(12,2) NULL,
  previous_resolution_type VARCHAR(32) NULL,
  new_resolution_type VARCHAR(32) NULL,
  reason TEXT NULL,
  actor_user_id INT NULL,
  actor_display_name VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_bag_bulk_audit_bag (organization_id, shift_date_et, bag_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
