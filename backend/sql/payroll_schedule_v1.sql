-- Payroll scheduling (Phase 1): parameterized shifts, roles, work streams, worker profiles.
-- Worker identity uses users.id (same as payroll_profiles / performance clock mapping).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS payroll_schedule_org_settings (
  organization_id INT NOT NULL PRIMARY KEY,
  overtime_threshold_hours DECIMAL(6,2) NOT NULL DEFAULT 40.00,
  default_break_minutes INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_psos_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_shifts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(64) NOT NULL,
  start_time_default TIME NOT NULL,
  end_time_default TIME NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ps_shift (organization_id, name),
  INDEX idx_ps_shift_org (organization_id, active, sort_order),
  CONSTRAINT fk_ps_shift_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_work_streams (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(64) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pws_stream (organization_id, name),
  INDEX idx_pws_org (organization_id, active, sort_order),
  CONSTRAINT fk_pws_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  name VARCHAR(64) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pr_role (organization_id, name),
  INDEX idx_pr_org (organization_id, active, sort_order),
  CONSTRAINT fk_pr_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_worker_profiles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  user_id INT NOT NULL,
  worker_category VARCHAR(32) NOT NULL DEFAULT 'w2',
  default_hourly_rate DECIMAL(10,2) NULL,
  max_hours_per_week DECIMAL(6,2) NULL,
  overtime_threshold DECIMAL(6,2) NULL,
  can_work_rinse TINYINT(1) NOT NULL DEFAULT 1,
  can_work_drop_off TINYINT(1) NOT NULL DEFAULT 1,
  can_work_both TINYINT(1) NOT NULL DEFAULT 1,
  preferred_shift_id INT NULL,
  preferred_role_id INT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pwp_user (organization_id, user_id),
  INDEX idx_pwp_org_active (organization_id, active),
  CONSTRAINT fk_pwp_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwp_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwp_pref_shift FOREIGN KEY (preferred_shift_id) REFERENCES payroll_shifts(id) ON DELETE SET NULL,
  CONSTRAINT fk_pwp_pref_role FOREIGN KEY (preferred_role_id) REFERENCES payroll_roles(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_worker_availability (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_profile_id INT NOT NULL,
  day_of_week TINYINT NOT NULL COMMENT '0=Mon .. 6=Sun',
  available_from TIME NULL,
  available_to TIME NULL,
  preferred_shift_id INT NULL,
  unavailable_flag TINYINT(1) NOT NULL DEFAULT 0,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pwa_day (worker_profile_id, day_of_week),
  INDEX idx_pwa_profile (worker_profile_id),
  CONSTRAINT fk_pwa_profile FOREIGN KEY (worker_profile_id) REFERENCES payroll_worker_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwa_shift FOREIGN KEY (preferred_shift_id) REFERENCES payroll_shifts(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_worker_role_skills (
  id INT AUTO_INCREMENT PRIMARY KEY,
  worker_profile_id INT NOT NULL,
  role_id INT NOT NULL,
  work_stream_id INT NULL,
  skill_level TINYINT NOT NULL DEFAULT 1 COMMENT '1=basic .. 5=expert',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pwrs_skill (worker_profile_id, role_id, work_stream_id),
  INDEX idx_pwrs_profile (worker_profile_id),
  CONSTRAINT fk_pwrs_profile FOREIGN KEY (worker_profile_id) REFERENCES payroll_worker_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwrs_role FOREIGN KEY (role_id) REFERENCES payroll_roles(id) ON DELETE CASCADE,
  CONSTRAINT fk_pwrs_stream FOREIGN KEY (work_stream_id) REFERENCES payroll_work_streams(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payroll_schedule_entries (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  worker_profile_id INT NOT NULL,
  work_date DATE NOT NULL,
  shift_id INT NOT NULL,
  work_stream_id INT NULL,
  role_id INT NULL,
  geofence_id INT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  break_minutes INT NOT NULL DEFAULT 0,
  scheduled_hours DECIMAL(6,2) NOT NULL DEFAULT 0,
  hourly_rate_snapshot DECIMAL(10,2) NULL,
  estimated_cost DECIMAL(10,2) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
  replacement_for_schedule_id INT NULL,
  notes TEXT NULL,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_pse_org_date (organization_id, work_date),
  INDEX idx_pse_worker_date (worker_profile_id, work_date),
  INDEX idx_pse_status (organization_id, status),
  CONSTRAINT fk_pse_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
  CONSTRAINT fk_pse_worker FOREIGN KEY (worker_profile_id) REFERENCES payroll_worker_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_pse_shift FOREIGN KEY (shift_id) REFERENCES payroll_shifts(id),
  CONSTRAINT fk_pse_stream FOREIGN KEY (work_stream_id) REFERENCES payroll_work_streams(id) ON DELETE SET NULL,
  CONSTRAINT fk_pse_role FOREIGN KEY (role_id) REFERENCES payroll_roles(id) ON DELETE SET NULL,
  CONSTRAINT fk_pse_geofence FOREIGN KEY (geofence_id) REFERENCES geofences(id) ON DELETE SET NULL,
  CONSTRAINT fk_pse_replacement FOREIGN KEY (replacement_for_schedule_id) REFERENCES payroll_schedule_entries(id) ON DELETE SET NULL
) ENGINE=InnoDB;
