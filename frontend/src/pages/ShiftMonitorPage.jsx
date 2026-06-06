import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
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
import { getShiftAnalysisSimple } from "../api";
import { todayRange } from "../utils/foldingDateRange";
import { formatAppliedRangeSummary } from "../utils/foldingEasternDate";
import { formatDateTime, formatLaborHours, formatRate } from "../utils/foldingFormat";

const ShiftAnalysisAdvancedPanel = lazy(() => import("./ShiftAnalysisAdvancedPanel"));

const ACCENT = "#0097b2";

function MonitorNav() {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
      {[
        ["/performance/settings", "Settings"],
        ["/performance/user-mapping", "User mapping"],
        ["/performance/backfill", "Backfill"],
      ].map(([to, label]) => (
        <Button key={to} size="small" component={RouterLink} to={to} sx={{ textTransform: "none", fontWeight: 600 }}>
          {label}
        </Button>
      ))}
    </Stack>
  );
}

function StatCard({ label, value, source, sub, onClick, active, stale }) {
  const display = value ?? "—";
  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "2px solid",
        borderColor: active ? ACCENT : "divider",
        cursor: onClick ? "pointer" : "default",
        bgcolor: active ? "rgba(0,151,178,0.06)" : "background.paper",
        minHeight: 88,
      }}
    >
      <Typography variant="h4" fontWeight={800} lineHeight={1.1} color={ACCENT}>
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
        <Typography variant="caption" color={stale ? "warning.main" : "text.secondary"} display="block" sx={{ mt: 0.5 }}>
          Source: {source}
          {stale ? " · stale" : ""}
        </Typography>
      ) : null}
    </Paper>
  );
}

function Section({ title, children }) {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 1.5 }}>
        {title}
      </Typography>
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

function filterRecords(records, tag) {
  if (!tag) return records || [];
  return (records || []).filter((r) => (r.drilldown_tags || []).includes(tag));
}

