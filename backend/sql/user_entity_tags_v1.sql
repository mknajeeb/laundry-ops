-- Optional: flexible "entity" links per Laundry Ops user (location, route, cost center, …).
-- Idempotent. Run against your app schema after organizations + users exist.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS user_entity_tags (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  entity_type VARCHAR(64) NOT NULL,
  entity_key VARCHAR(128) NOT NULL,
  label VARCHAR(255) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_entity (user_id, entity_type, entity_key),
  KEY idx_uet_org (organization_id),
  CONSTRAINT fk_uet_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_uet_org FOREIGN KEY (organization_id) REFERENCES organizations(id)
) ENGINE=InnoDB;

SELECT 'user_entity_tags_v1 idempotent pass complete.' AS note;
