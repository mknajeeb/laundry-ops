-- Per-tenant users excluded from folding leaderboard / TV / team scoring.
CREATE TABLE IF NOT EXISTS rinse_folding_excluded_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT UNSIGNED NOT NULL,
  user_name VARCHAR(255) NULL,
  employee_id VARCHAR(64) NULL,
  reason VARCHAR(512) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by_user_id INT UNSIGNED NULL,
  UNIQUE KEY uq_rfeu_org_user (organization_id, user_name),
  KEY idx_rfeu_org_emp (organization_id, employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
