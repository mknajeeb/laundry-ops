import { Alert, Box, Typography } from "@mui/material";
import MetricCardGrid from "./MetricCardGrid";
import RushFilterChips from "./RushFilterChips";
import ShiftCountCard from "./ShiftCountCard";
import { buildAtVendorHierarchy } from "../../utils/shiftMonitorHelpers";

/** Management-first At Vendor daily workload hierarchy. */
export default function AtVendorFlowSection({
  module,
  rushFilter,
  onRushChange,
  onDrilldown,
  activeKey,
}) {
  const av = module || {};
  const monitoringCount = av.completed_before_day_start_still_present_count ?? 0;
  const monitoringRows = av.completed_before_day_start_still_present_rows || [];
  const dailyReliable = av.daily_metrics_reliable !== false;
  const segment = rushFilter || "all";

  const sections = buildAtVendorHierarchy(av, segment);

  const handleCardClick = (card) => {
    if (!onDrilldown) return;
    onDrilldown({
      moduleKey: "at_vendor_flow",
      moduleTag: card.moduleTag,
      bucket: card.bucket,
      cardLabel: card.label,
      cardKey: card.key,
      expectedCount: card.count,
      moduleTitle: "At Vendor",
    });
  };

  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
        At Vendor
      </Typography>
      {!dailyReliable && av.daily_metrics_ui_warning ? (
        <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
          {av.daily_metrics_ui_warning}
        </Alert>
      ) : null}
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Daily Workload = Pending + Completed Today
        {av.daily_workload_total != null ? ` · ${av.daily_workload_total}` : ""}
      </Typography>

      <Box sx={{ mb: 1.5 }}>
        <RushFilterChips value={segment} onChange={onRushChange} />
      </Box>

      <MetricCardGrid
        sections={sections}
        onCardClick={handleCardClick}
        activeKey={activeKey}
      />

      {monitoringCount > 0 ? (
        <Box sx={{ mt: 2, pt: 1.5, borderTop: "1px dashed", borderColor: "divider" }}>
          <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 1 }}>
            Monitoring only — excluded from Daily Workload
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Completed Earlier — Still at VeeWash
          </Typography>
          <Box sx={{ maxWidth: 320 }}>
            <ShiftCountCard
              label="Completed Earlier — Still at VeeWash"
              value={monitoringCount}
              sub={`${monitoringRows.length} record${monitoringRows.length === 1 ? "" : "s"}`}
              onClick={() => onDrilldown?.({
                moduleKey: "at_vendor_flow",
                moduleTag: "completed_before_day_start_still_present",
                cardLabel: "Completed Earlier — Still at VeeWash",
                cardKey: "av_monitoring",
                expectedCount: monitoringCount,
                moduleTitle: "At Vendor (Monitoring)",
              })}
              active={activeKey === "av_monitoring"}
            />
          </Box>
        </Box>
      ) : null}

      {av.changed_to_rush > 0 ? (
        <Box sx={{ mt: 1.5 }}>
          <ShiftCountCard
            label="Changed to Rush"
            value={av.changed_to_rush}
            onClick={() => onDrilldown?.({
              moduleKey: "at_vendor_flow",
              moduleTag: "mod_at_vendor_changed_rush",
              cardLabel: "Changed to Rush",
              cardKey: "av_changed_rush",
              expectedCount: av.changed_to_rush,
              moduleTitle: "At Vendor",
            })}
            active={activeKey === "av_changed_rush"}
            warn
          />
        </Box>
      ) : null}
    </Box>
  );
}
