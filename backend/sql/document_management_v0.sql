-- Document management (HR / compliance packets) — schema v0
-- Pairs with organizations_multitenancy_v1.sql (FK organization_id).
--
-- Flow:
--   1) Canonical employee data lives in payroll_profiles + users (per org).
--   2) document_templates describe fillable outputs: official PDF AcroForms, HTML layouts, or external DOCX refs.
--   3) employee_documents store merge payload (JSON), optional overrides after PDF generation, and blob URI.
--
-- Your draft archive includes: NY IT-2104, LS51–LS57, VeeWash contractor C-101…C-106 (DOCX), bilingual packs.
-- Keep template binaries in blob storage or /static; reference via storage_uri.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS document_templates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(255) NOT NULL,
  template_kind ENUM('pdf_acroform','html_print','docx_external') NOT NULL DEFAULT 'pdf_acroform',
  jurisdiction VARCHAR(32) NULL COMMENT 'e.g. US-FED, US-NY',
  is_official_gov_form TINYINT(1) NOT NULL DEFAULT 0,
  storage_uri VARCHAR(1024) NULL COMMENT 'Blob URL, app path, or template id',
  field_map_json JSON NULL COMMENT 'logical_key -> pdf field name or merge tag',
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
  subject_user_id INT NOT NULL COMMENT 'Washpro users.id for this org',
  template_id INT NOT NULL,
  status ENUM('draft','filled','exported') NOT NULL DEFAULT 'draft',
  profile_snapshot_json JSON NULL COMMENT 'Field values at generation time',
  overrides_json JSON NULL COMMENT 'Post-export manual edits metadata (optional)',
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
