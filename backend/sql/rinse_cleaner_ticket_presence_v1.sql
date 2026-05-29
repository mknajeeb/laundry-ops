-- Portal ticket presence (ready_for_vendor / at_vendor) separate from orders_staging active queue.
CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  portal_status VARCHAR(32) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  first_seen_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  source_batch_id VARCHAR(64) NULL,
  customer_name VARCHAR(255) NULL,
  estimated_delivery_date DATE NULL,
  rush_flag VARCHAR(32) NULL,
  service_type VARCHAR(64) NULL,
  raw_row_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_rinse_presence_org_bag (organization_id, bag_id),
  KEY idx_rinse_presence_org_status (organization_id, portal_status, active),
  KEY idx_rinse_presence_org_last_seen (organization_id, last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  portal_status VARCHAR(32) NOT NULL,
  source_batch_id VARCHAR(64) NOT NULL,
  source_url TEXT NULL,
  dry_run TINYINT(1) NOT NULL DEFAULT 0,
  rows_found INT NOT NULL DEFAULT 0,
  rows_inserted INT NOT NULL DEFAULT 0,
  rows_updated INT NOT NULL DEFAULT 0,
  rows_unchanged INT NOT NULL DEFAULT 0,
  rows_missing INT NOT NULL DEFAULT 0,
  errors_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY idx_presence_runs_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
