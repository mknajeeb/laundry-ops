import { Alert, Box, Typography } from "@mui/material";
import MetricCardGrid from "./MetricCardGrid";
import RushFilterChips from "./RushFilterChips";
import SyncFreshnessDetails from "./SyncFreshnessDetails";
import { buildRfvHierarchy } from "../../utils/shiftMonitorHelpers";

/** Management-first Ready for Vendor hierarchy (totals only). */
export default function ReadyForVendorSection({
  rfv,
  rfvSync,
  rushFilter,
  onRushChange,
  onDrilldown,
  activeKey,
}) {
  const syncFailed = rfvSync?.failed || rfvSync?.latest_failed;
  const syncStale = rfvSync?.stale && !rfv?.zero_rows_success && !rfvSync?.zero_rows_success;
  const showWarning = !rfv?.live || syncFailed || syncStale;
  const segment = rushFilter || "all";
  const sections = buildRfvHierarchy(rfv, segment);

  const handleCardClick = (card) => {
    if (!onDrilldown || !card.drilldownTag) return;
    onDrilldown({
      drilldownTag: card.drilldownTag,
      cardLabel: card.label,
      cardKey: card.key,
      expectedCount: card.count,
      moduleTitle: "Ready for Vendor",
    });
  };

  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
        Ready for Vendor
      </Typography>
      {showWarning ? (
        <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
          {rfv?.unavailable_reason || rfvSync?.message || "Ready for Vendor sync unavailable — refresh syncs"}
        </Alert>
      ) : null}
      {rfvSync?.freshness ? (
        <Box sx={{ mb: 1.25, p: 1.25, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
            RFV sync freshness
          </Typography>
          <SyncFreshnessDetails freshness={rfvSync.freshness} />
        </Box>
      ) : null}
      <Box sx={{ mb: 1.5 }}>
        <RushFilterChips value={segment} onChange={onRushChange} />
      </Box>
      <MetricCardGrid
        sections={sections}
        onCardClick={handleCardClick}
        activeKey={activeKey}
      />
    </Box>
  );
}
