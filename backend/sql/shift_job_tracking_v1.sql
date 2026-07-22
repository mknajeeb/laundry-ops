-- Shift task tracking Phase 1: Category + Role model.
-- Operator/Folder are shared role definitions assigned per category.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ta_task_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ttc_org_code (organization_id, code),
  INDEX idx_ttc_org_active (organization_id, active, sort_order)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ta_task_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ttr_org_code (organization_id, code),
  INDEX idx_ttr_org_active (organization_id, active, sort_order)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ta_task_category_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  category_id INT NOT NULL,
  role_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ttcr_cat_role (category_id, role_id),
  INDEX idx_ttcr_org (organization_id, active, sort_order),
  CONSTRAINT fk_ttcr_category FOREIGN KEY (category_id) REFERENCES ta_task_categories(id),
  CONSTRAINT fk_ttcr_role FOREIGN KEY (role_id) REFERENCES ta_task_roles(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS shift_job_segments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  shift_session_id INT NOT NULL,
  user_id INT NULL,
  category_id INT NULL,
  role_id INT NULL,
  category_role_id INT NULL,
  category_code VARCHAR(64) NULL,
  role_code VARCHAR(64) NULL,
  category_name_snapshot VARCHAR(128) NULL,
  role_name_snapshot VARCHAR(128) NULL,
  job_name_id INT NULL,
  started_at DATETIME NOT NULL,
  ended_at DATETIME NULL,
  change_source VARCHAR(64) NULL,
  close_source VARCHAR(64) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_sjs_session (shift_session_id, started_at),
  INDEX idx_sjs_category_role (category_id, role_id),
  CONSTRAINT fk_sjs_session FOREIGN KEY (shift_session_id) REFERENCES shift_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Session extensions (also applied via ensure_schema):
-- scheduled_end_at, force_checkout_at, force_checkout_waived, force_checked_out_at,
-- checkout_type, continuation_allowed, continued_after_force_at,
-- current_category_id, current_role_id, current_category_role_id
