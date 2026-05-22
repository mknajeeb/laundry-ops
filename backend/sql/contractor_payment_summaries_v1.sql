-- Contractor payment summaries (snapshots for printed Contractor Payment Summary forms).
-- Run after payroll_profiles / organizations exist. Idempotent.

CREATE TABLE IF NOT EXISTS contractor_payment_summaries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  pay_period_start DATE NULL,
  pay_period_end DATE NULL,
  invoice_date DATE NULL,
  approved_service_hours DECIMAL(10,2) NOT NULL DEFAULT 0,
  service_rate DECIMAL(10,2) NOT NULL DEFAULT 0,
  health_safety_credit_hours DECIMAL(10,2) NOT NULL DEFAULT 0,
  adjustments DECIMAL(10,2) NOT NULL DEFAULT 0,
  service_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  health_safety_credit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  total_payment DECIMAL(10,2) NOT NULL DEFAULT 0,
  payment_method VARCHAR(64) NULL,
  payment_reference VARCHAR(255) NULL,
  notes TEXT NULL,
  form_snapshot_json JSON NULL COMMENT 'Contractor/payment fields at generation time',
  clock_hours_source VARCHAR(32) NOT NULL DEFAULT 'manual',
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_cps_org_user (organization_id, user_id, created_at),
  CONSTRAINT fk_cps_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
