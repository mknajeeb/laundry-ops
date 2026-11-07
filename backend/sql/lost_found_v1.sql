-- Lost & Found v1.
-- Apply with backend/scripts/prepare_lost_found_schema.py.
-- Request paths do not create these tables.
-- Additive and idempotent: CREATE TABLE IF NOT EXISTS only.
-- The preparation procedure also seeds weekly_schedule_roles
-- custom_lost_found_reconciliation once per organization when that
-- Activity definition is missing. It does not update an existing definition.

CREATE TABLE IF NOT EXISTS found_items (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  client_request_id VARCHAR(64) NOT NULL,
  reported_by_user_id INT NOT NULL,
  reporter_name VARCHAR(160) NOT NULL,
  facility_name VARCHAR(200) NULL,
  shift_session_id INT NULL,
  business_date DATE NOT NULL,
  reported_at DATETIME NOT NULL,
  location_kind VARCHAR(32) NOT NULL,
  location_number VARCHAR(40) NULL,
  location_detail VARCHAR(160) NULL,
  location_label VARCHAR(200) NOT NULL,
  notes VARCHAR(1000) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'new',
  order_reference VARCHAR(80) NULL,
  status_comment VARCHAR(1000) NULL,
  resolved_reason VARCHAR(500) NULL,
  revision INT NOT NULL DEFAULT 1,
  status_changed_at DATETIME NOT NULL,
  status_changed_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,
  UNIQUE KEY uq_found_item_client (organization_id, client_request_id),
  KEY idx_found_item_org_day (organization_id, business_date),
  KEY idx_found_item_org_status (organization_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS found_item_photos (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  found_item_id BIGINT NULL,
  business_date DATE NULL,
  photo_role VARCHAR(20) NOT NULL,
  blob_name VARCHAR(255) NOT NULL,
  stored_filename VARCHAR(80) NOT NULL,
  content_type VARCHAR(80) NOT NULL,
  storage VARCHAR(16) NOT NULL,
  captured_at DATETIME NOT NULL,
  uploaded_by_user_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_found_photo_item (found_item_id),
  KEY idx_found_photo_day (organization_id, business_date, photo_role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS found_item_events (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  found_item_id BIGINT NULL,
  event_type VARCHAR(40) NOT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(160) NULL,
  payload_json TEXT NULL,
  created_at DATETIME NOT NULL,
  KEY idx_found_event_item (found_item_id),
  KEY idx_found_event_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS found_item_accounts (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date DATE NOT NULL,
  found_item_id BIGINT NOT NULL,
  revision INT NOT NULL,
  status_snapshot VARCHAR(32) NOT NULL,
  escalated TINYINT(1) NOT NULL DEFAULT 0,
  comment VARCHAR(1000) NULL,
  accounted_by_user_id INT NOT NULL,
  accounted_by_name VARCHAR(160) NULL,
  accounted_at DATETIME NOT NULL,
  UNIQUE KEY uq_found_account (organization_id, business_date, found_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS found_item_reconciliations (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'open',
  started_at DATETIME NOT NULL,
  completed_at DATETIME NULL,
  completed_by_user_id INT NULL,
  activity_id BIGINT NULL,
  box_photo_id BIGINT NULL,
  UNIQUE KEY uq_found_recon (organization_id, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS found_item_reconciliation_snapshots (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date DATE NOT NULL,
  activity_id BIGINT NULL,
  completed_by_user_id INT NOT NULL,
  completed_by_name VARCHAR(160) NULL,
  completed_at DATETIME NOT NULL,
  box_photo_id BIGINT NULL,
  snapshot_json LONGTEXT NOT NULL,
  KEY idx_found_snap_day (organization_id, business_date, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
