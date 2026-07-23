-- Maintenance Task List (employee checklist) — tables + permissions (idempotent).
-- Distinct from legacy maintenance_tasks / maintenance_assignments / maintenance_logs.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_task_definitions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  task_key VARCHAR(80) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
  days_of_week_json JSON NULL,
  is_required TINYINT(1) NOT NULL DEFAULT 1,
  require_note_if_incomplete TINYINT(1) NOT NULL DEFAULT 1,
  display_order INT NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  created_by_user_id INT NULL,
  updated_by_user_id INT NULL,
  UNIQUE KEY uq_mtl_def_org_key (organization_id, task_key),
  INDEX idx_mtl_def_org_active_order (organization_id, is_active, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_task_lists (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  employee_id INT NOT NULL,
  task_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
  notes TEXT NULL,
  submitted_at DATETIME NULL,
  submitted_by_user_id INT NULL,
  reopened_at DATETIME NULL,
  reopened_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_mtl_org_emp_date (organization_id, employee_id, task_date),
  INDEX idx_mtl_org_date_status (organization_id, task_date, status),
  INDEX idx_mtl_org_employee (organization_id, employee_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_task_list_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  maintenance_task_list_id INT NOT NULL,
  maintenance_task_definition_id INT NULL,
  task_name_snapshot VARCHAR(255) NOT NULL,
  task_description_snapshot TEXT NULL,
  is_required_snapshot TINYINT(1) NOT NULL DEFAULT 1,
  require_note_if_incomplete_snapshot TINYINT(1) NOT NULL DEFAULT 1,
  completed TINYINT(1) NOT NULL DEFAULT 0,
  completed_at DATETIME NULL,
  completed_by_user_id INT NULL,
  note TEXT NULL,
  display_order_snapshot INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_mtl_items_list (maintenance_task_list_id),
  INDEX idx_mtl_items_def (maintenance_task_definition_id),
  CONSTRAINT fk_mtl_items_list
    FOREIGN KEY (maintenance_task_list_id) REFERENCES maintenance_task_lists(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS maintenance_task_list_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  maintenance_task_list_id INT NULL,
  actor_user_id INT NULL,
  action VARCHAR(60) NOT NULL,
  entity_type VARCHAR(40) NULL,
  entity_id INT NULL,
  old_value JSON NULL,
  new_value JSON NULL,
  remarks TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mtl_events_list (maintenance_task_list_id, created_at),
  INDEX idx_mtl_events_org (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO permissions (perm_key, description) VALUES
('maintenance.tasks.view', 'View maintenance task lists'),
('maintenance.tasks.update', 'Update / save maintenance task progress'),
('maintenance.tasks.submit', 'Submit maintenance task lists'),
('maintenance.tasks.manage', 'Manage maintenance task definitions'),
('maintenance.tasks.reopen', 'Reopen submitted maintenance task lists'),
('maintenance.tasks.reports', 'View maintenance task list reports');

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'view', sort_order = 1210
WHERE perm_key = 'maintenance.tasks.view';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1211
WHERE perm_key = 'maintenance.tasks.update';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'submit', sort_order = 1212
WHERE perm_key = 'maintenance.tasks.submit';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'manage', sort_order = 1213
WHERE perm_key = 'maintenance.tasks.manage';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'reopen', sort_order = 1214
WHERE perm_key = 'maintenance.tasks.reopen';

UPDATE permissions SET
  route_key = 'maintenance', route_label = 'Maintenance',
  section_key = 'task_list', section_label = 'Task List',
  resource_key = '', resource_label = '', action_key = 'reports', sort_order = 1215
WHERE perm_key = 'maintenance.tasks.reports';

-- Admin: all
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('ADMIN', 'SUPER_ADMIN', 'PLATFORM_ADMIN')
  AND p.perm_key IN (
    'maintenance.tasks.view',
    'maintenance.tasks.update',
    'maintenance.tasks.submit',
    'maintenance.tasks.manage',
    'maintenance.tasks.reopen',
    'maintenance.tasks.reports'
  );

-- OPS / manager: attendant + reports + reopen
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('OPS')
  AND p.perm_key IN (
    'maintenance.tasks.view',
    'maintenance.tasks.update',
    'maintenance.tasks.submit',
    'maintenance.tasks.reopen',
    'maintenance.tasks.reports'
  );

-- Floor / attendant
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('FRONT_DESK')
  AND p.perm_key IN (
    'maintenance.tasks.view',
    'maintenance.tasks.update',
    'maintenance.tasks.submit'
  );

SELECT 'maintenance_task_list_v1 complete.' AS note;
