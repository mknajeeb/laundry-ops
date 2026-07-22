-- Payroll analytics dashboard permission (idempotent).
INSERT IGNORE INTO permissions (perm_key, description) VALUES
('payroll.analytics.view', 'View payroll analytics dashboard & summary exports (read-only)');

UPDATE permissions SET
  route_key = 'payroll', route_label = 'Payroll', section_key = 'main', section_label = 'Module access',
  resource_key = 'analytics', resource_label = 'Analytics dashboard', action_key = 'view', sort_order = 2115
WHERE perm_key = 'payroll.analytics.view';

SELECT 'payroll_analytics_dashboard_perm_v1 complete.' AS note;
