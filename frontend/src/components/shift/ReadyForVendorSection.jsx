import { Alert, Box, Chip, Stack, Typography } from "@mui/material";
import ShiftCountCard from "./ShiftCountCard";
import DrilldownCardGrid from "./DrilldownCardGrid";
import RushFilterChips from "./RushFilterChips";
import { formatDateTime } from "../../utils/foldingFormat";
import { syncStatusSubtext } from "../../utils/shiftMonitorHelpers";

export default function ReadyForVendorSection({
  rfv,
  rfvLive,
  rfvSync,
  rfvSyncSub,
  rfvSyncStale,
  rushFilter,
  onRushFilterChange,
  onDrilldown,
  activeTag,
}) {
  const syncSub = rfvSyncSub || syncStatusSubtext({ sync_status: rfvSync, last_refreshed_at: rfv?.last_refreshed_at }, "Ready for Vendor Sync");
  const cards = rfv?.cards;

  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            Ready for Vendor
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Live queue from Ready for Vendor sync — selected ET date rush rules apply
          </Typography>
        </Box>
        {rfvLive && rfv.parity_ok !== false && rfv.counts_add_up ? (
          <Chip size="small" color="success" variant="outlined" label="Reconciled ✓" />
        ) : rfvLive ? (
          <Chip size="small" color="warning" label="Needs Review" />
        ) : null}
      </Stack>

      {!rfvLive ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {rfv?.unavailable_reason || "Ready for Vendor: Sync stale"}
          {rfv?.last_refreshed_at ? ` · Last refresh: ${formatDateTime(rfv.last_refreshed_at)}` : ""}
        </Alert>
      ) : rfv.data_quality_warning ? (
        <Alert severity={rfv.zero_rows_success ? "info" : "error"} sx={{ mb: 1.5 }}>
          {rfv.data_quality_warning}
        </Alert>
      ) : rfvSyncStale ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>{syncSub}</Alert>
      ) : null}

      {rfvLive ? <RushFilterChips value={rushFilter} onChange={onRushFilterChange} sx={{ mb: 1 }} /> : null}

      {rfvLive && cards?.length ? (
        <DrilldownCardGrid cards={cards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} compact={false} />
      ) : rfvLive ? (
        <ShiftCountCard label="Ready for Vendor" value={rfv.total ?? "—"} sub={syncSub} onClick={() => onDrilldown("ready_for_vendor")} active={activeTag === "ready_for_vendor"} />
      ) : (
        <ShiftCountCard label="Ready for Vendor" value="—" sub={rfv?.unavailable_reason || syncSub || "Refresh Both Syncs"} />
      )}
    </Box>
  );
}
