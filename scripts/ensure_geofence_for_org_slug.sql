-- =============================================================================
-- Ensure at least one ACTIVE geofence exists for a tenant (fixes clock-in when
-- the API returns "No geofence available" / no fallback geofence for the org).
--
-- Run in MySQL Workbench against production `laundryapp` if needed:
--   USE laundryapp;
--
-- Then set @slug to your tenant (default: veewash), execute the whole script.
-- After insert, open the admin UI and EDIT lat/lng/radius to the real work site.
-- =============================================================================

SET NAMES utf8mb4;

SET @slug = 'veewash';

SELECT id INTO @oid FROM organizations WHERE slug = @slug LIMIT 1;

SELECT COUNT(*) INTO @n
FROM geofences
WHERE organization_id = COALESCE(@oid, -1) AND active = 1;

INSERT INTO geofences (
  organization_id,
  name,
  location_description,
  latitude,
  longitude,
  radius_meters,
  active
)
SELECT
  @oid,
  'Primary work site',
  'Placeholder coordinates — update in admin geofence settings to your facility GPS.',
  40.7127760,
  -74.0059740,
  300,
  1
WHERE @oid IS NOT NULL
  AND @n = 0;

SELECT
  @slug AS tenant_slug,
  @oid AS organization_id,
  @n AS active_geofences_before,
  (SELECT COUNT(*) FROM geofences WHERE organization_id = @oid AND active = 1) AS active_geofences_after;
