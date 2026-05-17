-- Admin override audit for folding performance rows.
CREATE TABLE IF NOT EXISTS rinse_folding_performance_overrides (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  performance_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  field_name VARCHAR(64) NOT NULL,
  old_value TEXT NULL,
  new_value TEXT NULL,
  actor_user_id INT NULL,
  notes TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_rfpo_perf (performance_id),
  KEY idx_rfpo_org_bag (organization_id, bag_id),
  KEY idx_rfpo_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
