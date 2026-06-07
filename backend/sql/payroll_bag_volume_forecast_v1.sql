-- Bag Volume Labor Forecast — optional relational store (Phase 2).
-- Phase 1 uses JSON in system_settings key payroll_bag_volume_forecast_v1 via payroll_planning_settings.py.
-- Run when promoting forecast to first-class tables.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS payroll_labor_speed_parameters (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  role_id INT NOT NULL,
  work_stream_id INT NULL,
  unit_type VARCHAR(32) NOT NULL DEFAULT 'bags_per_hour'
    COMMENT 'bags_per_hour|pounds_per_hour|minutes_per_bag|minutes_per_order',
  planning_speed DECIMAL(12,4) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  notes TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_plsp_org_role_stream_unit (organization_id, role_id, work_stream_id, unit_type),
  INDEX idx_plsp_org_active (organization_id, active)
) ENGINE=InnoDB;

-- Future: payroll_bag_volume_forecast_runs (saved what-if scenarios)
-- Future: payroll_bag_volume_forecast_results (required vs scheduled gap per role/stream/day)
