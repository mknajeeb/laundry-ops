-- Inspect persisted Rinse scan events for one bag (ET timeline, audit fields).
-- Usage: set @org_id and @bag_id, then run in MySQL.

SET @org_id = 3;
SET @bag_id = '5LCZ5RJ60E';

SELECT
    id,
    bag_id,
    scan_index,
    rack,
    user_name,
    purpose,
    time_scanned_raw,
    scanned_at_parsed,
    source_timezone,
    dedupe_key,
    source_upload_batch_id,
    created_at,
    updated_at,
    last_seen_at
FROM rinse_bag_scan_events
WHERE organization_id = @org_id
  AND bag_id = @bag_id
ORDER BY scanned_at_parsed ASC, scan_index ASC, id ASC;
