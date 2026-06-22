-- Rinse partner login: read-only Weekly Schedule (Rinse Exclusive tab, current week onward).
-- Assign via People → user roles after running this migration.

SET NAMES utf8mb4;

INSERT IGNORE INTO roles (code, name, organization_id, is_system)
VALUES ('RINSE', 'Rinse schedule viewer', 0, 1);

SELECT 'rinse_schedule_viewer_role_v1 complete.' AS note;
