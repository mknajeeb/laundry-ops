import { Box, Paper, Typography } from "@mui/material";
import SyncFreshnessDetails from "./SyncFreshnessDetails";

function SyncFreshnessCard({ title, freshness, warn = false }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.25,
        border: "1px solid",
        borderColor: warn ? "warning.main" : "divider",
        borderRadius: 2,
        bgcolor: warn ? "warning.50" : "background.paper",
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.5 }}>
        {title}
      </Typography>
      <SyncFreshnessDetails freshness={freshness} />
    </Paper>
  );
}

/** Last Rinse Sync Cycle — Pulled vs Updated per section. */
export function SyncCycleFreshnessSummary({ cycle, avSync, rfvSync }) {
  const avScanRows = avSync?.scan_events_count ?? avSync?.freshness?.scan_events_count;
  const avBatchId = avSync?.imported_batch_id ?? avSync?.freshness?.imported_batch_id;

  const avFreshness = {
    ...(avSync?.freshness || cycle?.at_vendor_scrape_freshness || cycle?.at_vendor_presence_freshness || {}),
    scan_events_count: avScanRows,
    imported_batch_id: avBatchId,
  };
  const rfvFreshness = rfvSync?.freshness || cycle?.rfv_freshness;

  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
        gap: 1,
        mb: 1,
      }}
    >
      <SyncFreshnessCard title="Ready for Vendor" freshness={rfvFreshness} warn={rfvSync?.stale || rfvSync?.failed} />
      <SyncFreshnessCard title="At Vendor" freshness={avFreshness} warn={avSync?.stale || avSync?.failed} />
    </Box>
  );
}
