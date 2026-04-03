-- Notification module: groups, event routing (include/exclude), delivery audit.
-- Run against your app database after backups.
--
-- Creates `user_notification_preferences` if it does not exist (fixes Error 1146 when ALTER ran first).
-- Legacy DBs that already have this table but WITHOUT sms_*: uncomment the ALTER block at the bottom.

-- ---------------------------------------------------------------------------
-- User notification preferences (Washpro users.id)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_notification_preferences (
  user_id INT NOT NULL PRIMARY KEY,
  email_out TINYINT(1) NOT NULL DEFAULT 1,
  email_in TINYINT(1) NOT NULL DEFAULT 0,
  push_out TINYINT(1) NOT NULL DEFAULT 1,
  push_in TINYINT(1) NOT NULL DEFAULT 0,
  sms_out TINYINT(1) NOT NULL DEFAULT 1,
  sms_in TINYINT(1) NOT NULL DEFAULT 0,
  whatsapp_out TINYINT(1) NOT NULL DEFAULT 0,
  whatsapp_in TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Legacy only (uncomment if an old table exists without sms_*; ignore Duplicate column if already present):
-- ALTER TABLE user_notification_preferences ADD COLUMN sms_out TINYINT(1) NOT NULL DEFAULT 1 AFTER push_in;
-- ALTER TABLE user_notification_preferences ADD COLUMN sms_in TINYINT(1) NOT NULL DEFAULT 0 AFTER sms_out;

-- ---------------------------------------------------------------------------
-- Groups & members (Washpro users.id within tenant)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_groups (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  description VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_notif_grp_org_name (organization_id, name),
  KEY idx_notif_grp_org (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification_group_members (
  group_id INT NOT NULL,
  user_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (group_id, user_id),
  KEY idx_ngm_user (user_id),
  CONSTRAINT fk_ngm_group FOREIGN KEY (group_id) REFERENCES notification_groups(id) ON DELETE CASCADE,
  CONSTRAINT fk_ngm_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- Event catalog + audience rules (include / exclude users or groups)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_event_definitions (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  event_key VARCHAR(64) NOT NULL,
  display_name VARCHAR(160) NOT NULL,
  description VARCHAR(1024) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_notif_evt_org_key (organization_id, event_key),
  KEY idx_notif_evt_org (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification_event_audiences (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  event_definition_id INT NOT NULL,
  organization_id INT NOT NULL,
  target_type ENUM('user','group') NOT NULL,
  target_id INT NOT NULL,
  rule_kind ENUM('include','exclude') NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_nea (event_definition_id, target_type, target_id, rule_kind),
  KEY idx_nea_org (organization_id),
  CONSTRAINT fk_nea_event FOREIGN KEY (event_definition_id) REFERENCES notification_event_definitions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- Delivery audit (best practice: traceability for compliance & debugging)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_delivery_log (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  event_key VARCHAR(64) NOT NULL,
  user_id INT NULL,
  channel VARCHAR(16) NOT NULL,
  status VARCHAR(32) NOT NULL,
  detail VARCHAR(512) NULL,
  payload_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ndl_org_created (organization_id, created_at),
  KEY idx_ndl_event (event_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
