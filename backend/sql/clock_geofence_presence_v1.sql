-- Tracks how long a user has been inside the work geofence without clocking in (for reminder push).
-- Run against tenant DB after deploy.

CREATE TABLE IF NOT EXISTS user_clock_geofence_presence (
  user_id INT NOT NULL,
  organization_id INT NOT NULL,
  inside_since DATETIME NULL,
  last_reminder_at DATETIME NULL,
  PRIMARY KEY (user_id),
  KEY idx_ucgp_org (organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
