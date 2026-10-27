-- Task Activity Groups: named multi-task activities with one shared PIN timer.
-- Distinct from assignment_group_id (shared employees) and task_checklists (verification).

CREATE TABLE IF NOT EXISTS task_activity_groups (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(40) NOT NULL,
  name VARCHAR(80) NOT NULL,
  category_code VARCHAR(40) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_tag_org_code (organization_id, code),
  INDEX idx_tag_org_order (organization_id, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_activity_group_items (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  group_id INT NOT NULL,
  task_code VARCHAR(64) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  required TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_tagi (group_id, task_code),
  INDEX idx_tagi_org (organization_id, group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cleaning_task_activity_items (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  activity_id BIGINT NOT NULL,
  task_code VARCHAR(64) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  required TINYINT(1) NOT NULL DEFAULT 1,
  status VARCHAR(32) NOT NULL,
  completed_at DATETIME NULL,
  completion_input_json TEXT NULL,
  child_activity_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ctai (activity_id, task_code),
  INDEX idx_ctai_org_activity (organization_id, activity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'task_activity_groups_v1 complete.' AS note;
