import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Drawer,
  IconButton,
  Paper,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import LiveBaselineBanner from "../components/shift/LiveBaselineBanner";
import SyncStatusSection from "../components/shift/SyncStatusSection";
import AtVendorFlowSection from "../components/shift/AtVendorFlowSection";
import EmployeeProductivityDashboard from "../components/shift/EmployeeProductivityDashboard";
import ShiftMonitorDateBar from "../components/shift/ShiftMonitorDateBar";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import { getFoldingPerformanceDetail, getRinseScheduledScrapeStatus, getShiftAnalysisSimple, runRinseBothSyncs } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import ShiftBagRecordRow from "../components/shift/ShiftBagRecordRow";
import BagWeightSummary from "../components/shift/BagWeightSummary";
import { RushPendingWhyPanel } from "../components/shift/RushPendingWhyPanel";
import VeeWashLogo from "../components/VeeWashLogo";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import {
  filterAtVendorDrilldown,
  filterModuleRecords,
  filterRfvRecords,
  formatShiftDateLabel,
  isOperationsMode as checkOperationsMode,
  isReportingMode as checkReportingMode,
  sortDrilldownRowsByDue,
  summarizeDrilldownEdd,
  formatDueDateRow,
  formatLastActivityRow,
  formatRushAuditRow,
  formatRecordReason,
  formatEtDateTime,
} from "../utils/shiftMonitorHelpers";

const SYNC_POLL_INTERVAL_MS = 10000;
const SYNC_POLL_MAX_MS = 1800000;

async function pollUntilSchedulerSyncComplete() {
  const started = Date.now();
  while (Date.now() - started < SYNC_POLL_MAX_MS) {
    await new Promise((resolve) => setTimeout(resolve, SYNC_POLL_INTERVAL_MS));
    const st = await getRinseScheduledScrapeStatus();
    if (!st.data?.currently_running) {
      return st.data;
    }
  }
  throw new Error("Sync timed out waiting for scheduler job");
}

const WORKLOAD_BASELINE_AUDIT_NOTE =
  "Historical workload uses clean baseline reset from Jun 12, 2026 11:20 PM ET. Legacy carry-in bags before reset are excluded.";

function MonitorNav() {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
      {[
        ["/performance/scan-chronology", "Scan Chronology"],
        ["/performance/operations-timeline", "Operations Timeline"],
        ["/performance/settings", "Settings"],
        ["/performance/user-mapping", "User mapping"],
        ["/performance/backfill", "Historical Repair / Admin Tools"],
      ].map(([to, label]) => (
        <Button key={to} size="small" component={RouterLink} to={to} sx={{ textTransform: "none", fontWeight: 600 }}>
          {label}
        </Button>
      ))}
    </Stack>
  );
}

