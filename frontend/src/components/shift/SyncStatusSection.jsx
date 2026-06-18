import { Alert, Box, Collapse, Typography } from "@mui/material";
import { useState } from "react";
import ShiftCountCard from "./ShiftCountCard";
import { SyncCycleFreshnessSummary } from "./SyncCycleFreshnessSummary";
import { syncStatusSubtext } from "../../utils/shiftMonitorHelpers";

function TargetedRefreshSummary({ targeted }) {
  const t = targeted || {};
  const hasActivity =
    t.targeted_refresh_ran
    || t.skipped_reason
    || t.bag_ids_requested?.length
    || t.bags?.length
    || t.error;
  if (!hasActivity) return null;
  const failed = t.lookup_failed_bag_ids || [];
  const considered = t.targeted_bags_considered ?? t.bag_ids_requested?.length ?? 0;
  const imported = t.missing_scans_imported ?? t.events_inserted;
  const completed = t.bags_completed_after_refresh;
  const refreshed = t.targeted_bags_refreshed ?? t.bags_processed;
  const lookupFailed = t.lookup_failures ?? t.lookup_failed;
  return (
    <Box sx={{ mb: 1, p: 1.25, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.35 }}>
        Targeted refresh (direct ?q=BAGID)
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5, lineHeight: 1.45 }}>
        Pending workload bags missing from the latest portal crawl — including off-portal bags.
      </Typography>
      {t.skipped_reason ? (
        <Typography variant="caption" color="text.secondary" display="block">
          Skipped: {t.skipped_reason}
        </Typography>
      ) : (
        <Typography variant="caption" display="block">
          Pending bags checked: {considered}
          {refreshed != null ? ` · bags refreshed: ${refreshed}` : ""}
          {imported != null ? ` · scans imported: ${imported}` : ""}
          {completed != null ? ` · completed after refresh: ${completed}` : ""}
          {lookupFailed != null ? ` · lookup failed: ${lookupFailed}` : ""}
          {t.crawl_batch_id != null ? ` · crawl batch ${t.crawl_batch_id}` : ""}
        </Typography>
      )}
      {failed.length ? (
        <Typography variant="caption" color="error.main" display="block" sx={{ mt: 0.35 }}>
          Direct lookup failed: {failed.join(", ")}
        </Typography>
      ) : null}
      {t.error ? (
        <Typography variant="caption" color="error.main" display="block" sx={{ mt: 0.35 }}>
          {t.error}
        </Typography>
      ) : null}
    </Box>
  );
}

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
  const targeted = cycle.targeted_pending_scan_refresh || {};
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
      cycleStatusSuffix = ` · latest completed RFV ${rfvEt || "—"} · portal crawl ${avEt || "—"}`;
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
  const portalCrawlEt =
    avSync?.freshness?.portal_pulled_at_et
    || cycle.at_vendor_completed_at_et
    || avSync?.last_refreshed_at_et
    || "—";

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
        <Box
          component="button"
          type="button"
          onClick={onRefresh}
          disabled={syncRunning || loading}
          sx={{
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
            label="Last portal crawl"
            value={portalCrawlEt}
            sub={
              [
                avPortalRows != null ? `${avPortalRows} Vendor Home bag${avPortalRows === 1 ? "" : "s"}` : null,
                avScanRows != null ? `${avScanRows} scan row${avScanRows === 1 ? "" : "s"}` : null,
                avBatchId != null ? `batch ${avBatchId}` : null,
                cycle.delay_seconds != null ? `delay ${cycle.delay_seconds}s` : null,
              ].filter(Boolean).join(" · ") || avSyncSub
            }
            warn={avWarn}
            compact
          />
        </Box>
        <SyncCycleFreshnessSummary cycle={cycle} avSync={avSync} rfvSync={rfvSync} />
        <TargetedRefreshSummary targeted={targeted} />
        <Alert severity="info" variant="outlined" sx={{ mb: 1, py: 0.75 }}>
          <Typography variant="caption" display="block" sx={{ lineHeight: 1.45 }}>
            <strong>Last portal crawl</strong> imports scans only for bags on the current Vendor Home page.
            {" "}
            <strong>Targeted refresh</strong> runs direct ?q=BAGID lookup for pending Today&apos;s Workload bags
            missing from that crawl (including off-portal).
            {" "}
            Workload scans are current only after <strong>both</strong> steps succeed.
            Manual Refresh Both Syncs runs portal crawl then targeted refresh.
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
