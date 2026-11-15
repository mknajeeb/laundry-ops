-- Supervisor portal (Track 2). Additive and idempotent.
-- Does not alter folding scans, session approvals, payroll, or task tables.
-- Rollback: drop only the tables listed at the bottom. Do not run the rollback
-- in production without an explicit restore plan; historical rows live here.

CREATE TABLE IF NOT EXISTS supervisor_role_targets (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  unit VARCHAR(32) NULL,
  target_value DECIMAL(14,4) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  above_target_policy VARCHAR(16) NOT NULL DEFAULT 'uncapped',
  status VARCHAR(16) NOT NULL DEFAULT 'published',
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_supervisor_role_target (organization_id, role_key, effective_from, status),
  KEY idx_supervisor_role_target_day (organization_id, role_key, effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_employee_primary_roles (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  role_key VARCHAR(32) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  notes VARCHAR(500) NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_supervisor_primary_role (organization_id, user_id, effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_session_adjustments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  business_date_et DATE NOT NULL,
  session_id VARCHAR(64) NULL,
  employee_user_id INT NULL,
  employee_name VARCHAR(255) NULL,
  kind VARCHAR(32) NOT NULL,
  original_start VARCHAR(40) NULL,
  original_end VARCHAR(40) NULL,
  original_hours DECIMAL(14,4) NULL,
  original_rate DECIMAL(14,4) NULL,
  original_lbs DECIMAL(14,4) NULL,
  eligible_start VARCHAR(40) NULL,
  eligible_end VARCHAR(40) NULL,
  eligible_hours DECIMAL(14,4) NULL,
  eligible_percent DECIMAL(8,4) NULL,
  reallocated_role_key VARCHAR(32) NULL,
  reallocated_hours DECIMAL(14,4) NULL,
  manual_rate DECIMAL(14,4) NULL,
  reason VARCHAR(255) NOT NULL,
  notes TEXT NULL,
  actor_user_id INT NULL,
  actor_name VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reversed_at DATETIME NULL,
  reversed_by INT NULL,
  reversal_reason VARCHAR(255) NULL,
  KEY idx_supervisor_adj_day (organization_id, business_date_et, session_id),
  KEY idx_supervisor_adj_emp (organization_id, business_date_et, employee_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_quality_issue_types (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  code VARCHAR(64) NOT NULL,
  label VARCHAR(128) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_supervisor_issue_type (organization_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_quality_weight_versions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  effective_from DATE NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'draft',
  weights_json MEDIUMTEXT NOT NULL,
  severity_json MEDIUMTEXT NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_supervisor_weight_ver (organization_id, status, effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_quality_incidents (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  week_start DATE NOT NULL,
  issue_type VARCHAR(64) NOT NULL,
  severity VARCHAR(32) NULL,
  quantity INT NOT NULL DEFAULT 1,
  incident_key VARCHAR(160) NOT NULL,
  reference VARCHAR(500) NULL,
  notes TEXT NULL,
  role_key VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
  weight_version_id BIGINT NULL,
  points DECIMAL(14,4) NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  voided_at DATETIME NULL,
  voided_by INT NULL,
  void_reason VARCHAR(255) NULL,
  UNIQUE KEY uq_supervisor_incident (organization_id, incident_key),
  KEY idx_supervisor_incident_week (organization_id, week_start, voided_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_quality_incident_employees (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  incident_id BIGINT NOT NULL,
  organization_id INT NOT NULL,
  user_id INT NULL,
  employee_name VARCHAR(255) NULL,
  role_key VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_supervisor_incident_emp (incident_id, user_id, employee_name),
  KEY idx_supervisor_incident_emp_org (organization_id, incident_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_training_templates (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  title VARCHAR(160) NOT NULL,
  role_key VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
  category VARCHAR(64) NOT NULL DEFAULT 'general',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_supervisor_training_tpl (organization_id, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_training_versions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  template_id BIGINT NOT NULL,
  version_number INT NOT NULL,
  instructions TEXT NULL,
  practical_required TINYINT(1) NOT NULL DEFAULT 0,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_supervisor_training_ver (template_id, version_number),
  KEY idx_supervisor_training_ver_org (organization_id, template_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_training_items (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  version_id BIGINT NOT NULL,
  label VARCHAR(255) NOT NULL,
  required_step TINYINT(1) NOT NULL DEFAULT 1,
  needs_evidence TINYINT(1) NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  KEY idx_supervisor_training_item (version_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_training_assignments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  version_id BIGINT NOT NULL,
  trainee_user_id INT NOT NULL,
  trainer_user_id INT NULL,
  reason VARCHAR(64) NOT NULL,
  assigned_on DATE NOT NULL,
  due_on DATE NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'assigned',
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  competency_result VARCHAR(16) NULL,
  verified_by INT NULL,
  verified_at DATETIME NULL,
  supervisor_notes TEXT NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_supervisor_training_asg (organization_id, trainee_user_id, status),
  KEY idx_supervisor_training_due (organization_id, due_on, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_training_progress (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  assignment_id BIGINT NOT NULL,
  item_id BIGINT NOT NULL,
  done TINYINT(1) NOT NULL DEFAULT 0,
  done_at DATETIME NULL,
  done_by INT NULL,
  UNIQUE KEY uq_supervisor_training_prog (assignment_id, item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supervisor_feature_flags (
  organization_id INT NOT NULL,
  flag_key VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (organization_id, flag_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback (manual, explicit authorization only):
-- DROP TABLE IF EXISTS supervisor_training_progress;
-- DROP TABLE IF EXISTS supervisor_training_assignments;
-- DROP TABLE IF EXISTS supervisor_training_items;
-- DROP TABLE IF EXISTS supervisor_training_versions;
-- DROP TABLE IF EXISTS supervisor_training_templates;
-- DROP TABLE IF EXISTS supervisor_quality_incident_employees;
-- DROP TABLE IF EXISTS supervisor_quality_incidents;
-- DROP TABLE IF EXISTS supervisor_quality_weight_versions;
-- DROP TABLE IF EXISTS supervisor_quality_issue_types;
-- DROP TABLE IF EXISTS supervisor_session_adjustments;
-- DROP TABLE IF EXISTS supervisor_employee_primary_roles;
-- DROP TABLE IF EXISTS supervisor_role_targets;
-- DROP TABLE IF EXISTS supervisor_feature_flags;
