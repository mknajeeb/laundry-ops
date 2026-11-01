-- Additive. Existing groups keep NULL instructions. Not applied in this change.
ALTER TABLE task_activity_groups
  ADD COLUMN instructions TEXT NULL;
