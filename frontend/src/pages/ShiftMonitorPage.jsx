import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Drawer,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CloseIcon from "@mui/icons-material/Close";
import LiveBaselineBanner from "../components/shift/LiveBaselineBanner";
import SyncStatusSection from "../components/shift/SyncStatusSection";
import ReadyForVendorSection from "../components/shift/ReadyForVendorSection";
import ShiftMonitorModuleSection from "../components/shift/ShiftMonitorModuleSection";
import VendorHomeComparisonSection from "../components/shift/VendorHomeComparisonSection";
import CurrentFacilitySnapshotSection from "../components/shift/CurrentFacilitySnapshotSection";
import DueTodaySnapshotSection from "../components/shift/DueTodaySnapshotSection";
import FacilityWorkloadSection from "../components/shift/FacilityWorkloadSection";
import { EmployeeActivityPlaceholder } from "../components/shift/DashboardPreviewSections";
import FoldingDateRangeFilter from "../components/folding/FoldingDateRangeFilter";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import { getFoldingPerformanceDetail, getShiftAnalysisSimple, runRinseBothSyncs } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import {
  filterModuleRecords,
  filterRfvRecords,
  formatShiftDateLabel,
  formatDueDateRow,
  formatLastActivityRow,
  formatRushAuditRow,
  formatRecordReason,
  formatEtDateTime,
} from "../utils/shiftMonitorHelpers";

const ShiftAnalysisAdvancedPanel = lazy(() => import("./ShiftAnalysisAdvancedPanel"));

const SYNC_TIMEOUT_MS = 1800000;

