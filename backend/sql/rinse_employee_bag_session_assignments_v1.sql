-- Manual bag → payroll role-session overrides for Employee Productivity.
-- Does not alter bag ownership, PRE credit, or payroll clock data.
CREATE TABLE IF NOT EXISTS rinse_employee_bag_session_assignments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  selected_date_et DATE NOT NULL,
  employee_name VARCHAR(255) NULL,
  session_id VARCHAR(64) NULL,
  segment_id INT NULL,
  assignment_source VARCHAR(32) NOT NULL DEFAULT 'manual',
  assigned_by_user_id INT NULL,
  note VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_bag_session_assign_org_bag_date (organization_id, bag_id, selected_date_et),
  KEY idx_bag_session_assign_org_date (organization_id, selected_date_et),
  KEY idx_bag_session_assign_segment (organization_id, segment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
