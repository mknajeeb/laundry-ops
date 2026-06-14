import { Stack, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/** Optional historical report insight chips — presentation only. */
export default function WorkloadReportStats({ stats }) {
  if (!stats) return null;
  const items = [
    { label: "Completed", value: `${stats.completedPct}%`, color: VEEWASH_DASHBOARD.teal },
    { label: "Rush", value: `${stats.rushPct}%`, color: VEEWASH_DASHBOARD.pending },
    { label: "HD", value: `${stats.hdPct}%`, color: VEEWASH_DASHBOARD.primaryBlueDark },
  ];
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
      {items.map(({ label, value, color }) => (
        <Stack key={label} direction="row" spacing={0.75} alignItems="baseline">
          <Typography variant="caption" color="text.secondary" fontWeight={600}>
            {label}
          </Typography>
          <Typography variant="body2" fontWeight={800} sx={{ color }}>
            {value}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
