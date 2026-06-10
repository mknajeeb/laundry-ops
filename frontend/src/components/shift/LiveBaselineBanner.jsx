import { Alert, Box, Typography } from "@mui/material";

export default function LiveBaselineBanner({ baseline }) {
  if (!baseline?.active && baseline?.shift_monitor_baseline_start_at_et == null) return null;

  const needsRefresh = baseline.needs_refresh || !baseline.at_vendor_scrape_ready;
  const severity = needsRefresh ? "warning" : "info";

  return (
    <Alert severity={severity} sx={{ mb: 2 }}>
      <Typography variant="subtitle2" fontWeight={800}>
        {baseline.banner_title || "Live Dashboard Baseline active"}
      </Typography>
      <Typography variant="body2" sx={{ mt: 0.25 }}>
        {baseline.banner_subtitle || "Using latest post-baseline Rinse scrape + post-baseline scans"}
      </Typography>
      {baseline.latest_at_vendor_scrape_after_baseline ? (
        <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.5 }}>
          Latest At Vendor scrape after baseline: {baseline.latest_at_vendor_scrape_after_baseline}
          {baseline.latest_rfv_scrape_after_baseline
            ? ` · RFV: ${baseline.latest_rfv_scrape_after_baseline}`
            : ""}
        </Typography>
      ) : null}
      <Typography variant="caption" display="block" color="text.secondary">
        {baseline.banner_footer || "Historical data kept for audit only"}
      </Typography>
      {baseline.baseline_note ? (
        <Box sx={{ mt: 0.75 }}>
          <Typography variant="caption" color="text.secondary">
            {baseline.baseline_note}
          </Typography>
        </Box>
      ) : null}
    </Alert>
  );
}
