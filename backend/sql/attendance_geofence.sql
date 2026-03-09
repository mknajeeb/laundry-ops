CREATE TABLE IF NOT EXISTS geofence_settings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  label VARCHAR(120) NOT NULL,
  latitude DECIMAL(10, 8) NOT NULL,
  longitude DECIMAL(11, 8) NOT NULL,
  radius_m INT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_by VARCHAR(100) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  employee_id INT NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  event_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  device_time VARCHAR(80) NULL,
  latitude DECIMAL(10, 8) NOT NULL,
  longitude DECIMAL(11, 8) NOT NULL,
  within_geofence BOOLEAN NOT NULL,
  distance_m DECIMAL(10, 2) NOT NULL,
  geofence_id INT NULL,
  notes VARCHAR(255) NULL,
  personal_bags INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_attendance_employee_time (employee_id, event_time),
  INDEX idx_attendance_event_type (event_type)
);

CREATE TABLE IF NOT EXISTS employee_geo_presence (
  employee_id INT PRIMARY KEY,
  is_inside BOOLEAN NOT NULL,
  latitude DECIMAL(10, 8) NOT NULL,
  longitude DECIMAL(11, 8) NOT NULL,
  last_seen_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS geofence_alerts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  employee_id INT NOT NULL,
  transition_type VARCHAR(20) NOT NULL,
  geofence_id INT NULL,
  latitude DECIMAL(10, 8) NOT NULL,
  longitude DECIMAL(11, 8) NOT NULL,
  distance_m DECIMAL(10, 2) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_alerts_created (created_at),
  INDEX idx_alerts_employee (employee_id)
);
