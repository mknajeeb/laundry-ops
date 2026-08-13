-- Shift Capacity Planner: Saved Simulations (management scenarios).
-- Separate from PARAMETERS (system_settings shift_capacity_planner_params_v1).
-- Idempotent. Applied via ensure_saved_simulations_table on first API use,
-- or manually: mysql ... < backend/sql/shift_capacity_saved_simulations_v1.sql

CREATE TABLE IF NOT EXISTS shift_capacity_saved_simulations (
  id BIGINT NOT NULL AUTO_INCREMENT,
  organization_id INT NOT NULL,
  name VARCHAR(120) NOT NULL,
  scenario_payload JSON NOT NULL,
  payload_version VARCHAR(16) NOT NULL,
  created_by_user_id INT NULL,
  updated_by_user_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_run_at DATETIME NULL,
  last_run_summary JSON NULL,
  PRIMARY KEY (id),
  KEY idx_scs_org_updated (organization_id, updated_at),
  KEY idx_scs_org_name (organization_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
