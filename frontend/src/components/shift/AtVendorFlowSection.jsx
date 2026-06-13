import { Alert, Box, Typography } from "@mui/material";
import DrilldownCardGrid from "./DrilldownCardGrid";
import RushFilterChips from "./RushFilterChips";
import ServiceFilterChips from "./ServiceFilterChips";

/** Hierarchical At Vendor daily workload flow (mobile-first). */
export default function AtVendorFlowSection({
  module,
  rushFilter,
  serviceFilter,
  onRushChange,
  onServiceChange,
  onDrilldown,
  activeTag,
}) {
  const av = module || {};
  const cards = av.cards || [];
  const monitoringCount = av.completed_before_day_start_still_present_count ?? 0;
  const dailyReliable = av.daily_metrics_reliable !== false;

  const level1 = cards.filter((c) => c.level === 1);
  const level2 = cards.filter((c) => c.level === 2);
  const level3 = cards.filter((c) => c.level === 3);
  const monitoring = cards.filter((c) => c.level === "monitoring");

  const showLevel2 = rushFilter && rushFilter !== "all";
  const showLevel3 = showLevel2 || (serviceFilter && serviceFilter !== "all");

  const visibleCards = [
    ...level1,
    ...(showLevel2
      ? level2.filter((c) => {
          if (rushFilter === "rush") return c.module_tag?.includes("rush") && !c.module_tag?.includes("non");
          if (rushFilter === "non_rush") return c.module_tag?.includes("non_rush");
          return true;
        })
      : []),
    ...(showLevel3
      ? level3.filter((c) => {
          if (serviceFilter === "wf") return c.module_tag?.includes("wf");
          if (serviceFilter === "hd") return c.module_tag?.includes("hd");
          return true;
        })
      : []),
  ];

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
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Daily Workload = Pending + Completed Today
        {av.daily_workload_total != null ? ` · ${av.daily_workload_total}` : ""}
      </Typography>
      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
          Rush
        </Typography>
        <RushFilterChips value={rushFilter} onChange={onRushChange} />
      </Box>
      {showLevel2 ? (
        <Box sx={{ mb: 1 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
            Service
          </Typography>
          <ServiceFilterChips value={serviceFilter} onChange={onServiceChange} />
        </Box>
      ) : null}
      <DrilldownCardGrid
        cards={visibleCards}
        onDrilldown={onDrilldown}
        activeTag={activeTag}
        rushFilter={rushFilter}
      />
      {monitoring.length > 0 || monitoringCount > 0 ? (
        <Box sx={{ mt: 1.5, pt: 1, borderTop: "1px dashed", borderColor: "divider" }}>
          <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.5 }}>
            Monitoring only — not included in Daily Workload
          </Typography>
          <DrilldownCardGrid
            cards={monitoring}
            onDrilldown={onDrilldown}
            activeTag={activeTag}
            compact
          />
        </Box>
      ) : null}
    </Box>
  );
}
