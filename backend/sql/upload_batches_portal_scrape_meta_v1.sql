-- Portal scrape stop metadata (scrape.mjs) for full_snapshot guard.

SET @t = 'upload_batches';
SET @c = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = @t AND COLUMN_NAME = 'portal_scrape_meta'
);
SET @sql = IF(
  @c = 0,
  'ALTER TABLE upload_batches ADD COLUMN portal_scrape_meta JSON NULL COMMENT ''Portal scrape stop metadata from scrape.mjs''',
  'SELECT ''skip: upload_batches.portal_scrape_meta exists'' AS migration_note'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
