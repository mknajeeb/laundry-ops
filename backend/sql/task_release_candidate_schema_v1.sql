-- Task Management release-candidate schema notes.
-- The application applies these changes idempotently from ensure_* on first use
-- of the management schema helpers, or from backend/scripts/prepare_task_management_schema.py.
-- Do not run this file against production until a deployment is authorized.
-- Do not backfill participation_sessions_json or personal acknowledgments.
-- NULL participation_sessions_json means the historical started_at, ended_at, and duration_seconds remain the record.
-- Existing shared sessions with no cleaning_task_shared_item_checks rows stay one-check.

ALTER TABLE cleaning_task_activities
  ADD COLUMN participation_sessions_json TEXT NULL;

ALTER TABLE cleaning_task_shared_sessions
  ADD COLUMN participation_adjustments_json TEXT NULL;

ALTER TABLE cleaning_task_shared_session_items
  ADD COLUMN acknowledgment_mode VARCHAR(16) NULL;

ALTER TABLE task_activity_groups
  ADD COLUMN archived TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE task_activity_group_items
  ADD COLUMN acknowledgment_mode VARCHAR(16) NOT NULL DEFAULT 'any',
  ADD COLUMN verification_inherits TINYINT(1) NOT NULL DEFAULT 1,
  ADD COLUMN verification_required TINYINT(1) NULL,
  ADD COLUMN verification_method VARCHAR(32) NULL,
  ADD COLUMN verification_timing VARCHAR(32) NULL,
  ADD COLUMN verifier_config_json TEXT NULL;

-- cleaning_task_shared_item_checks is created with CREATE TABLE IF NOT EXISTS.
-- It is not a second acknowledgment system. Sessions that already have check rows keep them.
-- Rollback: these columns and the check table are additive. Older application code ignores unknown nullable columns.
-- Do not drop them after activity rows have been written.
