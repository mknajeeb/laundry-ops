-- Additive chronology watermark (independent of management publish).
-- Safe to re-run.

SET @col_exists := (
  SELECT COUNT(1)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'rinse_freshness_watermarks'
    AND column_name = 'chronology_processed_through'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE rinse_freshness_watermarks ADD COLUMN chronology_processed_through DATETIME(6) NULL AFTER canonical_processed_through',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
