-- Task Management: categories + task definition config + activity extensions.
-- Reuses weekly_schedule_roles (task codes) and cleaning_task_activities (execution).
-- Historical role codes and activity rows remain valid.

CREATE TABLE IF NOT EXISTS task_categories (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(40) NOT NULL,
  name VARCHAR(80) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_task_cat_org_code (organization_id, code),
  INDEX idx_task_cat_org_order (organization_id, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_checklists (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(40) NOT NULL,
  name VARCHAR(80) NOT NULL,
  category_id INT NULL,
  verification_required TINYINT(1) NOT NULL DEFAULT 1,
  verification_method VARCHAR(32) NOT NULL DEFAULT 'employee',
  verification_timing VARCHAR(32) NOT NULL DEFAULT 'next_day',
  verifier_config_json TEXT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_task_cl_org_code (organization_id, code),
  INDEX idx_task_cl_org (organization_id, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_checklist_items (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  checklist_id INT NOT NULL,
  task_code VARCHAR(64) NOT NULL,
  display_order INT NOT NULL DEFAULT 0,
  required TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_task_cli (checklist_id, task_code),
  INDEX idx_task_cli_org (organization_id, checklist_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_checklist_verifications (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  checklist_id INT NOT NULL,
  business_date DATE NOT NULL,
  status VARCHAR(32) NOT NULL,
  verified_by_user_id INT NULL,
  verified_at DATETIME NULL,
  rejection_reason VARCHAR(500) NULL,
  payload_json TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_task_clv (organization_id, checklist_id, business_date),
  INDEX idx_task_clv_status (organization_id, status, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'task_management_v1 complete.' AS note;