function MonitorNav() {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
      {[
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
                <FoldingScanEventsTable events={scanEvents} />
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

function AdvancedDebugSection({ data, user, cfs, dts, facilityTracker }) {
  const audit = data?.debug_audit || {};
  const facility = audit.facility_tracker_today || {};
  const recon = audit.reconciliation_status || {};
  const tagCounts = audit.drilldown_tag_counts || {};
  const debugRush = "all";

  return (
    <Accordion defaultExpanded={false} sx={{ mt: 2, boxShadow: "none", border: "1px solid", borderColor: "divider" }} TransitionProps={{ unmountOnExit: true }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography fontWeight={700}>Advanced Debug</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
          Vendor Home vs Internal Scan (reconciliation)
        </Typography>
        <VendorHomeComparisonSection parity={data?.vendor_home_parity} presence={data?.vendor_home_parity?.presence} />

        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1, mt: 2 }}>
          Current Facility Snapshot (A/B)
        </Typography>
        <CurrentFacilitySnapshotSection snapshot={cfs} rushFilter={debugRush} onDrilldown={() => {}} activeTag={null} />

        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1, mt: 2 }}>
          Due Today Snapshot (A/B)
        </Typography>
        <DueTodaySnapshotSection snapshot={dts} rushFilter={debugRush} onDrilldown={() => {}} activeTag={null} />

        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1, mt: 2 }}>
          Historical Workload
        </Typography>
        <FacilityWorkloadSection tracker={facilityTracker} rushFilter={debugRush} onDrilldown={() => {}} activeTag={null} />

        <EmployeeActivityPlaceholder />

        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5, mt: 2 }}>
          Sync & reconciliation JSON
        </Typography>
        <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
          {JSON.stringify(
            {
              ready_for_vendor_sync: audit.ready_for_vendor_sync,
              at_vendor_sync: audit.at_vendor_sync,
              reconciliation_status: recon,
              live_baseline: audit.live_baseline,
            },
            null,
            2,
          )}
        </Box>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
          Facility workload IDs
        </Typography>
        <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
          {JSON.stringify(
            {
              received_today_ids: facility.entered_today_ids,
              carryover_ids: facility.carryover_ids,
              total_workload_ids: facility.total_workload_ids,
            },
            null,
            2,
          )}
        </Box>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
          Drilldown tag counts
        </Typography>
        <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1, maxHeight: 240 }}>
          {JSON.stringify(tagCounts, null, 2)}
        </Box>
        {data?.scope_overlap ? (
          <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
            {JSON.stringify({ overlap: data.scope_overlap }, null, 2)}
          </Box>
        ) : null}
        {data?.employee_diagnostics?.excluded_external?.length ? (
          <Alert severity="info" sx={{ mb: 2 }}>
            External / ignored users: {data.employee_diagnostics.excluded_external.join(", ")}
          </Alert>
        ) : null}
        <Suspense fallback={<Typography sx={{ p: 2 }}>Loading advanced view…</Typography>}>
          <ShiftAnalysisAdvancedPanel user={user} embedded />
        </Suspense>
      </AccordionDetails>
    </Accordion>
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
    portal_snapshot: { rush: "all", service: "all" },
    facility_status: { rush: "all", service: "all" },
    production_stage: { rush: "all", service: "all" },
    exceptions: { rush: "all", service: "all" },
    monitor: { rush: "all", service: "all" },
  });
  const [rfvRushFilter, setRfvRushFilter] = useState("all");
  const [expandedBag, setExpandedBag] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const initialToday = todayRange();
  const [rangePreset, setRangePreset] = useState(() => {
    const ds = searchParams.get("date_start");
    return ds ? "custom" : "today";
  });
  const [dateStart, setDateStart] = useState(() => searchParams.get("date_start") || initialToday.start);
  const [dateEnd, setDateEnd] = useState(() => searchParams.get("date_end") || initialToday.end);

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
      });
      setData(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load shift monitor");
    } finally {
      setLoading(false);
    }
  }, [dateStart, dateEnd]);

  useEffect(() => {
    load();
  }, [load]);

  const records = data?.records || [];
  const atVendorRecords = data?.at_vendor_module?.rows || [];
  const modules = data?.shift_monitor_modules || {};
  const opsLabel = modules.operations_window?.label;
  const rfv = data?.ready_for_vendor || {};

  const filtered = useMemo(() => {
    if (!drilldown) return [];
    if (drilldown.type === "rfv") {
      return filterRfvRecords(rfv.rows || [], drilldown.drilldownTag, rfvRushFilter);
    }
    const f = moduleFilters[drilldown.moduleKey] || { rush: "all", service: "all" };
    const sourceRecords = drilldown.moduleKey === "facility_status" ? atVendorRecords : records;
    return filterModuleRecords(sourceRecords, {
      moduleTag: drilldown.moduleTag,
      rushFilter: f.rush,
      serviceFilter: f.service,
    });
  }, [records, atVendorRecords, drilldown, moduleFilters, rfv.rows, rfvRushFilter]);

  const openDrilldown = (ctx) => {
    setDrilldown(ctx);
    setDrawerOpen(true);
  };

  const openRfvDrilldown = (tagOrCtx) => {
    const tag = typeof tagOrCtx === "string" ? tagOrCtx : (tagOrCtx?.drilldown_tag || tagOrCtx?.drilldownTag);
    const cardLabel = typeof tagOrCtx === "string" ? tag : (tagOrCtx?.label || tagOrCtx?.cardLabel || tag);
    setDrilldown({
      type: "rfv",
      drilldownTag: tag,
      cardLabel,
      moduleTitle: "Ready for Vendor",
    });
    setDrawerOpen(true);
  };

  const setModuleFilter = (moduleKey, patch) => {
    setModuleFilters((prev) => ({
      ...prev,
      [moduleKey]: { ...(prev[moduleKey] || { rush: "all", service: "all" }), ...patch },
    }));
  };

  const runRinseSync = async () => {
    setSyncRunning(true);
    setSyncMessage("");
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(() => {
      setSyncRunning(false);
      setSyncMessage("Sync timed out after 30 minutes — check Scheduled Rinse Sync for status.");
    }, SYNC_TIMEOUT_MS);
    try {
      const res = await runRinseBothSyncs({ dry_run: false });
      const av = res.data?.at_vendor_sync || {};
      const rfv = res.data?.ready_for_vendor_sync || {};
      const overall = res.data?.overall_status || "success";
      const rfvDetail = (() => {
        if (rfv.skipped_reason || rfv.status === "disabled") {
          return `Ready for Vendor skipped: ${rfv.skipped_reason || "feature flag disabled"}`;
        }
        if (rfv.status === "failed") {
          return `Ready for Vendor failed: ${rfv.error_message || "unknown error"}`;
        }
        if (rfv.status === "success" && Number(rfv.rows_found) === 0) {
          return "Ready for Vendor returned 0 rows successfully (old rows marked inactive)";
        }
        if (rfv.status === "success") {
          return `Ready for Vendor success: ${rfv.rows_found ?? 0} rows, ${rfv.active_rows ?? 0} active`;
        }
        return `Ready for Vendor: ${rfv.status || "—"}`;
      })();
      setSyncMessage(
        overall === "partial_success"
          ? `At Vendor: ${av.status || "—"} · ${rfvDetail} (partial success)`
          : `Both syncs finished — At Vendor: ${av.status || "—"} · ${rfvDetail}`,
      );
      await load();
    } catch (e) {
      const errData = e?.response?.data;
      if (errData?.overall_status === "partial_success" || e?.response?.status === 207) {
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
        setSyncMessage(errData?.error || "Refresh Both Syncs failed");
      }
    } finally {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
      setSyncRunning(false);
    }
  };

  const rfvSync = data?.rinse_sync?.ready_for_vendor || rfv.sync_status || {};
  const pipeline = data?.current_work_pipeline || data?.current_active_work_now || data?.current_active_work || {};
  const avSync = data?.rinse_sync?.at_vendor || pipeline.sync_status || {};
  const cfs = data?.current_facility_snapshot || {};
  const dts = data?.due_today_snapshot || {};
  const facilityTracker = data?.facility_tracker_today || {};

  const moduleKeys = ["portal_snapshot", "facility_status", "production_stage", "exceptions", "monitor"];

  return (
    <Box sx={{ p: { xs: 1.5, md: 3 }, maxWidth: 960, mx: "auto", pb: 6 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        spacing={1}
        sx={{ mb: 2, position: "sticky", top: 0, zIndex: 10, bgcolor: "background.default", py: 1 }}
      >
        <Box>
          <Typography variant="h5" fontWeight={900}>
            Shift Monitor
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {formatShiftDateLabel(dateStart, dateEnd)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Times shown in New York time
          </Typography>
        </Box>
        <MonitorNav />
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 2 }} flexWrap="wrap">
        <FoldingDateRangeFilter
          preset={rangePreset}
          onPresetChange={setRangePreset}
          dateStart={dateStart}
          dateEnd={dateEnd}
          onDateStartChange={setDateStart}
          onDateEndChange={setDateEnd}
          showDateField={false}
        />
        <Button variant="contained" size="small" onClick={load} disabled={loading} sx={{ alignSelf: { xs: "stretch", sm: "center" } }}>
          Apply
        </Button>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {syncMessage ? <Alert severity="info" sx={{ mb: 2 }}>{syncMessage}</Alert> : null}
      {loading && !data ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}

      {data ? (
        <>
          <SyncStatusSection
            avSync={avSync}
            rfvSync={rfvSync}
            rfv={rfv}
            syncRunning={syncRunning}
            loading={loading}
            onRefresh={runRinseSync}
          />

          <ReadyForVendorSection
            rfv={rfv}
            rfvSync={rfvSync}
            rushFilter={rfvRushFilter}
            onRushChange={setRfvRushFilter}
            onDrilldown={openRfvDrilldown}
            activeTag={drilldown?.type === "rfv" ? drilldown.drilldownTag : null}
          />

          <LiveBaselineBanner baseline={data?.live_baseline} />

          {moduleKeys.map((key) => (
            <ShiftMonitorModuleSection
              key={key}
              moduleKey={key}
              module={modules[key]}
              records={key === "facility_status" ? atVendorRecords : records}
              rushFilter={moduleFilters[key]?.rush || "all"}
              serviceFilter={moduleFilters[key]?.service || "all"}
              onRushChange={(v) => setModuleFilter(key, { rush: v })}
              onServiceChange={(v) => setModuleFilter(key, { service: v })}
              onDrilldown={openDrilldown}
              activeTag={drilldown}
              operationsLabel={key === "monitor" ? opsLabel : undefined}
            />
          ))}

          <AdvancedDebugSection data={data} user={user} cfs={cfs} dts={dts} facilityTracker={facilityTracker} />
        </>
      ) : null}

      <Drawer
        anchor="bottom"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{ sx: { height: "70vh", borderTopLeftRadius: 16, borderTopRightRadius: 16, p: 2 } }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Box>
            <Typography variant="h6" fontWeight={800}>
              {drilldown?.moduleTitle || "Records"} — {drilldown?.cardLabel || ""}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block">
              {drilldown?.type === "rfv"
                ? `Rush: ${rfvRushFilter} · Count: ${filtered.length}`
                : `Rush: ${moduleFilters[drilldown?.moduleKey]?.rush || "all"} · Service: ${moduleFilters[drilldown?.moduleKey]?.service || "all"} · Count: ${filtered.length}`}
            </Typography>
          </Box>
          <IconButton onClick={() => setDrawerOpen(false)} aria-label="Close">
            <CloseIcon />
          </IconButton>
        </Stack>
        <Box sx={{ overflow: "auto", flex: 1 }}>
          {drilldown?.type === "rfv"
            ? filtered.map((row) => <RfvRecordRow key={row.bag_id} row={row} />)
            : drilldown?.moduleKey === "facility_status"
              ? filtered.map((row) => (
                <AtVendorRecordRow
                  key={row.bag_id}
                  row={row}
                  changedRushDrilldown={drilldown?.moduleTag === "mod_at_vendor_changed_rush"}
                />
              ))
              : filtered.map((row) => (
                <RecordRow
                  key={row.bag_id}
                  row={row}
                  expanded={expandedBag === row.bag_id}
                  onToggle={() => setExpandedBag((b) => (b === row.bag_id ? null : row.bag_id))}
                />
              ))}
          {filtered.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No records for this filter.</Typography>
          ) : null}
        </Box>
      </Drawer>
    </Box>
  );
}
