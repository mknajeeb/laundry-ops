import { Box } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";

/** Visual tokens for Management → Performance (presentation only). */
export const PERF_UI = {
  pageBg: "#e8f0f3",
  contentTint: "rgba(255, 255, 255, 0.45)",
  rowBg: "rgba(255, 255, 255, 0.78)",
  rowBorder: "rgba(0, 151, 178, 0.1)",
  kpiBg: "rgba(0, 151, 178, 0.07)",
  kpiBorder: "rgba(0, 151, 178, 0.12)",
  segmentTrack: "rgba(0, 151, 178, 0.1)",
  segmentInactive: "rgba(30, 58, 74, 0.72)",
  navy: "#1e3a4a",
  secondary: "#5c7280",
  muted: "#8fa3ad",
  teal: VEEWASH_DASHBOARD.primaryBlue,
  tealDark: VEEWASH_DASHBOARD.primaryBlueDark,
  hdTeal: VEEWASH_DASHBOARD.hdTeal,
  separator: "rgba(100, 130, 145, 0.35)",
};

export const PERF_TYPE = {
  pageTitle: { fontSize: { xs: 20, sm: 22 }, fontWeight: 600, color: PERF_UI.navy, lineHeight: 1.15 },
  kpi: { fontSize: 13, fontWeight: 400, color: PERF_UI.secondary, lineHeight: 1.45 },
  kpiAccent: { fontWeight: 600, color: PERF_UI.tealDark },
  kpiValue: { fontWeight: 500, color: PERF_UI.navy },
  name: { fontSize: 14, fontWeight: 600, color: PERF_UI.navy, lineHeight: 1.25 },
  rank: { fontSize: 12, fontWeight: 500, color: PERF_UI.teal, lineHeight: 1.25 },
  metricPrimary: { fontSize: 15, fontWeight: 600, color: PERF_UI.tealDark, lineHeight: 1.2 },
  metricLabel: { fontSize: 11, fontWeight: 400, color: PERF_UI.muted },
  body: { fontSize: 13, fontWeight: 400, color: PERF_UI.secondary, lineHeight: 1.35 },
  meta: { fontSize: 12, fontWeight: 400, color: PERF_UI.muted, lineHeight: 1.35 },
  link: { fontSize: 12, fontWeight: 500, color: PERF_UI.tealDark },
  filter: { fontSize: 11, fontWeight: 500 },
  filterActive: { fontWeight: 600 },
};

export function PerfSeparator({ char = "|" }) {
  return (
    <Box
      component="span"
      sx={{
        mx: 0.65,
        color: PERF_UI.separator,
        fontWeight: 300,
        userSelect: "none",
      }}
    >
      {char}
    </Box>
  );
}

export function perfRowSx(extra = {}) {
  return {
    px: { xs: 1, sm: 1.15 },
    py: { xs: 0.7, sm: 0.6 },
    borderRadius: 1.25,
    bgcolor: PERF_UI.rowBg,
    border: `1px solid ${PERF_UI.rowBorder}`,
    ...extra,
  };
}

export function perfKpiStripSx(extra = {}) {
  return {
    mb: 1,
    px: { xs: 1, sm: 1.15 },
    py: { xs: 0.55, sm: 0.5 },
    borderRadius: 1.25,
    bgcolor: PERF_UI.kpiBg,
    border: `1px solid ${PERF_UI.kpiBorder}`,
    ...extra,
  };
}
