import { Box } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";

/** Visual tokens for Management → Performance (presentation only). */
export const PERF_UI = {
  pageBg: VEEWASH_DASHBOARD.pageBackground,
  contentTint: VEEWASH_DASHBOARD.primaryBlueLight,
  rowBg: VEEWASH_DASHBOARD.snapshotBg,
  rowBorder: VEEWASH_DASHBOARD.snapshotBorder,
  kpiBg: "rgba(0, 151, 178, 0.06)",
  kpiBorder: "rgba(0, 151, 178, 0.1)",
  segmentTrack: "rgba(0, 151, 178, 0.08)",
  segmentInactive: "rgba(30, 58, 74, 0.68)",
  navy: "#2a4552",
  secondary: "#5f7380",
  muted: "#8fa3ad",
  teal: VEEWASH_DASHBOARD.primaryBlue,
  tealDark: VEEWASH_DASHBOARD.primaryBlueDark,
  hdTeal: VEEWASH_DASHBOARD.hdTeal,
  separator: "rgba(100, 130, 145, 0.32)",
};

export const PERF_TYPE = {
  pageTitle: {
    fontSize: { xs: 18, sm: 20, md: 21 },
    fontWeight: 500,
    color: PERF_UI.navy,
    lineHeight: 1.15,
    letterSpacing: "-0.01em",
  },
  kpi: { fontSize: 12.5, fontWeight: 400, color: PERF_UI.secondary, lineHeight: 1.4 },
  kpiAccent: { fontWeight: 500, color: PERF_UI.tealDark },
  kpiValue: { fontWeight: 400, color: PERF_UI.navy },
  name: { fontSize: 13, fontWeight: 500, color: PERF_UI.navy, lineHeight: 1.25 },
  rank: { fontSize: 11.5, fontWeight: 400, color: PERF_UI.teal, lineHeight: 1.25 },
  metricPrimary: { fontSize: 13.5, fontWeight: 500, color: PERF_UI.tealDark, lineHeight: 1.2 },
  metricLabel: { fontSize: 10.5, fontWeight: 400, color: PERF_UI.muted },
  body: { fontSize: 12.5, fontWeight: 400, color: PERF_UI.secondary, lineHeight: 1.35 },
  meta: { fontSize: 11.5, fontWeight: 400, color: PERF_UI.muted, lineHeight: 1.35 },
  link: { fontSize: 12, fontWeight: 500, color: PERF_UI.tealDark },
  filter: { fontSize: 11, fontWeight: 500 },
  filterActive: { fontWeight: 500 },
};

export function PerfSeparator({ char = "|" }) {
  return (
    <Box
      component="span"
      sx={{
        mx: 0.55,
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
    px: { xs: 0.85, sm: 1, md: 1.05 },
    py: { xs: 0.55, sm: 0.45, md: 0.4 },
    borderRadius: 1,
    bgcolor: PERF_UI.rowBg,
    border: `1px solid ${PERF_UI.rowBorder}`,
    ...extra,
  };
}

export function perfKpiStripSx(extra = {}) {
  return {
    mb: 0.75,
    px: { xs: 0.85, sm: 1, md: 1.05 },
    py: { xs: 0.45, sm: 0.4 },
    borderRadius: 1,
    bgcolor: PERF_UI.kpiBg,
    border: `1px solid ${PERF_UI.kpiBorder}`,
    ...extra,
  };
}
