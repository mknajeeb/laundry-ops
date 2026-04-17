-- Draft batch row permissions (run on existing DBs; idempotent).
SET NAMES utf8mb4;

INSERT IGNORE INTO permissions (perm_key, description) VALUES
('upload.rows.edit', 'Edit draft upload batch rows (before confirm)'),
('upload.rows.delete', 'Delete draft upload batch rows (before confirm)');

UPDATE permissions SET
  route_key = 'upload', route_label = 'Upload', section_key = 'draft_rows', section_label = 'Draft batch rows',
  resource_key = '', resource_label = '', action_key = 'update', sort_order = 1325
WHERE perm_key = 'upload.rows.edit';
UPDATE permissions SET
  route_key = 'upload', route_label = 'Upload', section_key = 'draft_rows', section_label = 'Draft batch rows',
  resource_key = '', resource_label = '', action_key = 'delete', sort_order = 1326
WHERE perm_key = 'upload.rows.delete';

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE UPPER(TRIM(r.code)) IN ('ADMIN', 'SUPER_ADMIN', 'PLATFORM_ADMIN')
  AND p.perm_key IN ('upload.rows.edit', 'upload.rows.delete');
