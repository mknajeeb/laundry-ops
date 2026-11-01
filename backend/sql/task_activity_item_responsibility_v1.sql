-- Additive item responsibility for existing activity groups.
-- Defaults keep current groups as Anyone on Team.
-- Does not rewrite completed check-off rows.
-- Not applied by this file alone; ensure_* in task_activity_item_responsibility.py
-- applies the same changes idempotently at runtime.

ALTER TABLE task_activity_group_items
  ADD COLUMN responsibility_mode VARCHAR(16) NOT NULL DEFAULT 'team',
  ADD COLUMN responsibility_user_ids_json TEXT NULL,
  ADD COLUMN section_label VARCHAR(80) NULL,
  ADD COLUMN section_order INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS task_activity_item_date_overrides (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  group_item_id INT NOT NULL,
  business_date DATE NOT NULL,
  responsibility_mode VARCHAR(16) NOT NULL,
  user_ids_json TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_taido_item_date (group_item_id, business_date),
  INDEX idx_taido_org_date (organization_id, business_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE cleaning_task_shared_session_items
  ADD COLUMN responsibility_snapshot_json TEXT NULL;

ALTER TABLE cleaning_task_activity_items
  ADD COLUMN responsibility_snapshot_json TEXT NULL;
