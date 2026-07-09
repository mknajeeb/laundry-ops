-- Daily Revenue & Cost v2 — long-term financial module for LaundryOps.
--
-- MIGRATION SAFETY:
--   Safe to run ONLY on environments where Daily Revenue/Cost has NOT been deployed yet.
--   If v1 tables exist (dr_cost_settings, dr_daily_entries.self_service_cash column,
--   dr_rinse_wf_tiers.organization_id), do NOT run this file blindly.
--   Runtime ensure_daily_revenue_cost_tables() will FAIL LOUDLY if v1 is detected.
--   Contact engineering for a manual v1→v2 migration before applying in that case.
--
-- Apply: mysql ... < backend/sql/daily_revenue_cost_v2.sql
-- Runtime ensure also exists in backend/daily_revenue_cost.py (references this file).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS dr_commercial_accounts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  external_ref VARCHAR(128) NULL COMMENT 'POS / accounting customer id',
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dr_ca_org_name (organization_id, name),
  INDEX idx_dr_ca_org_active (organization_id, active, sort_order),
  CONSTRAINT fk_dr_ca_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_commercial_pricing_schedules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  commercial_account_id INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  billing_model VARCHAR(16) NOT NULL DEFAULT 'per_lb' COMMENT 'per_lb | flat | hybrid',
  rate_per_pound DECIMAL(10, 4) NULL,
  flat_amount DECIMAL(12, 2) NULL,
  logistics_charge DECIMAL(12, 2) NOT NULL DEFAULT 0,
  additional_charge DECIMAL(12, 2) NOT NULL DEFAULT 0,
  notes VARCHAR(255) NULL,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_dr_cps_account_dates (commercial_account_id, effective_from, effective_to),
  CONSTRAINT fk_dr_cps_account FOREIGN KEY (commercial_account_id) REFERENCES dr_commercial_accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_rinse_wf_pricing_schedules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  name VARCHAR(128) NULL,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_dr_wfps_org_dates (organization_id, effective_from, effective_to),
  CONSTRAINT fk_dr_wfps_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_rinse_wf_tier_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  schedule_id INT NOT NULL,
  tier_number INT NOT NULL,
  max_lbs INT NULL COMMENT 'Cumulative cap; NULL = unlimited',
  rate_per_lb DECIMAL(10, 4) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_dr_wftl_sched_tier (schedule_id, tier_number),
  CONSTRAINT fk_dr_wftl_sched FOREIGN KEY (schedule_id) REFERENCES dr_rinse_wf_pricing_schedules(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_cost_schedules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  payroll_tax_pct DECIMAL(8, 4) NULL,
  payroll_tax_daily_fixed DECIMAL(12, 2) NULL,
  rent_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'fixed',
  insurance_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'fixed',
  property_tax_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'fixed',
  electricity_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  water_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  gas_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  supplies_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  maintenance_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  adjustments_daily DECIMAL(12, 2) NOT NULL DEFAULT 0 COMMENT 'variable',
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_dr_cs_org_dates (organization_id, effective_from, effective_to),
  CONSTRAINT fk_dr_cs_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_daily_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  entry_date DATE NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'open' COMMENT 'open | locked | submitted | approved | rejected',
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  modified_by INT NULL,
  modified_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  locked_by INT NULL,
  locked_at DATETIME NULL,
  submitted_by INT NULL,
  submitted_at DATETIME NULL,
  reviewed_by INT NULL,
  reviewed_at DATETIME NULL,
  review_notes TEXT NULL,
  UNIQUE KEY uq_dr_entry_org_date (organization_id, entry_date),
  INDEX idx_dr_entry_org_status (organization_id, status, entry_date),
  CONSTRAINT fk_dr_entry_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_daily_entry_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  daily_entry_id INT NOT NULL,
  line_key VARCHAR(64) NOT NULL,
  line_category VARCHAR(16) NOT NULL COMMENT 'revenue | payroll | cost_fixed | cost_variable',
  amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
  quantity DECIMAL(12, 2) NULL,
  commercial_account_id INT NULL,
  source_system VARCHAR(32) NOT NULL DEFAULT 'manual',
  source_ref VARCHAR(128) NULL,
  source_captured_at DATETIME NULL,
  source_payload JSON NULL,
  is_manual_override TINYINT(1) NOT NULL DEFAULT 0,
  override_reason VARCHAR(255) NULL,
  overridden_by INT NULL,
  overridden_at DATETIME NULL,
  pricing_schedule_id INT NULL,
  rate_snapshot_json JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dr_del_entry_key (daily_entry_id, line_key),
  INDEX idx_dr_del_entry (daily_entry_id),
  INDEX idx_dr_del_source (source_system),
  CONSTRAINT fk_dr_del_entry FOREIGN KEY (daily_entry_id) REFERENCES dr_daily_entries(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_entry_audit_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  daily_entry_id INT NULL,
  event_type VARCHAR(32) NOT NULL,
  line_key VARCHAR(64) NULL,
  field_name VARCHAR(64) NULL,
  old_value TEXT NULL,
  new_value TEXT NULL,
  source_system VARCHAR(32) NULL,
  actor_user_id INT NULL,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_dr_eae_entry (daily_entry_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dr_integration_sync_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  entry_date DATE NOT NULL,
  source_system VARCHAR(32) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  records_imported INT NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  payload_json JSON NULL,
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP NULL,
  INDEX idx_dr_isr_org_date (organization_id, entry_date, source_system),
  CONSTRAINT fk_dr_isr_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;
