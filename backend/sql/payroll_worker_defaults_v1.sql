-- Payroll Management worker profile defaults (idempotent column add).
-- Backfill is applied by backend/payroll_worker_defaults.py — only null/blank fields.

SET NAMES utf8mb4;

-- Column added idempotently by ensure_payroll_schedule_v2() when app starts.
-- ALTER TABLE payroll_worker_profiles ADD COLUMN default_overtime_rate DECIMAL(10,2) NULL;

-- Manual backfill (safe to re-run):
-- UPDATE payroll_worker_profiles SET default_hourly_rate = 17.00
--   WHERE default_hourly_rate IS NULL OR default_hourly_rate <= 0;
-- UPDATE payroll_worker_profiles SET default_overtime_rate = 25.50
--   WHERE default_overtime_rate IS NULL OR default_overtime_rate <= 0;
-- UPDATE payroll_worker_profiles SET max_hours_per_week = 40
--   WHERE max_hours_per_week IS NULL;
-- UPDATE payroll_worker_profiles SET overtime_threshold = 30
--   WHERE overtime_threshold IS NULL;
