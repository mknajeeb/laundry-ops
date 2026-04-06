-- Document compliance policy + employee document records (Phase 1)
-- Safe to run multiple times.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS org_document_compliance_policy (
  organization_id INT NOT NULL PRIMARY KEY,
  reminder_days_before INT NOT NULL DEFAULT 14,
  push_enabled TINYINT(1) NOT NULL DEFAULT 1,
  prompt_enabled TINYINT(1) NOT NULL DEFAULT 1,
  disable_profile_on_expiry TINYINT(1) NOT NULL DEFAULT 0,
  enforce_on_clock_in TINYINT(1) NOT NULL DEFAULT 0,
  updated_by_user_id INT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_odcp_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_odcp_user FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS employee_document_records (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  document_code VARCHAR(80) NOT NULL,
  document_name VARCHAR(255) NOT NULL,
  form_locale VARCHAR(16) NULL,
  source_kind ENUM('uploaded','generated','external') NOT NULL DEFAULT 'uploaded',
  status ENUM('pending','received','verified','expired','rejected') NOT NULL DEFAULT 'received',
  issued_on DATE NULL,
  expires_on DATE NULL,
  reminder_days_before INT NULL,
  disable_profile_on_expiry TINYINT(1) NOT NULL DEFAULT 0,
  file_uri VARCHAR(1024) NULL,
  notes TEXT NULL,
  metadata_json JSON NULL,
  verified_by_user_id INT NULL,
  verified_at DATETIME NULL,
  created_by_user_id INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_edr_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_edr_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_edr_verifier FOREIGN KEY (verified_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_edr_author FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_edr_org_user (organization_id, user_id),
  INDEX idx_edr_org_code_exp (organization_id, document_code, expires_on),
  INDEX idx_edr_org_exp (organization_id, expires_on)
) ENGINE=InnoDB;
