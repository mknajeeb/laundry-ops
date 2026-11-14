-- Day-range Scan Chronology reads filter and order by organization + scan time.
-- Measured on production org 3, 2026-11-12 (read-only, index NOT applied):
--   WHERE organization_id = ? AND scanned_at_parsed >= ? AND scanned_at_parsed < ?
--   ORDER BY scanned_at_parsed, scan_index, id
-- EXPLAIN uses uq_rbse_org_bag_dedupe, type ref, ~180,710 rows,
-- Extra "Using where" plus "Using filesort". The day returned 5,544 rows in 39.5s.
-- Existing keys start with (organization_id, bag_id, ...), including
-- idx_rbse_org_bag_time, so none can range-scan the day. This index matches
-- that predicate. A local table with the same cardinality used the new index
-- as a range of 5,544 rows and dropped the filesort. Do not infer production
-- milliseconds from that local timing.
--
-- Column types (rinse_bag_scan_events):
--   organization_id INT NOT NULL
--   scanned_at_parsed DATETIME NULL
--   scan_index INT NULL
--   id INT NOT NULL (PRIMARY KEY)
--
-- Do not apply to production until a separate deploy authorization.
-- Additive only. Safe to re-run: the procedure skips an existing key.

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'rinse_bag_scan_events'
    AND index_name = 'idx_rbse_org_scanned_at'
);
SET @ddl := IF(
  @idx_exists = 0,
  'ALTER TABLE rinse_bag_scan_events ADD INDEX idx_rbse_org_scanned_at (organization_id, scanned_at_parsed, scan_index, id), ALGORITHM=INPLACE, LOCK=NONE',
  'SELECT ''idx_rbse_org_scanned_at already present'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
