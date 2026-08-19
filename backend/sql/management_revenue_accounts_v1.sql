-- Management Revenue Accounts & Pricing (Phase 2)
-- Reference schema; tables are also created idempotently at runtime.

CREATE TABLE IF NOT EXISTS mgmt_revenue_accounts (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  parent_id BIGINT NULL,
  account_code VARCHAR(64) NULL,
  name VARCHAR(255) NOT NULL,
  revenue_group VARCHAR(32) NOT NULL,
  service_type VARCHAR(64) NULL,
  revenue_mode VARCHAR(32) NOT NULL DEFAULT 'calculated',
  active TINYINT(1) NOT NULL DEFAULT 1,
  start_date DATE NULL,
  end_date DATE NULL,
  dr_commercial_account_id INT NULL,
  notes TEXT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_mgmt_rev_acct_org_code (organization_id, account_code),
  INDEX idx_mgmt_rev_acct_org_group (organization_id, revenue_group),
  INDEX idx_mgmt_rev_acct_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mgmt_revenue_pricing_schedules (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  account_id BIGINT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  pricing_method VARCHAR(32) NOT NULL,
  pricing_unit VARCHAR(32) NOT NULL DEFAULT 'lbs',
  rate_per_unit DECIMAL(12,4) NULL,
  tiers_json JSON NULL,
  created_by INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mgmt_rev_price_acct (account_id, effective_from),
  INDEX idx_mgmt_rev_price_active (account_id, effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
