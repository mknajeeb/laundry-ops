-- Partner roster share links (read-only, tokenized, privacy-safe defaults).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS payroll_roster_share_links (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  geofence_id INT NULL,
  token VARCHAR(64) NOT NULL,
  title VARCHAR(128) NOT NULL DEFAULT 'Partner Roster',
  date_start DATE NOT NULL,
  date_end DATE NOT NULL,
  include_shift_ids JSON NULL,
  include_work_stream_ids JSON NULL,
  include_role_ids JSON NULL,
  show_phone TINYINT(1) NOT NULL DEFAULT 0,
  show_worker_category TINYINT(1) NOT NULL DEFAULT 0,
  show_internal_notes TINYINT(1) NOT NULL DEFAULT 0,
  show_performance TINYINT(1) NOT NULL DEFAULT 0,
  published_only TINYINT(1) NOT NULL DEFAULT 1,
  mode VARCHAR(16) NOT NULL DEFAULT 'live',
  expires_at TIMESTAMP NULL,
  password_hash VARCHAR(255) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  revoked_at TIMESTAMP NULL,
  last_accessed_at TIMESTAMP NULL,
  UNIQUE KEY uq_prsl_token (token),
  INDEX idx_prsl_org (organization_id, active),
  CONSTRAINT fk_prsl_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_roster_share_access_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  share_link_id INT NOT NULL,
  accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR(64) NULL,
  user_agent VARCHAR(512) NULL,
  INDEX idx_prsal_link (share_link_id, accessed_at),
  CONSTRAINT fk_prsal_link FOREIGN KEY (share_link_id) REFERENCES payroll_roster_share_links(id) ON DELETE CASCADE
) ENGINE=InnoDB;
