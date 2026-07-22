-- Additional Step-1 / Review Required drawer indexes (idempotent).
-- Existing coverage:
--   rinse_shift_monitor_days: UNIQUE (organization_id, shift_date_et)
--   rinse_shift_monitor_day_bags: UNIQUE (organization_id, shift_date_et, bag_id)
--     + KEY (organization_id, shift_date_et, effective_status)
--   rinse_bag_scan_events: KEY (organization_id, bag_id)
--     + KEY (organization_id, bag_id, scanned_at_parsed, scan_index)

SET @db := DATABASE();

-- Day-bag lookup by bag across dates
SET @ix := (
  SELECT COUNT(1) FROM information_schema.statistics
  WHERE table_schema = @db
    AND table_name = 'rinse_shift_monitor_day_bags'
    AND index_name = 'idx_shift_monitor_day_bag_org_bag'
);
SET @sql := IF(
  @ix = 0,
  'CREATE INDEX idx_shift_monitor_day_bag_org_bag ON rinse_shift_monitor_day_bags (organization_id, bag_id, shift_date_et)',
  'SELECT ''skip idx_shift_monitor_day_bag_org_bag'' AS _note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Status drill-down without forcing org prefix first (covering helper)
SET @ix := (
  SELECT COUNT(1) FROM information_schema.statistics
  WHERE table_schema = @db
    AND table_name = 'rinse_shift_monitor_day_bags'
    AND index_name = 'idx_shift_monitor_day_bag_date_status'
);
SET @sql := IF(
  @ix = 0,
  'CREATE INDEX idx_shift_monitor_day_bag_date_status ON rinse_shift_monitor_day_bags (shift_date_et, effective_status)',
  'SELECT ''skip idx_shift_monitor_day_bag_date_status'' AS _note'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
