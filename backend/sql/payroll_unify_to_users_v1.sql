-- Unified payroll: Washpro users.id is the only payroll subject key (payroll_profiles).
-- Backup first. Inspect FK names: SHOW CREATE TABLE shift_sessions;
-- Adjust DROP FOREIGN KEY names below if your DB used different constraint names.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS payroll_period_settings (
  id INT PRIMARY KEY DEFAULT 1,
  week_starts_on TINYINT NOT NULL DEFAULT 0 COMMENT '0=Monday .. 6=Sunday',
  ref_prefix VARCHAR(16) NOT NULL DEFAULT 'PC',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

INSERT IGNORE INTO payroll_period_settings (id, week_starts_on, ref_prefix) VALUES (1, 0, 'PC');

CREATE TABLE IF NOT EXISTS payroll_profiles (
  user_id INT NOT NULL PRIMARY KEY,
  employee_id VARCHAR(64) NULL UNIQUE,
  first_name VARCHAR(128) NOT NULL,
  last_name VARCHAR(128) NOT NULL,
  address TEXT NULL,
  email VARCHAR(255) NOT NULL,
  mobile VARCHAR(32) NULL,
  itin_ssn VARCHAR(32) NULL,
  hire_date DATE NULL,
  termination_date DATE NULL,
  rehired TINYINT(1) DEFAULT 0,
  rehire_parent_user_id INT NULL,
  prior_employee_id VARCHAR(64) NULL,
  active TINYINT(1) DEFAULT 1,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_pp_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_pp_rehire_parent FOREIGN KEY (rehire_parent_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

INSERT IGNORE INTO payroll_profiles (
  user_id, employee_id, first_name, last_name, address, email, mobile, itin_ssn,
  hire_date, termination_date, rehired, rehire_parent_user_id, prior_employee_id,
  active, password_hash
)
SELECT
  t.washpro_user_id,
  t.employee_id,
  t.first_name,
  t.last_name,
  t.address,
  t.email,
  t.mobile,
  t.itin_ssn,
  t.hire_date,
  t.termination_date,
  t.rehired,
  (SELECT t2.washpro_user_id FROM ta_users t2 WHERE t2.id = t.rehire_parent_id LIMIT 1),
  t.prior_employee_id,
  t.active,
  t.password_hash
FROM ta_users t
WHERE t.washpro_user_id IS NOT NULL;

SET FOREIGN_KEY_CHECKS = 0;

-- Remove FKs to ta_users (names from ta_schema_washpro_addon.sql; change if needed)
ALTER TABLE user_geofences DROP FOREIGN KEY fk_ta_ug_user;
ALTER TABLE user_employment_categories DROP FOREIGN KEY fk_ta_uec_user;
ALTER TABLE user_rates DROP FOREIGN KEY fk_ta_ur_user;
ALTER TABLE shift_sessions DROP FOREIGN KEY fk_ta_ss_user;
ALTER TABLE shift_exceptions DROP FOREIGN KEY fk_ta_se_user;
ALTER TABLE payroll_adjustments DROP FOREIGN KEY fk_ta_pa_user;
ALTER TABLE payroll_adjustments DROP FOREIGN KEY fk_ta_pa_by;
ALTER TABLE bag_count_summary DROP FOREIGN KEY fk_ta_bcs_user;
ALTER TABLE payroll_payments DROP FOREIGN KEY fk_ta_pp_user;
ALTER TABLE payroll_payments DROP FOREIGN KEY fk_ta_pp_by;
ALTER TABLE audit_log DROP FOREIGN KEY fk_ta_al_actor;

UPDATE user_geofences ug JOIN ta_users t ON t.id = ug.user_id SET ug.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE user_employment_categories uec JOIN ta_users t ON t.id = uec.user_id SET uec.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE user_rates ur JOIN ta_users t ON t.id = ur.user_id SET ur.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE shift_sessions ss JOIN ta_users t ON t.id = ss.user_id SET ss.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE shift_exceptions se JOIN ta_users t ON t.id = se.user_id SET se.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE payroll_adjustments pa JOIN ta_users t ON t.id = pa.user_id SET pa.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE payroll_adjustments pa JOIN ta_users t ON t.id = pa.created_by SET pa.created_by = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL AND pa.created_by IS NOT NULL;
UPDATE bag_count_summary b JOIN ta_users t ON t.id = b.user_id SET b.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE payroll_payments pp JOIN ta_users t ON t.id = pp.user_id SET pp.user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL;
UPDATE payroll_payments pp JOIN ta_users t ON t.id = pp.created_by SET pp.created_by = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL AND pp.created_by IS NOT NULL;
UPDATE audit_log a JOIN ta_users t ON t.id = a.actor_user_id SET a.actor_user_id = t.washpro_user_id WHERE t.washpro_user_id IS NOT NULL AND a.actor_user_id IS NOT NULL;

DROP TABLE IF EXISTS ta_users;

ALTER TABLE user_geofences ADD CONSTRAINT fk_pp_ug_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_employment_categories ADD CONSTRAINT fk_pp_uec_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE user_rates ADD CONSTRAINT fk_pp_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE shift_sessions ADD CONSTRAINT fk_pp_ss_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE shift_exceptions ADD CONSTRAINT fk_pp_se_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE payroll_adjustments ADD CONSTRAINT fk_pp_pa_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE payroll_adjustments ADD CONSTRAINT fk_pp_pa_by FOREIGN KEY (created_by) REFERENCES users(id);
ALTER TABLE bag_count_summary ADD CONSTRAINT fk_pp_bcs_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE payroll_payments ADD CONSTRAINT fk_pp_pp_user FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE payroll_payments ADD CONSTRAINT fk_pp_pp_by FOREIGN KEY (created_by) REFERENCES users(id);
ALTER TABLE audit_log ADD CONSTRAINT fk_pp_al_actor FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL;

SET FOREIGN_KEY_CHECKS = 1;
