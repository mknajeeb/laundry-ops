-- HR compliance: extended worker profile + optional document management tables.
-- Idempotent. Run after organizations_multitenancy_v1.sql and payroll_profiles exist.
-- BACKUP FIRST.

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- hr_extended_profiles: VF-01 / contractor cover data not on payroll_profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hr_extended_profiles (
  user_id INT NOT NULL PRIMARY KEY,
  organization_id INT NOT NULL,
  preferred_name VARCHAR(128) NULL,
  date_of_birth DATE NULL,
  alternate_phone VARCHAR(32) NULL,
  emergency_contacts_json JSON NULL COMMENT 'Array of {name, relationship, phone, alt_phone}',
  work_json JSON NULL COMMENT 'department, job_title, supervisor_name, primary_work_location, language, mailing address fields',
  compliance_ack_json JSON NULL COMMENT 'laundry_experience, essential_duties_ack, worker_classification, etc.',
  contractor_json JSON NULL COMMENT 'business_name, agency, schedules, rate basis',
  tax_snapshots_json JSON NULL COMMENT 'Optional keyed withholding snapshots by year',
  i9_receipt_json JSON NULL COMMENT 'Non-PII metadata: last completed, document list labels',
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_hr_ep_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_hr_ep_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  INDEX idx_hr_ep_org (organization_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Document templates & generated files (from document_management_v0.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_templates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(255) NOT NULL,
  template_kind ENUM('pdf_acroform','html_print','docx_external') NOT NULL DEFAULT 'pdf_acroform',
  jurisdiction VARCHAR(32) NULL COMMENT 'e.g. US-FED, US-NY',
  is_official_gov_form TINYINT(1) NOT NULL DEFAULT 0,
  storage_uri VARCHAR(1024) NULL,
  field_map_json JSON NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_doc_tpl_org_code (organization_id, code),
  CONSTRAINT fk_doc_tpl_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS document_packages (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_doc_pkg_org_code (organization_id, code),
  CONSTRAINT fk_doc_pkg_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS document_package_items (
  package_id INT NOT NULL,
  template_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  PRIMARY KEY (package_id, template_id),
  CONSTRAINT fk_dpi_pkg FOREIGN KEY (package_id) REFERENCES document_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_dpi_tpl FOREIGN KEY (template_id) REFERENCES document_templates(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS employee_documents (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  subject_user_id INT NOT NULL COMMENT 'Washpro users.id',
  template_id INT NOT NULL,
  status ENUM('draft','filled','exported') NOT NULL DEFAULT 'draft',
  profile_snapshot_json JSON NULL,
  overrides_json JSON NULL,
  exported_uri VARCHAR(1024) NULL,
  exported_at DATETIME NULL,
  created_by_user_id INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_edoc_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_edoc_subject FOREIGN KEY (subject_user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_edoc_tpl FOREIGN KEY (template_id) REFERENCES document_templates(id) ON DELETE CASCADE,
  CONSTRAINT fk_edoc_author FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_edoc_org_subject (organization_id, subject_user_id)
) ENGINE=InnoDB;
