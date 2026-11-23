-- Notification assignment tables.
-- Apply with the same controlled SQL process as backend/sql/notification_module_v1.sql.
-- Idempotent: CREATE TABLE IF NOT EXISTS only. Safe to run again.
--
-- Does not insert recipients, does not activate routing, and does not change
-- user_roles, employee_mobile_pin_access, user_notification_preferences,
-- or notification_delivery_log.
--
-- Rollback, after routing has been deactivated:
--   DROP TABLE IF EXISTS notification_assignment_audit;
--   DROP TABLE IF EXISTS notification_category_recipients;
--   DROP TABLE IF EXISTS notification_category_settings;
--   DROP TABLE IF EXISTS notification_routing_activation;
-- Do not drop notification_delivery_log.

CREATE TABLE IF NOT EXISTS notification_routing_activation (
  organization_id INT NOT NULL PRIMARY KEY,
  management_routing_active TINYINT(1) NOT NULL DEFAULT 0,
  updated_by_user_id INT NULL,
  updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification_category_settings (
  organization_id INT NOT NULL,
  event_key VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  updated_by_user_id INT NULL,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY (organization_id, event_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification_category_recipients (
  organization_id INT NOT NULL,
  event_key VARCHAR(64) NOT NULL,
  user_id INT NOT NULL,
  assigned_by_user_id INT NULL,
  assigned_at DATETIME NOT NULL,
  PRIMARY KEY (organization_id, event_key, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification_assignment_audit (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  event_key VARCHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  actor_user_id INT NULL,
  detail_json TEXT NULL,
  created_at DATETIME NOT NULL,
  KEY idx_notif_assign_audit_org (organization_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