function RfvRecordRow({ row }) {
  return (
    <Paper elevation={0} sx={{ p: 1.5, mb: 1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Typography variant="subtitle2" fontWeight={800}>
        {row.bag_id}
      </Typography>
      <Typography variant="body2" color="primary.main" fontWeight={600}>
        {row.customer_name || "—"}
      </Typography>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        Estimated delivery: {row.estimated_delivery_raw || "—"}
      </Typography>
      <Typography variant="body2">
        EDD (ET): {row.estimated_delivery_date_et || "—"}
      </Typography>
      <Typography variant="body2">
        TODAY label: {row.has_today_label ? "yes" : "no"}
      </Typography>
      <Typography variant="body2" fontWeight={700} sx={{ mt: 0.5 }}>
        {row.rush_label || row.rush_bucket || "—"} · {row.service_bucket || row.service_type || "—"}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        {row.reason || row.source}
      </Typography>
    </Paper>
  );
}

function AtVendorRecordRow({ row, changedRushDrilldown = false }) {
  const rushLabel = row.rush_label
    || (row.rush_bucket === "RUSH" ? "Rush" : row.rush_bucket === "NON_RUSH" ? "Non-Rush" : "Unknown Review");
  const serviceLabel = row.service_bucket || row.service_type || "—";
  const statusLabel = row.at_vendor_status || (row.facility_status
    ? row.facility_status.charAt(0).toUpperCase() + row.facility_status.slice(1)
    : "—");
  const reason = row.changed_to_rush_reason || row.status_reason || row.reason || row.rush_reason || "—";

  return (
    <Paper elevation={0} sx={{ p: 1.5, mb: 1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Typography variant="subtitle2" fontWeight={800}>
        {row.bag_id}
      </Typography>
      <Typography variant="body2" color="primary.main" fontWeight={600}>
        {row.customer_name || row.customer || "—"}
      </Typography>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        Service type: {serviceLabel}
      </Typography>
      <Typography variant="body2">
        Rush / Non-Rush: {rushLabel}
      </Typography>
      <Typography variant="body2">
        Estimated delivery date: {row.estimated_delivery_date || row.date_clean || "—"}
      </Typography>
      <Typography variant="body2">
        TODAY label: {row.today_label || (row.has_today_label ? "yes" : "no")}
      </Typography>
      <Typography variant="body2">
        sent-to-vendor time: {row.sent_to_vendor_time_et || formatEtDateTime(row.sent_to_vendor_time) || "—"}
      </Typography>
      {!changedRushDrilldown ? (
        <>
          <Typography variant="body2">
            Completion signal: {row.completion_signal || "—"}
          </Typography>
          {row.completion_time_et ? (
            <Typography variant="body2" color="text.secondary">
              Completed at: {row.completion_time_et}
            </Typography>
          ) : null}
        </>
      ) : null}
      <Typography variant="body2" fontWeight={700} sx={{ mt: 0.5 }}>
        Status: {statusLabel}
      </Typography>
      {changedRushDrilldown ? (
        <>
          {row.previous_edd ? (
            <Typography variant="body2">
              Previous EDD: {row.previous_edd}
            </Typography>
          ) : null}
          <Typography variant="body2">
            Current rush bucket: {rushLabel}
          </Typography>
          {row.previous_rush_bucket ? (
            <Typography variant="body2">
              Previous rush bucket: {row.previous_rush_bucket === "RUSH" ? "Rush" : row.previous_rush_bucket === "NON_RUSH" ? "Non-Rush" : row.previous_rush_bucket}
            </Typography>
          ) : null}
          <Typography variant="body2">
            Selected ET date: {row.selected_date_et || "—"}
          </Typography>
        </>
      ) : null}
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        Reason: {reason}
      </Typography>
    </Paper>
  );
}

function RecordRow({ row, expanded, onToggle }) {
  const wd = row.weight_difference || {};
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  useEffect(() => {
    if (!expanded) {
      setDetail(null);
      setDetailError(null);
      return undefined;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    getFoldingPerformanceDetail(row.bag_id)
      .then((res) => {
        if (!cancelled) setDetail(res.data);
      })
      .catch((e) => {
        if (!cancelled) {
          setDetail(null);
          setDetailError(e?.response?.data?.error || "Could not load scan events");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [expanded, row.bag_id]);

  const perf = detail?.performance;
  const scanEvents = detail?.scan_events || [];
  const hasSpecial =
    row.special_instructions_raw || row.supply_interpretation || row.special_instruction_review;

  return (
    <Paper elevation={0} sx={{ p: 1.5, mb: 1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" onClick={onToggle} sx={{ cursor: "pointer" }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" fontWeight={800}>
            {row.bag_id}
          </Typography>
          <Typography variant="body2" color="primary.main" fontWeight={600}>
            {row.customer_name || row.customer || "—"}
          </Typography>
          <Typography variant="body2" color="primary.main" fontWeight={700} sx={{ mt: 0.5 }}>
            {formatDueDateRow(row)}
          </Typography>
          <Typography variant="body2" fontWeight={700} sx={{ mt: 0.5 }}>
            {formatLastActivityRow(row)}
          </Typography>
          {row.last_activity_purpose || row.last_scan_purpose ? (
            <Typography variant="body2" color="text.secondary" fontWeight={600}>
              {row.last_activity_purpose || row.last_scan_purpose}
            </Typography>
          ) : null}
          {(row.snapshot_bucket_reason || row.wip_bucket_reason || row.due_today_bucket_reason || row.scan_dts_bucket_reason || row.vendor_home_bucket_reason || row.baseline_inclusion_reason) ? (
            <Typography variant="body2" color="text.secondary" fontWeight={600} sx={{ mt: 0.75 }}>
              Reason: {formatRecordReason(row)}
            </Typography>
          ) : null}
          {row.source_seen_in?.length ? (
            <Typography variant="body2" color="text.secondary" fontWeight={600} sx={{ mt: 0.5 }}>
              Source: {row.source_seen_in.join(", ")}
            </Typography>
          ) : null}
          <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
            <Chip size="small" label={row.rush_bucket === "RUSH" ? "Rush" : row.rush_bucket === "NON_RUSH" ? "Non-Rush" : row.computed_rush_label || row.rush_label || "—"} />
            <Chip size="small" label={row.service_bucket || row.service_type || "WF"} variant="outlined" />
            {row.needs_review ? <Chip size="small" color="warning" label="Review" /> : null}
          </Stack>
          <BagWeightSummary row={row} />
          {formatRushAuditRow(row) ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              {formatRushAuditRow(row)}
            </Typography>
          ) : null}
          {hasSpecial ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              {row.special_instructions_raw || "—"}
              {row.supply_interpretation ? ` · ${row.supply_interpretation}` : ""}
              {row.special_instruction_review ? " · Review flagged" : ""}
            </Typography>
          ) : null}
        </Box>
        <Box textAlign="right" sx={{ minWidth: 120 }}>
          <Typography variant="body2" fontWeight={700}>
            {row.current_stage || row.current_status || "—"}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.employee || row.last_activity_user || "—"}
          </Typography>
        </Box>
      </Stack>
      <Collapse in={expanded}>
        <Box sx={{ mt: 1.5, pt: 1.5, borderTop: "1px dashed", borderColor: "divider" }}>
          <Typography variant="caption" fontWeight={700} display="block">
            Special instructions
          </Typography>
          <Typography variant="caption" display="block">
            Raw: {row.special_instructions_raw || "—"}
          </Typography>
          <Typography variant="caption" display="block">
            Supply: {row.supply_interpretation || "—"}
          </Typography>
          <Typography variant="caption" display="block">
            Review: {row.special_instruction_review ? "Yes" : "No"}
          </Typography>
          <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
            Employee: {row.employee || "—"}
          </Typography>
          <Typography variant="caption" display="block">
            Flags: {(row.flags || []).join(", ") || "—"}
          </Typography>
          {wd.flagged ? (
            <Typography variant="caption" display="block" color="warning.main">
              Weight Δ {wd.difference_lbs} lbs (threshold {wd.threshold_lbs})
            </Typography>
          ) : null}
          {(wd.first_weight_lbs != null || wd.second_weight_lbs != null || wd.unavailable_reason) && (
            <Box sx={{ mt: 0.5 }}>
              <Typography variant="caption" display="block" fontWeight={700}>
                Weight difference
              </Typography>
              <Typography variant="caption" display="block">
                First: {wd.first_weight_lbs ?? "—"} lbs · {formatDateTime(wd.first_weight_at)} · {wd.first_weight_user || "—"}
              </Typography>
              <Typography variant="caption" display="block">
                Second: {wd.second_weight_lbs ?? "—"} lbs · {formatDateTime(wd.second_weight_at)} · {wd.second_weight_user || "—"}
              </Typography>
              <Typography variant="caption" display="block">
                Difference: {wd.difference_lbs ?? "—"} · Threshold: {wd.threshold_lbs ?? "—"}
              </Typography>
              {wd.unavailable_reason ? (
                <Typography variant="caption" color="text.secondary" display="block">
                  {wd.unavailable_reason}
                </Typography>
              ) : null}
            </Box>
          )}
          {(row.activities || []).map((a) => (
            <Typography key={`${a.role}-${a.activity_at}`} variant="caption" display="block">
              {a.role}: {a.employee || "—"} @ {formatDateTime(a.activity_at)}
            </Typography>
          ))}
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="caption" fontWeight={700} display="block">
              Folding / scan timeline
              {row.scan_event_count != null ? ` (${row.scan_event_count} events)` : ""}
            </Typography>
            {detailLoading ? (
              <Typography variant="caption" color="text.secondary">Loading events…</Typography>
            ) : detailError ? (
              <Typography variant="caption" color="error.main">{detailError}</Typography>
            ) : (
              <>
                {perf ? (
                  <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>
                    Folder: {perf.assigned_user_name || "—"}
                    {perf.duration_seconds != null ? ` · ${formatFoldingDuration(perf.duration_seconds)}` : ""}
                    {perf.status ? ` · ${perf.status}` : ""}
                  </Typography>
                ) : detail?.folding_not_computed ? (
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                    Folding not computed yet (bag still in progress or no FOLDING→CLEAN interval).
                  </Typography>
                ) : null}
                <FoldingScanEventsTable events={scanEvents} collapseUploadDuplicates />
              </>
            )}
          </Box>
          {row.facility_entered_date ? (
            <Typography variant="caption" display="block">
              Entered: {row.facility_entered_date}
              {row.facility_status ? ` · ${row.facility_status.replace(/_/g, " ")}` : ""}
              {row.facility_left_sent ? " · Left/Sent" : ""}
              {row.facility_still_at_facility ? " · Still at facility" : ""}
            </Typography>
          ) : null}
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {row.source}
          </Typography>
        </Box>
      </Collapse>
    </Paper>
  );
}

export default function ShiftMonitorPage({ user }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [syncRunning, setSyncRunning] = useState(false);
  const syncTimerRef = useRef(null);
  const [drilldown, setDrilldown] = useState(null);
  const [moduleFilters, setModuleFilters] = useState({
    facility_status: { rush: "all", service: "all" },
    production_stage: { rush: "all", service: "all" },
    exceptions: { rush: "all", service: "all" },
    monitor: { rush: "all", service: "all" },
  });
  const [avRushFilter, setAvRushFilter] = useState("all");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dueSortEnabled, setDueSortEnabled] = useState(true);
  const initialToday = todayRange();
  const [rangePreset, setRangePreset] = useState(() => {
    const ds = searchParams.get("date_start");
    return ds ? "custom" : "today";
  });
  const [dateStart, setDateStart] = useState(() => searchParams.get("date_start") || initialToday.start);
  const [dateEnd, setDateEnd] = useState(() => searchParams.get("date_end") || initialToday.end);
  const [dataRefreshKey, setDataRefreshKey] = useState(0);

  useEffect(() => () => {
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getShiftAnalysisSimple({
        date_start: dateStart,
        date_end: dateEnd,
        summary_only: 1,
      });
      setData(res.data || null);
      setDataRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load shift monitor");
    } finally {
      setLoading(false);
    }
  }, [dateStart, dateEnd]);

  useEffect(() => {
    load();
  }, [load]);

  const atVendorModule = data?.at_vendor_module || {};
  const rfv = data?.ready_for_vendor || {};
  const records = data?.records || [];

  const filtered = useMemo(() => {
    if (!drilldown) return [];
    let rows = [];
    if (drilldown.type === "rfv") {
      rows = filterRfvRecords(rfv.rows || [], drilldown.drilldownTag, "all");
    } else if (drilldown.moduleKey === "at_vendor_flow") {
      rows = filterAtVendorDrilldown(atVendorModule, drilldown, {
        referenceDateEt: dateEnd || dateStart,
      });
    } else {
      const f = moduleFilters[drilldown.moduleKey] || { rush: "all", service: "all" };
      rows = filterModuleRecords(records, {
        moduleTag: drilldown.moduleTag,
        rushFilter: f.rush,
        serviceFilter: f.service,
      });
    }
    const referenceDateEt = dateEnd || dateStart;
    if (
      dueSortEnabled
      && referenceDateEt
      && (drilldown.type === "rfv" || drilldown.moduleKey === "at_vendor_flow")
    ) {
      return sortDrilldownRowsByDue(rows, referenceDateEt);
    }
    return rows;
  }, [records, atVendorModule, drilldown, moduleFilters, rfv.rows, dateEnd, dateStart, dueSortEnabled]);

  const drilldownEddSummary = useMemo(() => {
    if (!drilldown || (drilldown.type !== "rfv" && drilldown.moduleKey !== "at_vendor_flow")) {
      return null;
    }
    return summarizeDrilldownEdd(filtered, dateEnd || dateStart);
  }, [filtered, drilldown, dateEnd, dateStart]);

  const expectedDrilldownCount = useMemo(() => {
    if (!drilldown?.expectedCount && drilldown?.expectedCount !== 0) return null;
    return drilldown.expectedCount;
  }, [drilldown]);

  const showRushPendingWhyInDrawer = useMemo(() => {
    if (drilldown?.moduleKey !== "at_vendor_flow") return false;
    const bucket = drilldown?.bucket;
    if (bucket?.status === "pending" && bucket?.rush === "rush") return true;
    return false;
  }, [drilldown]);

  const runRinseSync = async () => {
    setSyncRunning(true);
    setSyncMessage("");
    try {
      const res = await runRinseBothSyncs({ dry_run: false });
      const overall = res.data?.overall_status || "success";

      if (overall === "queued" || res.status === 202) {
        setSyncMessage(
          res.data?.message
            || "Scheduler job started — dashboard will refresh when the sync cycle completes.",
        );
        await pollUntilSchedulerSyncComplete();
        setSyncMessage("Scheduler sync finished — dashboard refreshed.");
        await load();
        return;
      }

      const av = res.data?.at_vendor_sync || {};
      const rfv = res.data?.ready_for_vendor_sync || {};
      const rfvEnabled = rfv.enabled !== false && rfv.status !== "disabled" && !String(rfv.skipped_reason || "").includes("RFV_SCRAPE_ENABLED");
      const rfvDetail = (() => {
        if (!rfvEnabled) return null;
        if (rfv.skipped_reason || rfv.status === "disabled") {
          return `Ready for Vendor skipped: ${rfv.skipped_reason || "feature flag disabled"}`;
        }
        if (rfv.status === "failed") {
          return `Ready for Vendor failed: ${rfv.error_message || "unknown error"}`;
        }
        if (rfv.status === "success" && Number(rfv.rows_found) === 0) {
          const emptyValidated =
            rfv.empty_result_validated === true || rfv.stats?.empty_result_validated === true;
          if (emptyValidated) {
            return "Ready for Vendor queue validated empty.";
          }
          return "Ready for Vendor returned 0 rows but was not validated; previous RFV population was preserved.";
        }
        if (rfv.status === "success") {
          return `Ready for Vendor success: ${rfv.rows_found ?? 0} rows, ${rfv.active_rows ?? 0} active`;
        }
        return `Ready for Vendor: ${rfv.status || "—"}`;
      })();
      setSyncMessage(
        rfvDetail
          ? (overall === "partial_success"
            ? `At Vendor: ${av.status || "—"} · ${rfvDetail} (partial success)`
            : `Both syncs finished — At Vendor: ${av.status || "—"} · ${rfvDetail}`)
          : `Portal sync finished — At Vendor: ${av.status || "—"}`,
      );
      await load();
    } catch (e) {
      const errData = e?.response?.data;
      if (errData?.overall_status === "ALREADY_RUNNING" || e?.response?.status === 409) {
        setSyncMessage(errData?.message || "A sync is already running — wait for it to finish.");
        await load();
      } else if (errData?.overall_status === "partial_success" || e?.response?.status === 207) {
        setSyncMessage(
          `Partial success — At Vendor: ${errData?.at_vendor_sync?.status || "ok"} · ${
            errData?.ready_for_vendor_sync?.error_message
              ? `Ready for Vendor failed: ${errData.ready_for_vendor_sync.error_message}`
              : errData?.ready_for_vendor_sync?.skipped_reason
                ? `Ready for Vendor skipped: ${errData.ready_for_vendor_sync.skipped_reason}`
                : `Ready for Vendor: ${errData?.ready_for_vendor_sync?.status || "failed"}`
          }`,
        );
        await load();
      } else {
        setSyncMessage(
          errData?.message
            || errData?.error
            || errData?.ready_for_vendor_sync?.error_message
            || e?.message
            || "Refresh Both Syncs failed",
        );
      }
    } finally {
      setSyncRunning(false);
    }
  };

  const rfvSync = data?.rinse_sync?.ready_for_vendor || rfv.sync_status || {};
  const pipeline = data?.current_work_pipeline || data?.current_active_work_now || data?.current_active_work || {};
  const avSync = data?.rinse_sync?.at_vendor || pipeline.sync_status || {};
  const perfMeta = data?.performance_meta;
  const readyForVendorEnabled = Boolean(data?.rinse_sync?.ready_for_vendor_enabled);

  const syncCycle = data?.rinse_sync?.sync_cycle || {};
  const operationsMode = checkOperationsMode(dateStart, dateEnd);
  const singleDaySelected = Boolean(dateStart && dateEnd && dateStart === dateEnd);
  const employeeProductivity = atVendorModule?.employee_completed_bags_today;
  const reportingMode = checkReportingMode(dateStart, dateEnd);

  return (
    <Box sx={{ p: { xs: 1.25, md: 2.5 }, maxWidth: 960, mx: "auto", pb: 6, bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh" }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={1}
        sx={{ mb: 1.5, position: "sticky", top: 0, zIndex: 10, bgcolor: VEEWASH_DASHBOARD.pageBackground, py: 0.75 }}
      >
        <Stack direction="row" spacing={1.25} alignItems="center">
          <VeeWashLogo height={40} />
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="h5" fontWeight={900} sx={{ fontSize: "1.35rem" }}>
                Shift Monitor
              </Typography>
              <Chip
                label={operationsMode ? "Operations" : "Reporting"}
                size="small"
                sx={{
                  height: 22,
                  fontWeight: 700,
                  fontSize: "0.6875rem",
                  bgcolor: operationsMode ? VEEWASH_DASHBOARD.primaryBlue : "transparent",
                  color: operationsMode ? "#fff" : VEEWASH_DASHBOARD.primaryBlueDark,
                  border: "1px solid",
                  borderColor: operationsMode ? VEEWASH_DASHBOARD.primaryBlue : VEEWASH_DASHBOARD.primaryBlueBorder,
                }}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.8125rem" }}>
              {formatShiftDateLabel(dateStart, dateEnd)}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              New York time (ET)
            </Typography>
          </Box>
        </Stack>
        <MonitorNav />
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1.5 }} flexWrap="wrap">
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <ShiftMonitorDateBar
            preset={rangePreset}
            onPresetChange={setRangePreset}
            dateStart={dateStart}
            dateEnd={dateEnd}
            onDateStartChange={(v) => {
              setRangePreset("custom");
              setDateStart(v);
            }}
            onDateEndChange={(v) => {
              setRangePreset("custom");
              setDateEnd(v);
            }}
            loading={loading}
          />
        </Box>
        {rangePreset === "custom" ? (
          <Button variant="contained" size="small" onClick={load} disabled={loading} sx={{ textTransform: "none", fontWeight: 700, px: 2 }}>
            Apply
          </Button>
        ) : null}
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {syncMessage ? <Alert severity="info" sx={{ mb: 2 }}>{syncMessage}</Alert> : null}
      {loading && !data ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}

      {data ? (
        <>
          {reportingMode ? (
            <Alert
              severity="info"
              variant="outlined"
              sx={{
                mb: 1.5,
                py: 0.5,
                bgcolor: "#fff",
                borderColor: VEEWASH_DASHBOARD.snapshotBorder,
                "& .MuiAlert-message": { width: "100%" },
              }}
            >
              <Typography variant="body2" fontWeight={600}>
                Reporting Mode
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                Workload summary and breakdowns only — live portal, monitoring, RFV, sync, and pipeline are hidden.
              </Typography>
              {atVendorModule?.uses_clean_veewash_baseline ? (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5, fontStyle: "italic" }}>
                  {WORKLOAD_BASELINE_AUDIT_NOTE}
                </Typography>
              ) : null}
            </Alert>
          ) : null}

          {operationsMode ? (
            <SyncStatusSection
              avSync={avSync}
              rfvSync={rfvSync}
              rfv={rfv}
              syncCycle={syncCycle}
              syncRunning={syncRunning}
              loading={loading}
              onRefresh={runRinseSync}
              readyForVendorEnabled={readyForVendorEnabled}
            />
          ) : null}

          {operationsMode ? (
            <Typography variant="overline" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlueDark} sx={{ mb: 1, display: "block", letterSpacing: 1.2 }}>
              Live Operations
            </Typography>
          ) : null}

          <AtVendorFlowSection
            module={atVendorModule}
            rushFilter={avRushFilter}
            onRushChange={setAvRushFilter}
            onDrilldown={(ctx) => {
              setDrilldown(ctx);
              setDrawerOpen(true);
            }}
            activeKey={drilldown?.moduleKey === "at_vendor_flow" ? drilldown.cardKey : null}
            isOperationsMode={operationsMode}
            selectedDateEt={dateEnd || dateStart}
            onCompletionReviewChanged={load}
          />

          {singleDaySelected ? (
            <EmployeeProductivityDashboard
              key={`${dateEnd || dateStart}-${avRushFilter}`}
              initialSection={employeeProductivity}
              initialDateEt={dateEnd || dateStart}
              rushFilter={avRushFilter}
              refreshToken={dataRefreshKey}
              onRushChange={setAvRushFilter}
            />
          ) : null}

          {operationsMode ? <LiveBaselineBanner baseline={data?.live_baseline} /> : null}

          {perfMeta ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              Loaded in {Math.round(perfMeta.total_build_ms)}ms ·{" "}
              {Math.round((perfMeta.payload_size_bytes || 0) / 1024)} KB
              {perfMeta.summary_only ? " (summary)" : ""}
            </Typography>
          ) : null}
        </>
      ) : null}

      <Drawer
        anchor="bottom"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{
          sx: {
            height: { xs: "100%", sm: "75vh" },
            maxHeight: { xs: "100%", sm: "75vh" },
            borderTopLeftRadius: { xs: 0, sm: 16 },
            borderTopRightRadius: { xs: 0, sm: 16 },
            p: { xs: 1.5, sm: 2 },
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1, flexShrink: 0 }} flexWrap="wrap" gap={1}>
          <Box sx={{ minWidth: 0, pr: 1, flex: 1 }}>
            <Typography variant="h6" fontWeight={800} sx={{ wordBreak: "break-word" }}>
              {drilldown?.moduleTitle || "Records"} — {drilldown?.cardLabel || ""}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block">
              {filtered.length} record{filtered.length === 1 ? "" : "s"}
              {expectedDrilldownCount != null && expectedDrilldownCount !== filtered.length
                ? ` · expected ${expectedDrilldownCount}`
                : ""}
              {drilldownEddSummary?.missing > 0
                ? ` · ${drilldownEddSummary.missing} missing EDD`
                : ""}
            </Typography>
          </Box>
          {(drilldown?.type === "rfv" || drilldown?.moduleKey === "at_vendor_flow") ? (
            <FormControlLabel
              control={(
                <Switch
                  size="small"
                  checked={dueSortEnabled}
                  onChange={(e) => setDueSortEnabled(e.target.checked)}
                />
              )}
              label={<Typography variant="caption">Sort by due date</Typography>}
              sx={{ mr: 0 }}
            />
          ) : null}
          <IconButton onClick={() => setDrawerOpen(false)} aria-label="Close" sx={{ flexShrink: 0 }}>
            <CloseIcon />
          </IconButton>
        </Stack>
        {showRushPendingWhyInDrawer ? (
          <Box sx={{ mb: 1, flexShrink: 0 }}>
            <RushPendingWhyPanel summary={atVendorModule?.rush_pending_why_summary} />
          </Box>
        ) : null}
        <Box sx={{ overflow: "auto", flex: 1, minHeight: 0 }}>
          {drilldown?.type === "rfv"
            ? filtered.map((row) => (
              <ShiftBagRecordRow
                key={row.bag_id}
                row={row}
                variant="rfv"
                referenceDateEt={dateEnd || dateStart}
              />
            ))
            : drilldown?.moduleKey === "at_vendor_flow"
              ? filtered.map((row) => (
                <ShiftBagRecordRow
                  key={row.bag_id}
                  row={row}
                  variant="at_vendor"
                  referenceDateEt={dateEnd || dateStart}
                />
              ))
              : filtered.map((row) => (
                <RecordRow
                  key={row.bag_id}
                  row={row}
                  expanded={false}
                  onToggle={() => {}}
                />
              ))}
          {filtered.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No records for this bucket.</Typography>
          ) : null}
        </Box>
      </Drawer>
    </Box>
  );
}
