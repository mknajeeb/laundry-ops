-- Read-path indexes for Rinse dashboard snapshot queries (months/years of growth).
-- Leaderboard / week scan: org + role + active + date range
-- Employee last-N: org + role + employee + active + date DESC

SET @db := DATABASE();

-- Leaderboard / employees week: equality on org/role/active + range on date
SET @exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'rinse_performance_session_approvals'
    AND INDEX_NAME = 'idx_rinse_perf_read_role_week'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE rinse_performance_session_approvals ADD KEY idx_rinse_perf_read_role_week (organization_id, role_key, invalidated_at, business_date_et)',
  'SELECT ''skip idx_rinse_perf_read_role_week'' AS _note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Employee history / last-N: org + role + employee + active + chronological
SET @exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'rinse_performance_session_approvals'
    AND INDEX_NAME = 'idx_rinse_perf_read_emp_hist'
);
SET @sql := IF(
  @exists = 0,
  'ALTER TABLE rinse_performance_session_approvals ADD KEY idx_rinse_perf_read_emp_hist (organization_id, role_key, employee_user_id, invalidated_at, business_date_et, published_session_start_et, id)',
  'SELECT ''skip idx_rinse_perf_read_emp_hist'' AS _note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
