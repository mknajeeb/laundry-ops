USE laundryapp;

-- =========================================
-- AUTH + RBAC
-- =========================================

CREATE TABLE IF NOT EXISTS roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(50) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(150) NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id INT NOT NULL,
  role_id INT NOT NULL,
  assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, role_id),
  CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  token VARCHAR(120) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  revoked BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NULL,
  CONSTRAINT fk_auth_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =========================================
-- MAINTENANCE
-- =========================================

CREATE TABLE IF NOT EXISTS maintenance_tasks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  task_code VARCHAR(60) NOT NULL UNIQUE,
  task_name VARCHAR(150) NOT NULL,
  category VARCHAR(50) NOT NULL DEFAULT 'CLEANING',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL
);

CREATE TABLE IF NOT EXISTS maintenance_assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  task_id INT NOT NULL,
  assigned_to_employee_id INT NULL,
  assigned_to_name VARCHAR(150) NULL,
  due_date DATE NOT NULL,
  frequency_type VARCHAR(30) NOT NULL DEFAULT 'ONE_TIME',
  frequency_interval INT NOT NULL DEFAULT 1,
  weekdays_csv VARCHAR(20) NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'ASSIGNED',
  notes VARCHAR(255) NULL,
  created_by VARCHAR(100) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,
  CONSTRAINT fk_maintenance_assignments_task FOREIGN KEY (task_id) REFERENCES maintenance_tasks(id)
);

CREATE TABLE IF NOT EXISTS maintenance_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  assignment_id INT NULL,
  task_id INT NOT NULL,
  performed_by_employee_id INT NULL,
  performed_by_name VARCHAR(150) NOT NULL,
  performed_date DATE NOT NULL,
  start_time DATETIME NULL,
  end_time DATETIME NULL,
  pit1_done BOOLEAN NOT NULL DEFAULT FALSE,
  pit2_done BOOLEAN NOT NULL DEFAULT FALSE,
  big_pit_done BOOLEAN NOT NULL DEFAULT FALSE,
  washer_no VARCHAR(50) NULL,
  notes VARCHAR(500) NULL,
  source_type VARCHAR(20) NOT NULL DEFAULT 'ASSIGNED',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_maintenance_logs_task FOREIGN KEY (task_id) REFERENCES maintenance_tasks(id),
  CONSTRAINT fk_maintenance_logs_assignment FOREIGN KEY (assignment_id) REFERENCES maintenance_assignments(id)
);

CREATE TABLE IF NOT EXISTS maintenance_notifications (
  id INT AUTO_INCREMENT PRIMARY KEY,
  assignment_id INT NOT NULL,
  notification_type VARCHAR(30) NOT NULL,
  recipient_type VARCHAR(20) NOT NULL,
  recipient_value VARCHAR(150) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
  sent_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_maintenance_notifications_assignment FOREIGN KEY (assignment_id) REFERENCES maintenance_assignments(id)
);

-- =========================================
-- INVENTORY
-- =========================================

CREATE TABLE IF NOT EXISTS inventory_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  item_name VARCHAR(150) NOT NULL,
  category VARCHAR(20) NOT NULL,
  vendor_name VARCHAR(150) NULL,
  unit_label VARCHAR(50) NOT NULL DEFAULT 'unit',
  reorder_threshold DECIMAL(10,2) NOT NULL DEFAULT 0,
  on_hand_qty DECIMAL(10,2) NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL
);

CREATE TABLE IF NOT EXISTS inventory_counts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  item_id INT NOT NULL,
  counted_qty DECIMAL(10,2) NOT NULL,
  counted_by VARCHAR(150) NOT NULL,
  counted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notes VARCHAR(255) NULL,
  CONSTRAINT fk_inventory_counts_item FOREIGN KEY (item_id) REFERENCES inventory_items(id)
);

CREATE TABLE IF NOT EXISTS bag_sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sale_date DATE NOT NULL,
  customer_name VARCHAR(150) NOT NULL,
  sale_type VARCHAR(50) NOT NULL,
  qty INT NOT NULL,
  amount_paid VARCHAR(50) NULL,
  entered_by VARCHAR(150) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT IGNORE INTO roles (code, name) VALUES
('ADMIN', 'Administrator'),
('OPS', 'Operations'),
('FRONT_DESK', 'Front Desk'),
('MAINTENANCE', 'Maintenance');

INSERT IGNORE INTO maintenance_tasks (task_code, task_name, category) VALUES
('PIT1_CLEANING', 'Pit 1 Cleaning', 'CLEANING'),
('PIT2_CLEANING', 'Pit 2 Cleaning', 'CLEANING'),
('BIG_PIT_CLEANING', 'Big Pit Cleaning', 'CLEANING'),
('WASHER_CLEANING', 'Washer Cleaning', 'CLEANING'),
('DRYER_CLEANING', 'Dryer Cleaning', 'CLEANING'),
('ROOF_CLEANING', 'Roof Cleaning', 'CLEANING'),
('FLOOR_MOPPING', 'Floor Mopping', 'CLEANING'),
('MACHINE_CLEANING', 'Machine Cleaning', 'CLEANING');
