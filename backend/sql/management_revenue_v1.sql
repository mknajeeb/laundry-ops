-- Management Revenue — cash paid out (separate from revenue lines; auditable).

CREATE TABLE IF NOT EXISTS mgmt_cash_payouts (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  payout_date_et DATE NOT NULL,
  purpose VARCHAR(255) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  note VARCHAR(512) NULL,
  entered_by_user_id INT NULL,
  entered_by_name_snapshot VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_mgmt_cash_payout_org_date (organization_id, payout_date_et)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mgmt_cash_payout_audits (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  payout_id BIGINT NOT NULL,
  organization_id INT NOT NULL,
  action VARCHAR(32) NOT NULL,
  actor_user_id INT NULL,
  actor_name_snapshot VARCHAR(255) NULL,
  before_json JSON NULL,
  after_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mgmt_cash_payout_audit_payout (payout_id),
  INDEX idx_mgmt_cash_payout_audit_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
