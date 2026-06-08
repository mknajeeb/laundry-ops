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
import FoldingDateRangeFilter from "../components/folding/FoldingDateRangeFilter";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import { getFoldingPerformanceDetail, getShiftAnalysisSimple, runRinseBothSyncs } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import {
  RUSH_FILTERS,
  filterRecords,
  formatShiftDateLabel,
  sectionSplitCounts,
  syncStatusSubtext,
  rinseSyncBanner,
} from "../utils/shiftMonitorHelpers";

const ShiftAnalysisAdvancedPanel = lazy(() => import("./ShiftAnalysisAdvancedPanel"));

const ACCENT = "#0097b2";
const SYNC_TIMEOUT_MS = 120000;

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

function RushFilterChips({ value, onChange }) {
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mb: 1.5 }}>
      {RUSH_FILTERS.map(({ id, label }) => (
        <Chip
          key={id}
          size="small"
          label={label}
          color={value === id ? "primary" : "default"}
          variant={value === id ? "filled" : "outlined"}
          onClick={() => onChange(id)}
        />
      ))}
    </Stack>
  );
}

function StatCard({ label, value, source, sub, onClick, active, warn }) {
  const display = value ?? "—";
  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "2px solid",
        borderColor: active ? ACCENT : warn ? "error.main" : "divider",
        cursor: onClick ? "pointer" : "default",
        bgcolor: active ? "rgba(0,151,178,0.06)" : "background.paper",
        minHeight: 88,
      }}
    >
      <Typography variant="h4" fontWeight={800} lineHeight={1.1} color={warn ? "error.main" : ACCENT}>
        {display}
      </Typography>
      <Typography variant="body2" fontWeight={700} sx={{ mt: 0.5 }}>
        {label}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {sub}
        </Typography>
      ) : null}
      {source ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
          {source}
        </Typography>
      ) : null}
    </Paper>
  );
}

