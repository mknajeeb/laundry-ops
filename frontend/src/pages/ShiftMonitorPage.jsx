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
import { getShiftAnalysisSimple, runCleanerTicketPresenceScrape } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatLaborHours, formatRate } from "../utils/foldingFormat";
import {
  RUSH_FILTERS,
  filterRecords,
  formatShiftDateLabel,
  sectionSplitCounts,
  shiftMetricValue,
  syncStatusSubtext,
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
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {row.source}
          </Typography>
        </Box>
      </Collapse>
    </Paper>
  );
}

function EmployeeCard({ card }) {
  const [open, setOpen] = useState(false);
  const diag = card.diagnostic;
  return (
    <Paper elevation={0} sx={{ p: 2, mb: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
      <Stack direction="row" justifyContent="space-between" onClick={() => setOpen((v) => !v)} sx={{ cursor: "pointer" }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={800}>
            {card.employee}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Clock-in: {formatDateTime(card.clock_in_time) || (diag || "—")}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Last activity: {formatDateTime(card.last_activity_time) || "—"}
          </Typography>
        </Box>
        <Box textAlign="right">
          <Typography variant="h5" fontWeight={800} color={ACCENT}>
            {card.total_bags_touched ?? 0}
          </Typography>
          <Typography variant="caption">bags touched</Typography>
          <Typography variant="caption" display="block">
            {diag
              || `${formatLaborHours(card.performance_hours)} · ${formatRate(card.bags_per_hour)} bags/hr${card.lbs_per_hour ? ` · ${formatRate(card.lbs_per_hour)} lbs/hr` : ""}`}
          </Typography>
        </Box>
      </Stack>
      <Collapse in={open}>
        <Stack spacing={1} sx={{ mt: 1.5 }}>
          {(card.roles || []).map((role) => (
            <Box key={role.role} sx={{ p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
              <Typography variant="body2" fontWeight={700}>
                {role.role} · {role.bags} bags{role.lbs ? ` · ${role.lbs} lbs` : ""}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {role.diagnostic
                  || `${formatLaborHours(role.performance_hours)} perf hrs · ${formatRate(role.bags_per_hour)} bags/hr${role.lbs_per_hour ? ` · ${formatRate(role.lbs_per_hour)} lbs/hr` : ""} · last ${formatDateTime(role.last_activity_time)}`}
              </Typography>
            </Box>
          ))}
        </Stack>
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

  const runRinseSync = async (dryRun) => {
    setSyncRunning(true);
    setSyncMessage("");
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(() => {
      setSyncRunning(false);
      setSyncMessage("Rinse Sync timed out — check admin tools for status.");
    }, SYNC_TIMEOUT_MS);
    try {
      await runCleanerTicketPresenceScrape({
        portal_status: "ready_for_vendor",
        dry_run: dryRun,
        mark_missing: false,
      });
      setSyncMessage(dryRun ? "Dry Run Rinse Sync finished." : "Apply Rinse Sync finished.");
      await load();
    } catch (e) {
      setSyncMessage(e?.response?.data?.error || "Rinse Sync failed");
    } finally {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
      setSyncRunning(false);
    }
  };

  const rfv = data?.ready_for_vendor || {};
  const active = data?.current_active_work || {};
  const checkout = data?.rush_checkout || {};
  const shift = data?.shift_status || {};
  const exceptions = data?.exceptions_summary || {};
  const rfvCounts = sectionSplitCounts(rfv, rushFilter);
  const activeCounts = sectionSplitCounts(active, rushFilter);
  const syncSub = syncStatusSubtext(rfv);
  const syncStale = rfv.sync_status?.stale && rfv.last_refreshed_at;

  const weightDiffValue = (() => {
    const wd = shift.weight_difference;
    const flagged = shiftMetricValue(wd, rushFilter);
    if (flagged > 0) return flagged;
    if (shift.weight_difference_status === "unavailable") return "—";
    return flagged ?? 0;
  })();

  const weightDiffSub = (() => {
    if (shift.weight_difference_status === "unavailable") {
      return "No comparable first/second weights";
    }
    return `≥${shift.weight_difference_threshold_lbs} lbs threshold`;
  })();

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
        <Button variant="outlined" size="small" onClick={() => runRinseSync(false)} disabled={syncRunning || loading}>
          {syncRunning ? "Refreshing…" : "Refresh Rinse Sync"}
        </Button>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {syncMessage ? <Alert severity="info" sx={{ mb: 2 }}>{syncMessage}</Alert> : null}
      {loading && !data ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}

      {data ? (
        <>
          <Section
            title="Ready for Vendor"
            description="Incoming / unassigned queue from Rinse Sync"
            rushFilter={rushFilter}
            onRushFilterChange={setRushFilter}
            alert={
              rfv.data_quality_warning ? (
                <Alert severity="error" sx={{ mb: 1.5 }}>{rfv.data_quality_warning}</Alert>
              ) : syncStale ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>{syncSub}</Alert>
              ) : null
            }
          >
            <StatCard
              label="Total"
              value={rfvCounts.total}
              source="Ready for Vendor queue"
              sub={syncSub}
              onClick={() => openDrilldown("ready_for_vendor")}
              active={filterTag === "ready_for_vendor"}
            />
            <StatCard label="Rush WF" value={rushFilter === "non_rush" ? 0 : rfv.rush_wf} onClick={() => openDrilldown("rfv_rush_wf")} active={filterTag === "rfv_rush_wf"} />
            <StatCard label="Rush HD" value={rushFilter === "non_rush" ? 0 : rfv.rush_hd} onClick={() => openDrilldown("rfv_rush_hd")} active={filterTag === "rfv_rush_hd"} />
            <StatCard label="Non-Rush WF" value={rushFilter === "rush" ? 0 : rfv.nonrush_wf} onClick={() => openDrilldown("rfv_nonrush_wf")} active={filterTag === "rfv_nonrush_wf"} />
            <StatCard label="Non-Rush HD" value={rushFilter === "rush" ? 0 : rfv.nonrush_hd} onClick={() => openDrilldown("rfv_nonrush_hd")} active={filterTag === "rfv_nonrush_hd"} />
            <StatCard
              label="Unknown / Review"
              value={rushFilter === "all" ? rfv.unknown_needs_review : 0}
              warn={rushFilter === "all" && rfv.unknown_needs_review > 0}
              onClick={() => openDrilldown("rfv_unknown_needs_review")}
              active={filterTag === "rfv_unknown_needs_review"}
            />
          </Section>

          <Section
            title="Current Active Work"
            description="At Vendor — bags currently in facility production"
            rushFilter={rushFilter}
            onRushFilterChange={setRushFilter}
            alert={
              active.unreconciled > 0 ? (
                <Alert severity="warning" sx={{ mb: 1.5 }}>
                  {active.unreconciled} unreconciled bag(s) — splits do not match total. Use drilldown.
                </Alert>
              ) : null
            }
          >
            <StatCard label="Active Total" value={activeCounts.total} source={active.source} onClick={() => openDrilldown("active_work")} active={filterTag === "active_work"} />
            <StatCard label="Rush WF" value={rushFilter === "non_rush" ? 0 : active.rush_wf} onClick={() => openDrilldown("active_rush_wf")} />
            <StatCard label="Rush HD" value={rushFilter === "non_rush" ? 0 : active.rush_hd} onClick={() => openDrilldown("active_rush_hd")} />
            <StatCard label="Non-Rush WF" value={rushFilter === "rush" ? 0 : active.nonrush_wf} onClick={() => openDrilldown("active_nonrush_wf")} />
            <StatCard label="Non-Rush HD" value={rushFilter === "rush" ? 0 : active.nonrush_hd} onClick={() => openDrilldown("active_nonrush_hd")} />
            <StatCard
              label="Unknown / Review"
              value={rushFilter === "all" ? active.unknown_needs_review : 0}
              onClick={() => openDrilldown("unknown_speed_service")}
            />
          </Section>

          <Section
            title="Rush Checkout"
            description={checkout.description || "Checkout Pending = Rush bags still waiting for facility checkout"}
            rushFilter="rush"
          >
            <StatCard label="Checkout Pending" value={checkout.checkout_pending} source={checkout.source} onClick={() => openDrilldown("checkout_pending")} active={filterTag === "checkout_pending"} />
            <StatCard label="Checked Out" value={checkout.checked_out} source={checkout.source} />
            <StatCard label="Checkout Not Recorded" value={checkout.checkout_not_recorded} source={checkout.source} onClick={() => openDrilldown("checkout_pending")} />
            <StatCard label="Checkout Needs Review" value={checkout.checkout_needs_review} source={checkout.source} />
          </Section>

          <Section title="Shift Status" rushFilter={rushFilter} onRushFilterChange={setRushFilter}>
            <StatCard label="Weighed" value={shiftMetricValue(shift.weighed, rushFilter)} source={shift.source} onClick={() => openDrilldown("shift_weighed")} />
            <StatCard label="Not Weighed" value={shiftMetricValue(shift.not_weighed, rushFilter)} source={shift.source} onClick={() => openDrilldown("shift_not_weighed")} />
            <StatCard label="Issues" value={shiftMetricValue(shift.issues, rushFilter)} source="Scan events" onClick={() => openDrilldown("issues")} />
            <StatCard label="Workitems" value={shiftMetricValue(shift.workitems, rushFilter)} source="Scan events" onClick={() => openDrilldown("workitems")} />
            <StatCard label="Weight Difference" value={weightDiffValue} source={`Scan events · ${weightDiffSub}`} onClick={() => openDrilldown("weight_difference")} />
            <StatCard label="Rush Pending Wash" value={shiftMetricValue(shift.rush_pending_wash, "rush")} source="Rush only · Scan events" onClick={() => openDrilldown("rush_pending_wash")} />
            <StatCard
              label="Last Rush Wash"
              value={shift.last_rush_wash ? formatDateTime(shift.last_rush_wash.at)?.split(",")[1]?.trim() || "—" : "—"}
              source="Rush only · Scan events"
              sub={shift.last_rush_wash ? `${shift.last_rush_wash.bag_id} · ${shift.last_rush_wash.user || ""}` : "No rush wash today"}
            />
            <StatCard label="Yet to Fold" value={shiftMetricValue(shift.yet_to_fold, rushFilter)} source="At Vendor staging" onClick={() => openDrilldown("yet_to_fold")} />
          </Section>

          <Box sx={{ mb: 3 }}>
            <RushFilterChips value={rushFilter} onChange={setRushFilter} />
            <Typography variant="h6" fontWeight={800} sx={{ mb: 1.5 }}>
              Employee Activity
            </Typography>
            {(data.employee_cards || []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {data.employee_diagnostics?.folding_averages_status || "No employee activity for this shift."}
              </Typography>
            ) : (
              (data.employee_cards || []).map((card) => <EmployeeCard key={card.employee} card={card} />)
            )}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              Source: Clock records + scan events (mapped / tenant staff only)
            </Typography>
          </Box>

          <Section title="Exceptions / Needs Review" rushFilter={rushFilter} onRushFilterChange={setRushFilter}>
            {Object.entries(exceptions).map(([key, ex]) => (
              <StatCard
                key={key}
                label={key.replace(/_/g, " ")}
                value={ex.count}
                source={ex.source}
                onClick={() => openDrilldown(ex.drilldown_filter)}
                active={filterTag === ex.drilldown_filter}
              />
            ))}
          </Section>

          <Accordion sx={{ mt: 2, boxShadow: "none", border: "1px solid", borderColor: "divider" }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography fontWeight={700}>Advanced / Debug</Typography>
            </AccordionSummary>
            <AccordionDetails>
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
