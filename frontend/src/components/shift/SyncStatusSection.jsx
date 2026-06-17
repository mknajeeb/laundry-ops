import { Alert, Box, Collapse, Typography } from "@mui/material";
import { useState } from "react";
import ShiftCountCard from "./ShiftCountCard";
import { SyncCycleFreshnessSummary } from "./SyncCycleFreshnessSummary";
import { syncStatusSubtext } from "../../utils/shiftMonitorHelpers";

export default function SyncStatusSection({
  avSync,
  rfvSync,
  rfv,
  syncCycle,
  syncRunning,
  loading,
  onRefresh,
}) {
  const [open, setOpen] = useState(false);
  const rfvSyncSub = syncStatusSubtext(
    { sync_status: rfvSync, last_refreshed_at: rfv?.last_refreshed_at },
    "Ready for Vendor Sync",
  );
  const avSyncSub = syncStatusSubtext({ sync_status: avSync }, "At Vendor Sync");
  const avWarn = avSync?.failed || avSync?.stale;
  const rfvWarn =
    (rfvSync?.failed || rfvSync?.latest_failed || (rfvSync?.stale && !rfv?.zero_rows_success))
    && !rfv?.zero_rows_success;
  const cycle = syncCycle || {};
  const misleadingCronSkip =
    cycle.sync_cycle_id == null &&
    (cycle.cycle_status === "skipped" ||
      cycle.at_vendor_skipped_reason === "ALREADY_RUNNING" ||
      cycle.failure_message === "ALREADY_RUNNING");
  let cycleStatusMain = cycle.cycle_status || "—";
  let cycleStatusSuffix = cycle.at_vendor_ran === false ? " · At Vendor did not run" : "";
  if (misleadingCronSkip) {
    const rfvEt = rfvSync?.last_success_at_et || rfvSync?.last_refreshed_at_et;
    const avEt = avSync?.last_refreshed_at_et || cycle.at_vendor_completed_at_et;
    if (rfvEt || avEt) {
      cycleStatusMain = "—";
      cycleStatusSuffix = ` · latest completed RFV ${rfvEt || "—"} · AV ${avEt || "—"}`;
    } else {
      cycleStatusMain = "—";
      cycleStatusSuffix = " · no completed cycle on latest cron tick";
    }
  }
  const cycleWarn =
    !misleadingCronSkip &&
    (cycle.cycle_status === "failed" || cycle.cycle_status === "partial_success");
  const avScanRows = avSync?.scan_events_count ?? avSync?.freshness?.scan_events_count;
  const avPortalRows = avSync?.rows_found ?? avSync?.freshness?.rows_found;
  const avBatchId = avSync?.imported_batch_id ?? avSync?.freshness?.imported_batch_id;

  return (
    <Box sx={{ mb: 2 }}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 1,
          mb: 0.75,
        }}
      >
        <Typography
          variant="subtitle1"
          fontWeight={800}
          onClick={() => setOpen((v) => !v)}
          sx={{ cursor: "pointer", userSelect: "none" }}
        >
          {cycle.label || "Last Rinse Sync Cycle"} {open ? "▾" : "▸"}
        </Typography>
        <Box component="button" type="button" onClick={onRefresh} disabled={syncRunning || loading} sx={{
          border: "1px solid",
          borderColor: "divider",
          borderRadius: 1,
          px: 1.5,
          py: 0.75,
          fontSize: 13,
          fontWeight: 600,
          bgcolor: "background.paper",
          cursor: syncRunning || loading ? "not-allowed" : "pointer",
        }}
        >
          {syncRunning ? "Refreshing…" : "Refresh Both Syncs"}
        </Box>
      </Box>
      <Collapse in={open}>
        {cycleWarn ? (
          <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
            Cycle status: {cycle.cycle_status || "unknown"}
            {cycle.at_vendor_skipped_reason ? ` · At Vendor skipped: ${cycle.at_vendor_skipped_reason}` : ""}
          </Alert>
        ) : null}
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
            gap: 1,
            mb: 1,
          }}
        >
          <ShiftCountCard
            label="Ready for Vendor"
            value={rfvSync?.freshness?.portal_pulled_at_et || cycle.rfv_completed_at_et || "—"}
            sub={rfvSyncSub}
            warn={rfvWarn}
            compact
          />
          <ShiftCountCard
            label="At Vendor"
            value={avSync?.freshness?.portal_pulled_at_et || cycle.at_vendor_completed_at_et || avSync.last_refreshed_at_et || "—"}
            sub={
              cycle.delay_seconds != null
                ? `${avSyncSub} · delay ${cycle.delay_seconds}s`
                : avSyncSub
            }
            warn={avWarn}
            compact
          />
        </Box>
        <SyncCycleFreshnessSummary cycle={cycle} avSync={avSync} rfvSync={rfvSync} />
        <Alert severity="info" variant="outlined" sx={{ mb: 1, py: 0.75 }}>
          <Typography variant="caption" display="block" sx={{ lineHeight: 1.45 }}>
            Sync time is when the last Rinse export finished — not when every floor scan happened.
            {avPortalRows != null || avScanRows != null ? (
              <>
                {" "}
                Latest export: {avPortalRows ?? "—"} portal bag{avPortalRows === 1 ? "" : "s"}
                {avScanRows != null ? ` · ${avScanRows} scan-event row${avScanRows === 1 ? "" : "s"}` : ""}
                {avBatchId != null ? ` · batch ${avBatchId}` : ""}.
              </>
            ) : null}
            {" "}
            Pending bags can still show missing scans until those scans appear in the next Rinse export.
            Use <strong>Refresh Both Syncs</strong> after new scans on the floor.
          </Typography>
        </Alert>
        <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-word" }}>
          Status: {cycleStatusMain}
          {cycleStatusSuffix}
        </Typography>
      </Collapse>
    </Box>
  );
}
