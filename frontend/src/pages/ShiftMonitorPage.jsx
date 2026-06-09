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
import ReadyForVendorSection from "../components/shift/ReadyForVendorSection";
import FacilityWorkloadSection from "../components/shift/FacilityWorkloadSection";
import ShiftCountCard from "../components/shift/ShiftCountCard";
import RushFilterChips from "../components/shift/RushFilterChips";
import {
  WipPreviewSection,
  MonitorPreviewSection,
  ExceptionsPreviewSection,
  EmployeeActivityPlaceholder,
} from "../components/shift/DashboardPreviewSections";
import FoldingDateRangeFilter from "../components/folding/FoldingDateRangeFilter";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import { getFoldingPerformanceDetail, getShiftAnalysisSimple, runRinseBothSyncs } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import {
  filterRecords,
  formatShiftDateLabel,
  syncStatusSubtext,
  rinseSyncBanner,
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
          {hasSpecial ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              {row.special_instructions_raw || "—"}
              {row.supply_interpretation ? ` · ${row.supply_interpretation}` : ""}
              {row.special_instruction_review ? " · Review flagged" : ""}
            </Typography>
          ) : null}
        </Box>
        <Box textAlign="right">
          <Typography variant="caption" color="text.secondary" display="block">
            {row.current_status || "—"}
          </Typography>
          <Typography variant="caption" display="block">
            {formatDateTime(row.last_scan_time)}
          </Typography>
          {row.date_clean ? (
            <Typography variant="caption" color="text.secondary" display="block">
              EDD {row.date_clean}
            </Typography>
          ) : null}
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

function AdvancedDebugSection({ data, user }) {
  const audit = data?.debug_audit || {};
  const facility = audit.facility_tracker_today || {};
  const recon = audit.reconciliation_status || {};
  const tagCounts = audit.drilldown_tag_counts || {};

  return (
    <Accordion defaultExpanded={false} sx={{ mt: 2, boxShadow: "none", border: "1px solid", borderColor: "divider" }} TransitionProps={{ unmountOnExit: true }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography fontWeight={700}>Advanced Debug</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
          Sync & reconciliation
        </Typography>
        <Box component="pre" sx={{ fontSize: 11, overflow: "auto", mb: 2, p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
          {JSON.stringify(
            {
              ready_for_vendor_sync: audit.ready_for_vendor_sync,
              at_vendor_sync: audit.at_vendor_sync,
              reconciliation_status: recon,
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
              rush_wf_ids: data?.facility_tracker_today?.total_workload?.rush_wf_ids,
              rush_hd_ids: data?.facility_tracker_today?.total_workload?.rush_hd_ids,
              nonrush_wf_ids: data?.facility_tracker_today?.total_workload?.nonrush_wf_ids,
              nonrush_hd_ids: data?.facility_tracker_today?.total_workload?.nonrush_hd_ids,
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

  const rfv = data?.ready_for_vendor || {};
  const facility = data?.facility_tracker_today || {};
  const pipeline = data?.current_work_pipeline || data?.current_active_work_now || data?.current_active_work || {};
  const shiftStatus = data?.shift_status || {};
  const wip = data?.wip || {};
  const underReview = data?.sections_under_review || {};
  const rfvLive = rfv.live !== false && underReview.ready_for_vendor_live !== false;
  const rinseSync = rinseSyncBanner(data);
  const avSync = data?.rinse_sync?.at_vendor || pipeline.sync_status || {};
  const rfvSync = data?.rinse_sync?.ready_for_vendor || rfv.sync_status || {};
  const rfvSyncSub = syncStatusSubtext({ sync_status: rfvSync, last_refreshed_at: rfv.last_refreshed_at }, "Ready for Vendor Sync");
  const avSyncSub = syncStatusSubtext({ sync_status: avSync }, "At Vendor Sync");
  const rfvSyncStale = rfvSync?.stale && (rfv.last_refreshed_at || rfvSync.last_refreshed_at);

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
          <Box sx={{ mb: 2.5 }}>
            <Typography variant="h6" fontWeight={800} sx={{ mb: 1 }}>
              Sync Status
            </Typography>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
                gap: 1,
              }}
            >
              <ShiftCountCard label="At Vendor Sync" value={avSync.last_refreshed_at_et || avSync.message || "—"} sub={avSyncSub} />
              <ShiftCountCard
                label="Ready for Vendor Sync"
                value={rfvSync.last_refreshed_at_et || rfvSync.message || rfvSync.last_success_at_et || "—"}
                sub={rfv.unavailable_reason || rfvSyncSub || (rfvSync.zero_rows_success ? "0 rows — success" : null)}
                warn={!rfvLive || rfvSync?.failed || rfvSync?.latest_failed}
              />
            </Box>
          </Box>

          <ReadyForVendorSection
            rfv={rfv}
            rfvLive={rfvLive}
            rfvSync={rfvSync}
            rfvSyncSub={rfvSyncSub}
            rfvSyncStale={rfvSyncStale}
            rushFilter={rushFilter}
            onRushFilterChange={setRushFilter}
            onDrilldown={openDrilldown}
            activeTag={filterTag}
          />

          <Box sx={{ mb: 1 }}>
            <RushFilterChips value={rushFilter} onChange={setRushFilter} />
          </Box>

          <FacilityWorkloadSection
            tracker={facility}
            rushFilter={rushFilter}
            onDrilldown={openDrilldown}
            activeTag={filterTag}
          />

          <WipPreviewSection
            wip={wip}
            shiftStatus={shiftStatus}
            pipeline={pipeline}
            underReview={underReview.wip ?? underReview.shift_status}
            onDrilldown={openDrilldown}
            activeTag={filterTag}
          />
          <MonitorPreviewSection pipeline={pipeline} underReview={underReview.shift_status} onDrilldown={openDrilldown} activeTag={filterTag} />
          <ExceptionsPreviewSection exceptions={data.exceptions_summary} underReview={underReview.exceptions} onDrilldown={openDrilldown} activeTag={filterTag} />
          <EmployeeActivityPlaceholder />

          <AdvancedDebugSection data={data} user={user} />
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
