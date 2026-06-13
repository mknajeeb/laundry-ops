-- Immutable per-run presence scrape snapshots (audit + day-wise At Vendor baselines).
CREATE TABLE IF NOT EXISTS rinse_cleaner_ticket_presence_run_rows (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  presence_run_id BIGINT NOT NULL,
  organization_id INT NOT NULL,
  source_batch_id VARCHAR(64) NOT NULL,
  portal_status VARCHAR(32) NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  customer_name VARCHAR(255) NULL,
  estimated_delivery_date DATE NULL,
  rush_flag VARCHAR(32) NULL,
  service_type VARCHAR(64) NULL,
  raw_row_json JSON NULL,
  rinse_vendor VARCHAR(32) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_presence_run_row (presence_run_id, bag_id),
  KEY idx_presence_run_rows_run (presence_run_id),
  KEY idx_presence_run_rows_org_run (organization_id, presence_run_id),
  KEY idx_presence_run_rows_org_batch (organization_id, source_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
