-- Per-tenant federal W-4 Step 3 credit amounts by tax year (maintainable without code deploy).
-- Run once per environment. App also ensures table at runtime if missing.

CREATE TABLE IF NOT EXISTS tax_form_year_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  tax_year SMALLINT NOT NULL,
  form_code VARCHAR(16) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  w4_step3_child_credit_amount DECIMAL(12,2) NOT NULL DEFAULT 2000.00,
  w4_step3_other_dependent_credit_amount DECIMAL(12,2) NOT NULL DEFAULT 500.00,
  w4_allow_other_credits TINYINT(1) NOT NULL DEFAULT 1,
  w4_enable_manual_override TINYINT(1) NOT NULL DEFAULT 1,
  effective_start_date DATE NULL,
  effective_end_date DATE NULL,
  notes TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_tenant_year_form (organization_id, tax_year, form_code),
  KEY idx_tfs_org (organization_id),
  KEY idx_tfs_year (tax_year)
) ENGINE=InnoDB;

-- Example seed for current orgs: replace organization_id or run from app after first row exists.