function RecordRow({ row, expanded, onToggle }) {
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
          {row.weight_difference?.flagged ? (
            <Typography variant="caption" display="block" color="warning.main">
              Weight Δ {row.weight_difference.difference_lbs} lbs (threshold {row.weight_difference.threshold_lbs})
            </Typography>
          ) : null}
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
            {diag || `${formatLaborHours(card.performance_hours)} · ${formatRate(card.bags_per_hour)} bags/hr`}
          </Typography>
        </Box>
      </Stack>
      <Collapse in={open}>
        <Stack spacing={1} sx={{ mt: 1.5 }}>
          {(card.roles || []).map((role) => (
            <Box key={role.role} sx={{ p: 1, bgcolor: "action.hover", borderRadius: 1 }}>
              <Typography variant="body2" fontWeight={700}>
                {role.role} · {role.bags} bags
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {role.diagnostic || `${formatLaborHours(role.performance_hours)} perf hrs · ${formatRate(role.bags_per_hour)} bags/hr · last ${formatDateTime(role.last_activity_time)}`}
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
  const [filterTag, setFilterTag] = useState(searchParams.get("filter") || null);
  const [expandedBag, setExpandedBag] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const initialToday = todayRange();
  const [rangePreset, setRangePreset] = useState(() => {
    const ds = searchParams.get("date_start");
    return ds ? "custom" : "today";
  });
  const [dateStart, setDateStart] = useState(() => searchParams.get("date_start") || initialToday.start);
  const [dateEnd, setDateEnd] = useState(() => searchParams.get("date_end") || initialToday.end);

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
  const filtered = useMemo(() => filterRecords(records, filterTag), [records, filterTag]);

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

  const rfv = data?.ready_for_vendor || {};
  const active = data?.current_active_work || {};
  const shift = data?.shift_status || {};
  const exceptions = data?.exceptions_summary || {};
  const stalePresence = !rfv.last_refreshed_at;

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
            {formatAppliedRangeSummary({ dateStart, dateEnd, preset: rangePreset })} · ET
          </Typography>
        </Box>
        <MonitorNav />
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 2 }}>
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
      {loading && !data ? (
        <Typography variant="body2" color="text.secondary">Loading…</Typography>
      ) : null}

      {data ? (
        <>
          <Section title="Ready for Vendor">
            <StatCard label="Total" value={rfv.total} source={rfv.source} stale={stalePresence} sub={rfv.last_refreshed_at ? `Refreshed ${formatDateTime(rfv.last_refreshed_at)}` : "Refresh time unknown"} onClick={() => openDrilldown("ready_for_vendor")} active={filterTag === "ready_for_vendor"} />
            <StatCard label="Rush WF" value={rfv.rush_wf} source={rfv.source} onClick={() => openDrilldown("rfv_rush_wf")} active={filterTag === "rfv_rush_wf"} />
            <StatCard label="Rush HD" value={rfv.rush_hd} source={rfv.source} onClick={() => openDrilldown("rfv_rush_hd")} active={filterTag === "rfv_rush_hd"} />
            <StatCard label="Non-Rush WF" value={rfv.nonrush_wf} source={rfv.source} onClick={() => openDrilldown("rfv_nonrush_wf")} active={filterTag === "rfv_nonrush_wf"} />
            <StatCard label="Non-Rush HD" value={rfv.nonrush_hd} source={rfv.source} onClick={() => openDrilldown("rfv_nonrush_hd")} active={filterTag === "rfv_nonrush_hd"} />
            <StatCard label="Unknown / Review" value={rfv.unknown_needs_review} source={rfv.source} onClick={() => openDrilldown("rfv_unknown_needs_review")} active={filterTag === "rfv_unknown_needs_review"} />
          </Section>

          <Section title="Current Active Work">
            <StatCard label="Active Total" value={active.total} source={active.source} onClick={() => openDrilldown("active_work")} active={filterTag === "active_work"} />
            <StatCard label="Rush WF" value={active.rush_wf} source={active.source} onClick={() => openDrilldown("active_rush_wf")} />
            <StatCard label="Rush HD" value={active.rush_hd} source={active.source} onClick={() => openDrilldown("active_rush_hd")} />
            <StatCard label="Non-Rush WF" value={active.nonrush_wf} source={active.source} onClick={() => openDrilldown("active_nonrush_wf")} />
            <StatCard label="Non-Rush HD" value={active.nonrush_hd} source={active.source} onClick={() => openDrilldown("active_nonrush_hd")} />
            <StatCard label="Checkout Pending" value={active.checkout_pending} source="Checkout staging" onClick={() => openDrilldown("checkout_pending")} />
          </Section>

          <Section title="Shift Status">
            <StatCard label="Weighed" value={shift.weighed} source={shift.source} onClick={() => openDrilldown("shift_weighed")} />
            <StatCard label="Not Weighed" value={shift.not_weighed} source={shift.source} onClick={() => openDrilldown("shift_not_weighed")} />
            <StatCard label="Issues" value={shift.issues} source="Scan events" onClick={() => openDrilldown("issues")} />
            <StatCard label="Workitems" value={shift.workitems} source="Scan events" onClick={() => openDrilldown("workitems")} />
            <StatCard label="Weight Difference" value={shift.weight_difference} source={`Scan events · ≥${shift.weight_difference_threshold_lbs} lbs`} onClick={() => openDrilldown("weight_difference")} />
            <StatCard label="Rush Pending Wash" value={shift.rush_pending_wash} source="Scan events" onClick={() => openDrilldown("rush_pending_wash")} />
            <StatCard
              label="Last Rush Wash"
              value={shift.last_rush_wash ? formatDateTime(shift.last_rush_wash.at)?.split(",")[1]?.trim() || "—" : "—"}
              source="Scan events"
              sub={shift.last_rush_wash ? `${shift.last_rush_wash.bag_id} · ${shift.last_rush_wash.user || ""}` : "No rush wash today"}
            />
            <StatCard label="Yet to Fold" value={shift.yet_to_fold} source="Active staging" onClick={() => openDrilldown("yet_to_fold")} />
          </Section>

          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" fontWeight={800} sx={{ mb: 1.5 }}>
              Employee Activity
            </Typography>
            {(data.employee_cards || []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">No employee activity for this shift.</Typography>
            ) : (
              (data.employee_cards || []).map((card) => <EmployeeCard key={card.employee} card={card} />)
            )}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              Source: Clock records + scan events
            </Typography>
          </Box>

          <Section title="Exceptions / Needs Review">
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
            <AccordionDetails sx={{ p: 0 }}>
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
        {filterTag ? (
          <Chip label={filterTag} onDelete={() => { setFilterTag(null); setDrawerOpen(false); }} sx={{ mb: 1 }} />
        ) : null}
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