function Section({ title, description, rushFilter, onRushFilterChange, children, alert }) {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" fontWeight={800}>
        {title}
      </Typography>
      {description ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {description}
        </Typography>
      ) : null}
      {alert}
      {onRushFilterChange ? <RushFilterChips value={rushFilter} onChange={onRushFilterChange} /> : null}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
          gap: 1.5,
        }}
      >
        {children}
      </Box>
    </Box>
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

  return (
    <Paper elevation={0} sx={{ p: 1.5, mb: 1, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" onClick={onToggle} sx={{ cursor: "pointer" }}>
        <Box>
          <Typography variant="subtitle2" fontWeight={800}>
            {row.bag_id}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {row.customer || "—"}
          </Typography>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
            <Chip size="small" label={row.rush_label || "—"} />
            <Chip size="small" label={row.service_type || "WF"} variant="outlined" />
            {row.needs_review ? <Chip size="small" color="warning" label="Review" /> : null}
          </Stack>
        </Box>
        <Box textAlign="right">
          <Typography variant="caption" color="text.secondary" display="block">
            {row.current_status || "—"}
          </Typography>
          <Typography variant="caption" display="block">
            {formatDateTime(row.last_scan_time)}
          </Typography>
        </Box>
      </Stack>
      <Collapse in={expanded}>
        <Box sx={{ mt: 1.5, pt: 1.5, borderTop: "1px dashed", borderColor: "divider" }}>
          <Typography variant="caption" display="block">
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
  const [filterTag, setFilterTag] = useState(searchParams.get("filter") || null);
  const [rushFilter, setRushFilter] = useState("all");
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
  const filtered = useMemo(
    () => filterRecords(records, filterTag, rushFilter),
    [records, filterTag, rushFilter],
  );

  const openDrilldown = (tag) => {
    setFilterTag(tag);
    setDrawerOpen(true);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tag) next.set("filter", tag);
      else next.delete("filter");
      return next;
    });
  };

  const runRinseSync = async () => {
    setSyncRunning(true);
    setSyncMessage("");
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(() => {
      setSyncRunning(false);
      setSyncMessage("Sync timed out — check Scheduled Rinse Sync for status.");
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
      const data = e?.response?.data;
      if (data?.overall_status === "partial_success" || e?.response?.status === 207) {
        setSyncMessage(
          `Partial success — At Vendor: ${data?.at_vendor_sync?.status || "ok"} · ${
            data?.ready_for_vendor_sync?.error_message
              ? `Ready for Vendor failed: ${data.ready_for_vendor_sync.error_message}`
              : data?.ready_for_vendor_sync?.skipped_reason
                ? `Ready for Vendor skipped: ${data.ready_for_vendor_sync.skipped_reason}`
                : `Ready for Vendor: ${data?.ready_for_vendor_sync?.status || "failed"}`
          }`,
        );
        await load();
      } else {
        setSyncMessage(data?.error || "Refresh Both Syncs failed");
      }
    } finally {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
      setSyncRunning(false);
    }
  };

  const rfv = data?.ready_for_vendor || {};
  const facility = data?.facility_tracker_today || {};
  const active = data?.current_active_work_now || data?.current_active_work || {};
  const underReview = data?.sections_under_review || {};
  const rfvLive = rfv.live !== false && underReview.ready_for_vendor_live !== false;
  const rinseSync = rinseSyncBanner(data);
  const rfvCounts = sectionSplitCounts(rfv, rushFilter);
  const facilityCounts = sectionSplitCounts(facility, rushFilter);
  const activeCounts = sectionSplitCounts(active, rushFilter);
  const avSync = data?.rinse_sync?.at_vendor || active.sync_status || {};
  const rfvSync = data?.rinse_sync?.ready_for_vendor || rfv.sync_status || {};
  const rfvSyncSub = syncStatusSubtext({ sync_status: rfvSync, last_refreshed_at: rfv.last_refreshed_at }, "Ready for Vendor Sync");
  const avSyncSub = syncStatusSubtext({ sync_status: avSync }, "At Vendor Sync");
  const rfvSyncStale = rfvSync?.stale && (rfv.last_refreshed_at || rfvSync.last_refreshed_at);
  const avSyncStale = avSync?.stale && (active.last_refreshed_at || avSync.last_refreshed_at);

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
        <Button variant="outlined" size="small" onClick={runRinseSync} disabled={syncRunning || loading}>
          {syncRunning ? "Refreshing…" : "Refresh Both Syncs"}
        </Button>
      </Stack>

      {data?.rinse_sync ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {rinseSync.lines.filter(Boolean).join(" · ")}
        </Typography>
      ) : null}

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {syncMessage ? <Alert severity="info" sx={{ mb: 2 }}>{syncMessage}</Alert> : null}
      {loading && !data ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}

      {data ? (
        <>
          <Section
            title="Sync Status"
            description="At Vendor Sync and Ready for Vendor Sync timestamps"
          >
            <StatCard label="At Vendor Sync" value={avSync.last_refreshed_at_et || avSync.message || "—"} source="orders_staging + scan events" sub={avSyncSub} />
            <StatCard
              label="Ready for Vendor Sync"
              value={rfvSync.last_refreshed_at_et || rfvSync.last_success_at_et || rfvSync.message || "—"}
              source="rinse_cleaner_ticket_presence"
              sub={rfv.unavailable_reason || rfvSyncSub || (rfvSync.zero_rows_success ? "0 rows — success" : null)}
              warn={!rfvLive || rfvSync?.failed || rfvSync?.latest_failed}
            />
          </Section>

          <Section
            title="Facility Tracker Today"
            description="Bags that entered today — facility entry rack scan on selected date (kept even if completed or sent)"
            rushFilter={rushFilter}
            onRushFilterChange={setRushFilter}
            alert={
              facility.entry_racks?.length ? (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  Entry racks: {facility.entry_racks.join(", ")}
                </Typography>
              ) : null
            }
          >
            <StatCard
              label="Entered Total"
              value={facilityCounts.total}
              source={facility.source || "Scan events"}
              onClick={() => openDrilldown("facility_tracker")}
              active={filterTag === "facility_tracker"}
            />
            <StatCard label="Rush WF" value={rushFilter === "non_rush" ? 0 : facility.rush_wf} onClick={() => openDrilldown("facility_rush_wf")} active={filterTag === "facility_rush_wf"} />
            <StatCard label="Rush HD" value={rushFilter === "non_rush" ? 0 : facility.rush_hd} onClick={() => openDrilldown("facility_rush_hd")} active={filterTag === "facility_rush_hd"} />
            <StatCard label="Non-Rush WF" value={rushFilter === "rush" ? 0 : facility.nonrush_wf} onClick={() => openDrilldown("facility_nonrush_wf")} active={filterTag === "facility_nonrush_wf"} />
            <StatCard label="Non-Rush HD" value={rushFilter === "rush" ? 0 : facility.nonrush_hd} onClick={() => openDrilldown("facility_nonrush_hd")} active={filterTag === "facility_nonrush_hd"} />
            <StatCard label="Unknown / Review" value={rushFilter === "all" ? facility.unknown_needs_review : 0} onClick={() => openDrilldown("facility_unknown_needs_review")} />
            <StatCard label="Completed" value={facility.completed ?? 0} source="Scan completion rules" />
            <StatCard label="Still Active" value={facility.still_active ?? 0} source="Current active staging" />
            <StatCard label="Sent / Checked Out" value={facility.sent_or_checked_out ?? 0} source="Lifecycle / checkout" />
          </Section>

          <Section
            title="Current Active Work Now"
            description="Bags still pending now — active orders_staging (includes carryover from prior days)"
            rushFilter={rushFilter}
            onRushFilterChange={setRushFilter}
            alert={
              active.data_quality_warning ? (
                <Alert severity="error" sx={{ mb: 1.5 }}>{active.data_quality_warning}</Alert>
              ) : avSyncStale ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>{avSyncSub}</Alert>
              ) : active.unreconciled > 0 ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  {active.unreconciled} unreconciled bag(s) — splits do not match total. Use drilldown.
                </Alert>
              ) : null
            }
          >
            <StatCard label="Active Total" value={activeCounts.total} source={active.source} sub={avSyncSub} onClick={() => openDrilldown("active_work")} active={filterTag === "active_work"} />
            <StatCard label="Rush WF" value={rushFilter === "non_rush" ? 0 : active.rush_wf} onClick={() => openDrilldown("active_rush_wf")} />
            <StatCard label="Rush HD" value={rushFilter === "non_rush" ? 0 : active.rush_hd} onClick={() => openDrilldown("active_rush_hd")} />
            <StatCard label="Non-Rush WF" value={rushFilter === "rush" ? 0 : active.nonrush_wf} onClick={() => openDrilldown("active_nonrush_wf")} />
            <StatCard label="Non-Rush HD" value={rushFilter === "rush" ? 0 : active.nonrush_hd} onClick={() => openDrilldown("active_nonrush_hd")} />
            <StatCard label="Unknown / Review" value={rushFilter === "all" ? active.unknown_needs_review : 0} onClick={() => openDrilldown("unknown_speed_service")} />
          </Section>

          <Section
            title="Ready for Vendor"
            description={rfvLive ? "Incoming / unassigned queue from Rinse Sync" : "Sync required before live counts are shown"}
            rushFilter={rfvLive ? rushFilter : null}
            onRushFilterChange={rfvLive ? setRushFilter : null}
            alert={
              !rfvLive ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  {rfv.unavailable_reason || "Ready for Vendor: Sync stale"}
                  {rfv.last_refreshed_at ? ` · Last refresh: ${formatDateTime(rfv.last_refreshed_at)}` : ""}
                </Alert>
              ) : rfv.data_quality_warning ? (
                <Alert severity={rfv.zero_rows_success ? "info" : "error"} sx={{ mb: 1.5 }}>{rfv.data_quality_warning}</Alert>
              ) : rfvSyncStale ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>{rfvSyncSub}</Alert>
              ) : null
            }
          >
            {rfvLive ? (
              <>
                <StatCard label="Total" value={rfvCounts.total} source="Ready for Vendor queue" sub={rfvSyncSub} onClick={() => openDrilldown("ready_for_vendor")} active={filterTag === "ready_for_vendor"} />
                <StatCard label="Rush WF" value={rushFilter === "non_rush" ? 0 : rfv.rush_wf} onClick={() => openDrilldown("rfv_rush_wf")} active={filterTag === "rfv_rush_wf"} />
                <StatCard label="Rush HD" value={rushFilter === "non_rush" ? 0 : rfv.rush_hd} onClick={() => openDrilldown("rfv_rush_hd")} active={filterTag === "rfv_rush_hd"} />
                <StatCard label="Non-Rush WF" value={rushFilter === "rush" ? 0 : rfv.nonrush_wf} onClick={() => openDrilldown("rfv_nonrush_wf")} active={filterTag === "rfv_nonrush_wf"} />
                <StatCard label="Non-Rush HD" value={rushFilter === "rush" ? 0 : rfv.nonrush_hd} onClick={() => openDrilldown("rfv_nonrush_hd")} active={filterTag === "rfv_nonrush_hd"} />
                <StatCard label="Unknown / Review" value={rushFilter === "all" ? rfv.unknown_needs_review : 0} warn={rushFilter === "all" && rfv.unknown_needs_review > 0} onClick={() => openDrilldown("rfv_unknown_needs_review")} active={filterTag === "rfv_unknown_needs_review"} />
              </>
            ) : (
              <StatCard label="Ready for Vendor" value="—" source="Unavailable" sub={rfv.unavailable_reason || rfvSyncSub || "Refresh Both Syncs"} />
            )}
          </Section>

          {underReview.shift_status || underReview.rush_checkout || underReview.employee_activity || underReview.exceptions ? (
            <Alert severity="info" sx={{ mb: 2 }}>
              Employee Activity, Shift Status, Checkout, and Exceptions remain under review until Facility Tracker Today and Current Active Work Now are verified.
            </Alert>
          ) : null}

          <Accordion sx={{ mt: 2, boxShadow: "none", border: "1px solid", borderColor: "divider" }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography fontWeight={700}>Advanced / Debug</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {data.scope_overlap ? (
                <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
                  {JSON.stringify({ overlap: data.scope_overlap, facility_tracker_today: data.debug_audit?.facility_tracker_today, current_active_work_now: data.debug_audit?.current_active_work_now }, null, 2)}
                </Box>
              ) : null}
              {data.dashboard_reconciliation ? (
                <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
                  {JSON.stringify(data.dashboard_reconciliation, null, 2)}
                </Box>
              ) : null}
              {data.debug_audit ? (
                <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
                  {JSON.stringify(data.debug_audit, null, 2)}
                </Box>
              ) : null}
              {data.employee_diagnostics?.excluded_external?.length ? (
                <Alert severity="info" sx={{ mb: 2 }}>
                  External / ignored users: {data.employee_diagnostics.excluded_external.join(", ")}
                </Alert>
              ) : null}
              <Suspense fallback={<Typography sx={{ p: 2 }}>Loading advanced view…</Typography>}>
                <ShiftAnalysisAdvancedPanel user={user} embedded />
              </Suspense>
            </AccordionDetails>
          </Accordion>
        </>
      ) : null}

      <Drawer
        anchor="bottom"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{ sx: { height: "70vh", borderTopLeftRadius: 16, borderTopRightRadius: 16, p: 2 } }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6" fontWeight={800}>
            Records ({filtered.length})
          </Typography>
          <IconButton onClick={() => setDrawerOpen(false)} aria-label="Close">
            <CloseIcon />
          </IconButton>
        </Stack>
        <Stack direction="row" spacing={1} sx={{ mb: 1 }} flexWrap="wrap">
          {filterTag ? <Chip label={filterTag} onDelete={() => setFilterTag(null)} /> : null}
          {rushFilter !== "all" ? <Chip label={rushFilter === "rush" ? "Rush" : "Non-Rush"} size="small" /> : null}
        </Stack>
        <Box sx={{ overflow: "auto", flex: 1 }}>
          {filtered.map((row) => (
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
