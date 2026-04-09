-- People / payroll workspace DDL (also applied at runtime via backend.hr_workspace_schema).
-- Safe to run once manually if you prefer SQL over automatic ALTER on first API hit:
--
-- CREATE TABLE org_hr_lookup (...);  -- see backend/hr_workspace_schema.py
-- ALTER TABLE payroll_profiles ADD COLUMN dept_code VARCHAR(64) NULL;
-- ALTER TABLE payroll_profiles ADD COLUMN job_title_code VARCHAR(64) NULL;
-- ALTER TABLE payroll_profiles ADD COLUMN employment_status_code VARCHAR(64) NULL;
-- ALTER TABLE payroll_profiles ADD COLUMN language_code VARCHAR(64) NULL;
-- ALTER TABLE payroll_profiles ADD COLUMN laundry_experience TINYINT(1) NULL;
-- ALTER TABLE payroll_profiles ADD COLUMN clock_geofence_exempt TINYINT(1) NOT NULL DEFAULT 0;

SELECT 'Apply via app: first /api/ta/users or /api/ta/org-hr-lookups call runs ensure_people_workspace_schema()' AS note;
