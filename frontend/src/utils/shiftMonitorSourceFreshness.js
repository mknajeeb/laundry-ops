import { formatFriendlyEtWall } from "./rinseTimeFormat";

/**
 * Operator-facing Shift Monitor source freshness caption.
 * Watermark = MIN(portal_through, scan_through); never Stage-B calc time alone.
 */
export function sourceFreshnessCaption(dataFreshness, day = {}) {
  const df = dataFreshness || {};
  const available =
    df.source_freshness_available === true
    && df.operator_data_current_through_et;
  if (!available) {
    return {
      label: "Data freshness unavailable",
      tooltip: null,
      available: false,
    };
  }
  const calculated =
    df.calculated_at_et || day?.step1_refreshed_at || day?.last_sync_at || null;
  const tipLines = [
    df.portal_data_through_et
      ? `Portal: ${formatFriendlyEtWall(df.portal_data_through_et)}`
      : null,
    df.scan_data_through_et
      ? `Scans: ${formatFriendlyEtWall(df.scan_data_through_et)}`
      : null,
    calculated ? `Calculated: ${formatFriendlyEtWall(calculated)}` : null,
  ].filter(Boolean);
  return {
    label: `Data current through: ${formatFriendlyEtWall(df.operator_data_current_through_et)}`,
    tooltip: tipLines.length ? tipLines.join("\n") : null,
    available: true,
  };
}
