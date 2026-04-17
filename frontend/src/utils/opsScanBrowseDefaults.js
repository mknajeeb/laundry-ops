/**
 * Scan vs browse-list defaults from tenant maintenance (`ops_ui` on bootstrap).
 *
 * - If only scan is allowed → scan on, browse off.
 * - If only browse is allowed → browse on, scan off.
 * - If both are allowed → scan on, browse off (scan is the default mode).
 * - If neither → both off.
 *
 * @param {object | undefined} opsUi — from AuthContext; when undefined, treats both flags as on (matches API default until bootstrap).
 */
export function scanBrowseDefaultsFromOpsUi(opsUi) {
  const o = opsUi || {};
  const ms = o.scan_lookup_enabled !== false;
  const mb = o.browse_list_enabled !== false;
  if (!ms && !mb) return { scan: false, browse: false };
  if (ms && !mb) return { scan: true, browse: false };
  if (!ms && mb) return { scan: false, browse: true };
  return { scan: true, browse: false };
}
