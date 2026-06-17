import { Box, Typography } from "@mui/material";
import { formatEtDateTime } from "../../utils/shiftMonitorHelpers";

function fmt(iso) {
  if (!iso) return "—";
  return formatEtDateTime(iso);
}

/** Portal snapshot freshness — which Vendor Home pull the counts are based on. */
export default function PortalSnapshotFreshness({ freshness, legacyScrapeAt }) {
  const f = freshness || {};
  const hasBlock = f.portal_pulled_at || f.data_updated_at || f.scrape_started_at || legacyScrapeAt;
  if (!hasBlock) return null;

  const pulled = f.portal_pull_unavailable
    ? fmt(f.scrape_started_at || f.data_updated_at || legacyScrapeAt)
    : fmt(f.portal_pulled_at || legacyScrapeAt);
  const updated = fmt(f.data_updated_at || legacyScrapeAt);
  const duration = f.duration_label || (f.duration_seconds != null ? `${f.duration_seconds}s` : null);
  const rows = f.rows_found;

  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="caption" color="text.secondary" display="block">
        Portal snapshot based on presence run{f.presence_run_id ? ` #${f.presence_run_id}` : ""}.
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        Scrape started: {fmt(f.scrape_started_at)} · Portal data pulled: {pulled}
        {f.portal_pull_unavailable ? " (Portal pull time unavailable — using started/updated fallback)" : ""}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        Data updated: {updated}
        {duration ? ` · Duration: ${duration}` : ""}
        {rows != null ? ` · Rows found: ${rows}` : ""}
      </Typography>
    </Box>
  );
}
