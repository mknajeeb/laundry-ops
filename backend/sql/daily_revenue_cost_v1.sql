-- DEPRECATED FILENAME — Daily Revenue & Cost schema lives in v2.
--
-- Do NOT apply this file. Use:
--   backend/sql/daily_revenue_cost_v2.sql
--
-- Runtime table creation references v2 via ensure_daily_revenue_cost_tables()
-- in backend/daily_revenue_cost.py (not this filename).
--
-- MIGRATION SAFETY: If any environment has v1 tables (dr_cost_settings,
-- dr_daily_entries with self_service_cash column, dr_rinse_wf_tiers with
-- organization_id), runtime ensure will FAIL LOUDLY. Manual migration required.

SELECT 'Use backend/sql/daily_revenue_cost_v2.sql instead of this file' AS migration_notice;
