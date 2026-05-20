-- Failed/successful attendance PIN attempts (kiosk punch + optional unlock).
SET @db := DATABASE();

SET @has := (
  SELECT COUNT(*) FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'auth_pin_attempts'
);
SET @sql := IF(
  @has = 0,
  'CREATE TABLE auth_pin_attempts (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    ip_address VARCHAR(64) NULL,
    user_id INT NULL,
    success TINYINT(1) NOT NULL DEFAULT 0,
    action VARCHAR(32) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_pin_attempts_org_ip_created (organization_id, ip_address, created_at),
    KEY idx_pin_attempts_org_created (organization_id, created_at)
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
  'SELECT ''skip auth_pin_attempts'' AS _note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
