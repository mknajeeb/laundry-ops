-- Management Revenue obligations / dispositions + account schedules (additive).
-- Runtime ensure also creates/alters these.

CREATE TABLE IF NOT EXISTS mgmt_revenue_account_schedules (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id BIGINT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  pickup_weekdays JSON NULL COMMENT 'ISO weekdays Mon=0 .. Sun=6',
  delivery_weekdays JSON NULL,
  created_by INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mgmt_rev_sched_acct (account_id, effective_from),
  INDEX idx_mgmt_rev_sched_active (account_id, effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mgmt_revenue_dispositions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  source_key VARCHAR(64) NOT NULL COMMENT 'self_service|drop_off|rinse_wf|rinse_hd|dhs:{account_id}',
  account_id BIGINT NULL,
  processing_date_et DATE NULL,
  scheduled_pickup_date DATE NULL,
  scheduled_delivery_date DATE NULL,
  disposition VARCHAR(32) NOT NULL COMMENT 'no_activity|excluded|no_pickup|rescheduled',
  reason VARCHAR(255) NULL,
  new_pickup_date DATE NULL,
  metadata_json JSON NULL,
  entered_by_user_id INT NULL,
  entered_by_name_snapshot VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reversed_at TIMESTAMP NULL,
  reversed_by_user_id INT NULL,
  reversed_by_name_snapshot VARCHAR(255) NULL,
  INDEX idx_mgmt_rev_disp_org_src (organization_id, source_key, processing_date_et),
  INDEX idx_mgmt_rev_disp_pickup (organization_id, account_id, scheduled_pickup_date),
  INDEX idx_mgmt_rev_disp_active (organization_id, reversed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
