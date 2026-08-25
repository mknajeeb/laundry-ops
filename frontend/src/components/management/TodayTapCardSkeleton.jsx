import { Box, Skeleton } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/** VeeWash-branded KPI card placeholder — matches TodayTapCard footprint. */
export default function TodayTapCardSkeleton({ tone = "workload" }) {
  const accent =
    tone === "completed"
      ? VEEWASH_DASHBOARD.tealBorder
      : tone === "pending"
        ? VEEWASH_DASHBOARD.pendingBorder
        : tone === "review"
          ? "rgba(185, 28, 28, 0.25)"
          : VEEWASH_DASHBOARD.wfBorder;

  return (
    <Box
      sx={{
        px: 1,
        py: 0.85,
        minHeight: 56,
        borderRadius: 1.5,
        border: "1px solid",
        borderColor: accent,
        bgcolor: "#fff",
      }}
      data-testid={`wf-kpi-skeleton-${tone}`}
    >
      <Skeleton
        variant="text"
        width="55%"
        height={28}
        sx={{ bgcolor: "rgba(15, 23, 42, 0.06)", borderRadius: 0.75 }}
      />
      <Skeleton
        variant="text"
        width="40%"
        height={14}
        sx={{ mt: 0.35, bgcolor: "rgba(100, 116, 139, 0.1)", borderRadius: 0.5 }}
      />
    </Box>
  );
}
