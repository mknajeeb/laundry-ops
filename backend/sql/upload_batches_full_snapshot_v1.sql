-- Optional: mark whether a batch is a full portal export (for missing-from-portal completion).
-- When absent, confirms with accepted portal order rows are treated as full snapshot.

SET @t = 'upload_batches';
SET @c = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = @t AND COLUMN_NAME = 'full_snapshot'
);
SET @sql = IF(
  @c = 0,
  'ALTER TABLE upload_batches ADD COLUMN full_snapshot TINYINT(1) NOT NULL DEFAULT 1 COMMENT ''1=full portal CSV snapshot''',
  'SELECT ''skip: upload_batches.full_snapshot exists'' AS migration_note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
