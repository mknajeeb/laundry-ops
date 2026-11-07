-- Lost & Found v1. Applied at runtime by backend.lost_found.ensure_lost_found_tables.
-- One found_items row per report. Photos and events are kept after status changes.
-- reported_at and other business clocks are naive America/New_York wall times.

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
