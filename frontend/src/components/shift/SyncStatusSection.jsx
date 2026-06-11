import { Box, Button, Stack, Typography } from "@mui/material";
import ShiftCountCard from "./ShiftCountCard";
import { syncStatusSubtext } from "../../utils/shiftMonitorHelpers";

export default function SyncStatusSection({
  avSync,
  rfvSync,
  rfv,
  syncRunning,
  loading,
  onRefresh,
}) {
  const rfvSyncSub = syncStatusSubtext(
    { sync_status: rfvSync, last_refreshed_at: rfv?.last_refreshed_at },
    "Ready for Vendor Sync",
  );
  const avSyncSub = syncStatusSubtext({ sync_status: avSync }, "At Vendor Sync");
  const avWarn = avSync?.failed || avSync?.stale;
  const rfvWarn =
    (rfvSync?.failed || rfvSync?.latest_failed || (rfvSync?.stale && !rfv?.zero_rows_success))
    && !rfv?.zero_rows_success;

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1} sx={{ mb: 0.75 }}>
        <Typography variant="subtitle1" fontWeight={800}>
          Sync Status
        </Typography>
        <Button variant="outlined" size="small" onClick={onRefresh} disabled={syncRunning || loading}>
          {syncRunning ? "Refreshing…" : "Refresh Both Syncs"}
        </Button>
      </Stack>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
          gap: 1,
        }}
      >
        <ShiftCountCard
          label="At Vendor Sync"
          value={avSync.last_refreshed_at_et || avSync.message || "—"}
          sub={avSyncSub}
          warn={avWarn}
          compact
        />
        <ShiftCountCard
          label="Ready for Vendor Sync"
          value={rfvSync.last_refreshed_at_et || rfvSync.message || rfvSync.last_success_at_et || "—"}
          sub={rfv?.zero_rows_success ? "0 rows — success" : rfvSyncSub}
          warn={rfvWarn}
          compact
        />
      </Box>
    </Box>
  );
}
