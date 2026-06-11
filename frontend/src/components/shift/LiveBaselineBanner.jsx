import { Box, Typography } from "@mui/material";

export default function LiveBaselineBanner({ baseline }) {
  if (!baseline?.active && baseline?.shift_monitor_baseline_start_at_et == null) return null;

  const needsRefresh = baseline.needs_refresh || !baseline.at_vendor_scrape_ready;

  return (
    <Box
      sx={{
        mb: 1.5,
        px: 1.25,
        py: 0.75,
        borderRadius: 1,
        border: "1px solid",
        borderColor: needsRefresh ? "warning.main" : "info.main",
        bgcolor: needsRefresh ? "warning.50" : "action.hover",
      }}
    >
      <Typography variant="caption" fontWeight={700} display="block">
        {baseline.banner_title || "Live Baseline active"}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        {baseline.banner_subtitle || "Using latest post-baseline scrape and scans"}
      </Typography>
    </Box>
  );
}
