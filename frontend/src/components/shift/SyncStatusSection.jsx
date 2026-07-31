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
          Error: {t.error}
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
  readyForVendorEnabled = false,
}) {
  const [open, setOpen] = useState(false);
  const rfvActive = Boolean(readyForVendorEnabled && rfvSync?.enabled !== false);
  const rfvSyncSub = syncStatusSubtext(
    { sync_status: rfvSync, last_refreshed_at: rfv?.last_refreshed_at },
    "Ready for Vendor Sync",
  );
  const avSyncSub = syncStatusSubtext({ sync_status: avSync }, "At Vendor Sync");
  const avWarn = avSync?.failed || avSync?.stale;
  const rfvWarn =
    rfvActive
    && (rfvSync?.failed || rfvSync?.latest_failed || (rfvSync?.stale && !rfv?.zero_rows_success))
    && !rfv?.zero_rows_success;
  const cycle = syncCycle || {};
  const completed = cycle.latest_completed_cycle || null;
  const attempt = cycle.latest_attempt || avSync?.latest_attempt || null;
  const targeted =
    cycle.targeted_pending_scan_refresh
    || completed?.targeted_refresh
    || {};
  const hasCompletedCycle = Boolean(
    completed?.run_id
    || cycle.sync_cycle_id
    || cycle.at_vendor_completed_at
    || cycle.at_vendor_completed_at_et
  );
  const tipSkippedAlreadyRunning =
    attempt?.status === "skipped"
    && String(attempt?.skip_reason || "").toUpperCase() === "ALREADY_RUNNING";

  let cycleStatusMain = cycle.cycle_status || (hasCompletedCycle ? "success" : "—");
  let cycleStatusSuffix = cycle.at_vendor_ran === false ? " · At Vendor did not run" : "";
  if (!hasCompletedCycle) {
    cycleStatusMain = "—";
    cycleStatusSuffix = tipSkippedAlreadyRunning
      ? " · no completed cycle yet"
      : "";
  }
  const cycleWarn =
    hasCompletedCycle
    && (cycle.cycle_status === "failed" || cycle.cycle_status === "partial_success");
  const inspectOnlyWarn =
    cycle.cycle_status === "inspect_only" || Boolean(cycle.sync_warning || cycle.failure_message?.includes("no credible supply"));
  const gateWarning =
    cycle.sync_warning
    || (inspectOnlyWarn ? cycle.failure_message : null);
  const avScanRows = avSync?.scan_events_count ?? avSync?.freshness?.scan_events_count;
  const avPortalRows = avSync?.rows_found ?? avSync?.freshness?.rows_found;
  const avBatchId =
    avSync?.imported_batch_id
    ?? avSync?.freshness?.imported_batch_id
    ?? completed?.scan_import_batch_id;
  const portalCrawlEt =
    avSync?.freshness?.portal_pulled_at_et
    || cycle.at_vendor_completed_at_et
    || avSync?.last_refreshed_at_et
    || (hasCompletedCycle ? (completed?.finished_at || "—") : "—");
  const skipInfoMessage =
    cycle.latest_attempt_message
    || (tipSkippedAlreadyRunning && hasCompletedCycle
      ? `${attempt?.started_at_et || "Latest"} run skipped because the previous sync was still running.`
      : null);

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
          {syncRunning
            ? "Refreshing…"
            : (rfvActive ? "Refresh Both Syncs" : "Refresh Portal Sync")}
        </Box>
      </Box>
      <Collapse in={open}>
        {gateWarning ? (
          <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
            {gateWarning}
          </Alert>
        ) : null}
        {cycleWarn ? (
          <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
            Cycle status: {cycle.cycle_status || "unknown"}
            {cycle.at_vendor_skipped_reason ? ` · At Vendor skipped: ${cycle.at_vendor_skipped_reason}` : ""}
          </Alert>
        ) : null}
        {skipInfoMessage ? (
          <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>
            {skipInfoMessage}
          </Alert>
        ) : null}
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: rfvActive ? "repeat(2, 1fr)" : "1fr",
            },
            gap: 1,
            mb: 1,
          }}
        >
          {rfvActive ? (
            <ShiftCountCard
              label="Ready for Vendor"
              value={rfvSync?.freshness?.portal_pulled_at_et || cycle.rfv_completed_at_et || "—"}
              sub={rfvSyncSub}
              warn={rfvWarn}
              compact
            />
          ) : null}
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
        <SyncCycleFreshnessSummary
          cycle={cycle}
          avSync={avSync}
          rfvSync={rfvActive ? rfvSync : null}
          showRfv={rfvActive}
        />
        <TargetedRefreshSummary targeted={targeted} />
        <Alert severity="info" variant="outlined" sx={{ mb: 1, py: 0.75 }}>
          <Typography variant="caption" display="block" sx={{ lineHeight: 1.45 }}>
            <strong>Last portal crawl</strong> imports scans only for bags on the current Vendor Home page.
            {" "}
            <strong>Targeted refresh</strong> runs direct ?q=BAGID lookup for pending Today&apos;s Workload bags
            missing from that crawl (including off-portal).
            {" "}
            Workload scans are current only after <strong>both</strong> steps succeed.
            {rfvActive
              ? " Manual Refresh Both Syncs runs portal crawl then targeted refresh."
              : " Manual Refresh Portal Sync runs portal crawl then targeted refresh."}
          </Typography>
        </Alert>
        <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-word" }}>
          Status: {cycleStatusMain}
          {cycleStatusSuffix}
          {completed?.step1?.status
            ? ` · Step-1 ${completed.step1.status}`
            : (cycle.step1_day_refresh?.step1_refresh_status
              ? ` · Step-1 ${cycle.step1_day_refresh.step1_refresh_status}`
              : "")}
        </Typography>
      </Collapse>
    </Box>
  );
}
