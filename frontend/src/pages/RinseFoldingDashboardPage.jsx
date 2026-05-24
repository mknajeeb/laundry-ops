import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  getFoldingBenchmarks,
  getFoldingEmployeeAnalysis,
  getFoldingLeaderboard,
  getFoldingPerformanceDetail,
  listFoldingExceptions,
  listFoldingPerformance,
  overrideFoldingPerformance,
  recomputeFoldingPerformance,
  updateFoldingBenchmarks,
} from "../api";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import {
  comparisonArrow,
  formatComparison,
  formatDateTime,
  formatFoldingDuration,
  formatFoldingHours,
  formatLbs,
  formatPeriodRange,
  formatRate,
  isoDateInput,
  targetStatusChipColor,
} from "../utils/foldingFormat";

function exportEmployeesCsv(employees, filename = "folding-employees.csv") {
  const headers = [
    "employee",
    "bags",
    "total_lbs",
    "folding_hours",
    "bags_per_hour",
    "lbs_per_hour",
    "minutes_per_bag",
    "quality_percent",
    "issue_count",
    "target_status",
    "vs_prior_lbs_per_hour",
  ];
  const lines = [headers.join(",")];
  for (const e of employees) {
    const hours = e.total_folding_seconds ? (e.total_folding_seconds / 3600).toFixed(2) : "";
    lines.push(
      [
        JSON.stringify(e.user_name || ""),
        e.bag_count ?? "",
        e.total_lbs ?? "",
        hours,
        e.bags_per_hour ?? "",
        e.lbs_per_hour ?? "",
        e.avg_minutes_per_bag ?? "",
        e.issue_free_percent ?? "",
        e.issue_count ?? "",
        e.target_status ?? "",
        e.comparison?.lbs_per_hour?.delta ?? "",
      ].join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function isFoldingAdmin(user) {
  const roles = (user?.roles || []).map((r) => String(r).toUpperCase());
  return roles.some((r) => ["ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"].includes(r));
}

function SummaryCard({ label, value, sub }) {
  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h5" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

function RinseFoldingDashboardPage({ user }) {
  const admin = isFoldingAdmin(user);
  const today = isoDateInput();
  const weekAgo = isoDateInput(new Date(Date.now() - 6 * 86400000));

  const [period, setPeriod] = useState("week");
  const [anchorDate, setAnchorDate] = useState(today);
  const [customStart, setCustomStart] = useState(weekAgo);
  const [customEnd, setCustomEnd] = useState(today);
  const [leaderboard, setLeaderboard] = useState(null);
  const [employeeData, setEmployeeData] = useState(null);
  const [selectedEmployee, setSelectedEmployee] = useState("");
  const [records, setRecords] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [backfillOpen, setBackfillOpen] = useState(false);

  const [recomputeStart, setRecomputeStart] = useState(weekAgo);
  const [recomputeEnd, setRecomputeEnd] = useState(today);
  const [dateField, setDateField] = useState("date_clean");
  const [recomputeSummary, setRecomputeSummary] = useState(null);
  const [recomputing, setRecomputing] = useState(false);

  const [benchmarks, setBenchmarks] = useState(null);
  const [benchmarksOpen, setBenchmarksOpen] = useState(false);
  const [benchForm, setBenchForm] = useState({});

  const [drawerBagId, setDrawerBagId] = useState(null);
  const [drawerDetail, setDrawerDetail] = useState(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideBagId, setOverrideBagId] = useState(null);
  const [overrideForm, setOverrideForm] = useState({
    assigned_user_name: "",
    folding_start_at: "",
    folding_end_at: "",
    admin_notes: "",
    notes: "",
    excluded_from_performance: false,
  });

  const loadAll = useCallback(async () => {
    try {
      setLoading(true);
      setMessage({ type: "", text: "" });
      const lbPeriod = period === "custom" ? "week" : period;
      const empParams =
        period === "custom"
          ? { period: "custom", start_date: customStart, end_date: customEnd, ...(selectedEmployee ? { user_name: selectedEmployee } : {}) }
          : { period, date: anchorDate, ...(selectedEmployee ? { user_name: selectedEmployee } : {}) };
      const [lbRes, empRes, benchRes, exRes] = await Promise.all([
        getFoldingLeaderboard({ period: lbPeriod, date: period === "custom" ? customEnd : anchorDate }),
        getFoldingEmployeeAnalysis(empParams),
        getFoldingBenchmarks(),
        listFoldingExceptions({ limit: 500 }),
      ]);
      setLeaderboard(lbRes.data);
      setEmployeeData(empRes.data);
      setBenchmarks(benchRes.data);
      setBenchForm(benchRes.data || {});

      const ps = empRes.data?.period_start || lbRes.data?.period_start;
      const pe = empRes.data?.period_end || lbRes.data?.period_end;
      const recRes = await listFoldingPerformance({
        limit: 500,
        start_date: ps,
        end_date: pe,
        ...(selectedEmployee ? { user_name: selectedEmployee } : {}),
      });
      setRecords(recRes.data || []);
      setExceptions(exRes.data || []);
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || e?.message || "Failed to load folding data" });
    } finally {
      setLoading(false);
    }
  }, [anchorDate, period, customStart, customEnd, selectedEmployee]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const openDrawer = async (bagId) => {
    setDrawerBagId(bagId);
    setDrawerDetail(null);
    try {
      const res = await getFoldingPerformanceDetail(bagId);
      setDrawerDetail(res.data);
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Could not load bag detail" });
    }
  };

  const openOverride = (row, preExclude = false) => {
    const bid = row?.bag_id;
    if (!bid) return;
    setOverrideBagId(bid);
    setOverrideForm({
      assigned_user_name: row?.assigned_user_name || "",
      folding_start_at: row?.folding_start_at ? String(row.folding_start_at).slice(0, 16) : "",
      folding_end_at: row?.folding_end_at ? String(row.folding_end_at).slice(0, 16) : "",
      admin_notes: row?.admin_notes || "",
      notes: "",
      excluded_from_performance: preExclude,
    });
    setOverrideOpen(true);
  };

  const submitOverride = async () => {
    if (!overrideBagId) return;
    try {
      const body = {
        assigned_user_name: overrideForm.assigned_user_name || undefined,
        admin_notes: overrideForm.admin_notes || undefined,
        notes: overrideForm.notes || undefined,
        excluded_from_performance: overrideForm.excluded_from_performance,
      };
      if (overrideForm.folding_start_at) body.folding_start_at = new Date(overrideForm.folding_start_at).toISOString();
      if (overrideForm.folding_end_at) body.folding_end_at = new Date(overrideForm.folding_end_at).toISOString();
      await overrideFoldingPerformance(overrideBagId, body);
      setOverrideOpen(false);
      setMessage({ type: "success", text: `Override saved for ${overrideBagId}` });
      await loadAll();
      if (drawerBagId === overrideBagId) await openDrawer(overrideBagId);
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Override failed" });
    }
  };

  const runRecompute = async () => {
    try {
      setRecomputing(true);
      setRecomputeSummary(null);
      const res = await recomputeFoldingPerformance({ start_date: recomputeStart, end_date: recomputeEnd, date_field: dateField });
      setRecomputeSummary(res.data?.summary || null);
      setMessage({ type: "success", text: "Backfill recompute finished." });
      await loadAll();
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Recompute failed" });
    } finally {
      setRecomputing(false);
    }
  };

  const saveBenchmarks = async () => {
    try {
      await updateFoldingBenchmarks({
        bags_per_hour_target: parseFloat(benchForm.bags_per_hour_target),
        lbs_per_hour_target: parseFloat(benchForm.lbs_per_hour_target),
        minutes_per_bag_target: parseFloat(benchForm.minutes_per_bag_target),
        issue_free_percent_target: parseFloat(benchForm.issue_free_percent_target),
        week_start_day: benchForm.week_start_day,
      });
      setBenchmarksOpen(false);
      setMessage({ type: "success", text: "Benchmarks updated." });
      await loadAll();
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Failed to update benchmarks" });
    }
  };

  const team = leaderboard?.team || {};
  const bench = leaderboard?.benchmarks || benchmarks || {};
  const comp = leaderboard?.team_comparison || {};
  const staffRows = leaderboard?.users || [];
  const employees = employeeData?.employees || (employeeData?.employee ? [employeeData.employee] : []);
  const employeeBags = employeeData?.bags || [];

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1400, mx: "auto" }}>
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems="flex-start" gap={2} mb={2}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Folding Performance Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Metrics update when you confirm an upload batch (not on draft upload). Use backfill only for repair or history.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
          {period !== "custom" ? (
            <TextField type="date" size="small" label="Folding work date (period anchor)" value={anchorDate} onChange={(e) => setAnchorDate(e.target.value)} InputLabelProps={{ shrink: true }} helperText="Leaderboard period is based on folding work date" />
          ) : (
            <>
              <TextField type="date" size="small" label="Start" value={customStart} onChange={(e) => setCustomStart(e.target.value)} InputLabelProps={{ shrink: true }} />
              <TextField type="date" size="small" label="End" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
            </>
          )}
          <ToggleButtonGroup size="small" exclusive value={period} onChange={(_, v) => v && setPeriod(v)}>
            <ToggleButton value="week">This week</ToggleButton>
            <ToggleButton value="month">This month</ToggleButton>
            <ToggleButton value="custom">Custom range</ToggleButton>
          </ToggleButtonGroup>
          <Button variant="outlined" size="small" onClick={loadAll} disabled={loading}>Refresh</Button>
          <Button variant="outlined" size="small" onClick={() => exportEmployeesCsv(employees, `folding-${period}.csv`)} disabled={!employees.length}>
            Export CSV
          </Button>
          {admin ? <Button variant="text" size="small" onClick={() => setBackfillOpen((o) => !o)}>Backfill / Recompute</Button> : null}
        </Stack>
      </Stack>

      {message.text ? <Alert severity={message.type || "info"} sx={{ mb: 2 }} onClose={() => setMessage({ type: "", text: "" })}>{message.text}</Alert> : null}

      <Collapse in={backfillOpen && admin}>
        <Paper sx={{ p: 2, mb: 2, bgcolor: "grey.50" }}>
          <Typography variant="subtitle2" fontWeight={700} gutterBottom>Backfill / Recompute Performance</Typography>
          <Typography variant="caption" color="text.secondary" display="block" mb={1}>
            Not required for normal nightly uploads. Use for historical repair, testing, or after benchmark/override fixes.
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap">
            <TextField type="date" size="small" label="Start" value={recomputeStart} onChange={(e) => setRecomputeStart(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField type="date" size="small" label="End" value={recomputeEnd} onChange={(e) => setRecomputeEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Date field</InputLabel>
              <Select label="Date field" value={dateField} onChange={(e) => setDateField(e.target.value)}>
                <MenuItem value="date_clean">date_clean</MenuItem>
                <MenuItem value="completed_at">completed_at</MenuItem>
              </Select>
            </FormControl>
            <Button variant="contained" color="inherit" onClick={runRecompute} disabled={recomputing}>
              {recomputing ? "Running…" : "Run backfill"}
            </Button>
          </Stack>
          {recomputeSummary ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
              <Chip label={`Processed: ${recomputeSummary.processed ?? 0}`} size="small" />
              <Chip label={`Skipped: ${recomputeSummary.skipped_not_completed ?? 0}`} size="small" />
              <Chip label={`Calculated: ${recomputeSummary.calculated ?? 0}`} size="small" color="success" />
              <Chip label={`Exceptions: ${recomputeSummary.exceptions ?? 0}`} size="small" color="warning" />
            </Stack>
          ) : null}
        </Paper>
      </Collapse>

      <Typography variant="body2" color="text.secondary" mb={2}>
        {formatPeriodRange(employeeData?.period_start || leaderboard?.period_start, employeeData?.period_end || leaderboard?.period_end)}
        {leaderboard?.data_source_note ? ` · ${leaderboard.data_source_note}` : ""}
      </Typography>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={2}><SummaryCard label="Bags" value={team.bag_count ?? 0} sub={formatComparison(comp.bag_count)} /></Grid>
        <Grid item xs={6} md={2}><SummaryCard label="Total lbs" value={formatLbs(team.total_lbs)} /></Grid>
        <Grid item xs={6} md={2}><SummaryCard label="Hours" value={formatFoldingHours(team.total_folding_seconds)} /></Grid>
        <Grid item xs={6} md={2}><SummaryCard label="Bags/hr" value={formatRate(team.bags_per_hour)} sub={`Target ${formatRate(bench.bags_per_hour_target)} · ${formatComparison(comp.bags_per_hour)}`} /></Grid>
        <Grid item xs={6} md={2}><SummaryCard label="Lbs/hr" value={formatRate(team.lbs_per_hour)} sub={`Target ${formatRate(bench.lbs_per_hour_target)} · ${formatComparison(comp.lbs_per_hour)}`} /></Grid>
        <Grid item xs={6} md={2}>
          <SummaryCard
            label="Quality %"
            value={team.issue_free_percent != null ? `${formatRate(team.issue_free_percent, 1)}%` : "—"}
            sub={
              team.issue_count != null
                ? `${team.issue_count} issues · target ${formatRate(bench.issue_free_percent_target, 0)}% · ${formatComparison(comp.issue_free_percent, { suffix: "%" })}`
                : `Target ${formatRate(bench.issue_free_percent_target, 0)}% · ${formatComparison(comp.issue_free_percent, { suffix: "%" })}`
            }
          />
        </Grid>
      </Grid>

      {admin ? (
        <Paper sx={{ p: 2, mb: 3, border: "1px solid", borderColor: "primary.light", bgcolor: "rgba(0, 114, 206, 0.06)" }}>
          <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems="flex-start" gap={2}>
            <Box>
              <Typography variant="subtitle1" fontWeight={800}>Performance settings (benchmarks)</Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                TV and dashboard read these targets from the API — not hardcoded.
              </Typography>
            </Box>
            <Button variant="contained" size="small" onClick={() => setBenchmarksOpen(true)}>Edit settings</Button>
          </Stack>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={6} sm={4} md={2}><Typography variant="caption" color="text.secondary">Bags/hr target</Typography><Typography fontWeight={700}>{formatRate(bench.bags_per_hour_target)}</Typography></Grid>
            <Grid item xs={6} sm={4} md={2}><Typography variant="caption" color="text.secondary">Lbs/hr target</Typography><Typography fontWeight={700}>{formatRate(bench.lbs_per_hour_target)}</Typography></Grid>
            <Grid item xs={6} sm={4} md={2}><Typography variant="caption" color="text.secondary">Min/bag target</Typography><Typography fontWeight={700}>{formatRate(bench.minutes_per_bag_target)}</Typography></Grid>
            <Grid item xs={6} sm={4} md={2}><Typography variant="caption" color="text.secondary">Quality target</Typography><Typography fontWeight={700}>{formatRate(bench.issue_free_percent_target, 0)}%</Typography></Grid>
            <Grid item xs={6} sm={4} md={2}><Typography variant="caption" color="text.secondary">Week starts</Typography><Typography fontWeight={700}>{bench.week_start_day || "MONDAY"}</Typography></Grid>
          </Grid>
        </Paper>
      ) : null}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>Staff leaderboard</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Rank</TableCell><TableCell>Staff</TableCell><TableCell align="right">Bags</TableCell>
              <TableCell align="right">Lbs</TableCell><TableCell align="right">Lbs/hr</TableCell><TableCell align="right">Bags/hr</TableCell>
              <TableCell align="right">Quality</TableCell><TableCell>Target</TableCell><TableCell>vs prior</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {staffRows.length === 0 ? (
              <TableRow><TableCell colSpan={9} align="center">No calculated performance for this period.</TableCell></TableRow>
            ) : staffRows.map((u) => (
              <TableRow key={u.user_name} hover sx={{ cursor: "pointer" }} onClick={() => setSelectedEmployee(u.user_name)}>
                <TableCell>{u.rank}</TableCell><TableCell>{u.user_name}</TableCell>
                <TableCell align="right">{u.bag_count}</TableCell><TableCell align="right">{formatLbs(u.total_lbs)}</TableCell>
                <TableCell align="right">{formatRate(u.lbs_per_hour)}</TableCell><TableCell align="right">{formatRate(u.bags_per_hour)}</TableCell>
                <TableCell align="right">{u.issue_free_percent != null ? `${formatRate(u.issue_free_percent, 1)}%` : "—"}</TableCell>
                <TableCell><Chip size="small" label={u.target_status} color={targetStatusChipColor(u.target_status)} /></TableCell>
                <TableCell>{formatComparison(u.comparison?.lbs_per_hour)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1} flexWrap="wrap" gap={1}>
          <Typography variant="subtitle1" fontWeight={700}>Employee performance</Typography>
          <Stack direction="row" spacing={1}>
            {selectedEmployee ? <Button size="small" onClick={() => setSelectedEmployee("")}>Clear filter</Button> : null}
            <Button size="small" variant="outlined" onClick={() => exportEmployeesCsv(employees)} disabled={!employees.length}>Export</Button>
          </Stack>
        </Stack>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell align="right">Bags</TableCell>
              <TableCell align="right">Lbs</TableCell>
              <TableCell align="right">Hours</TableCell>
              <TableCell align="right">Bags/hr</TableCell>
              <TableCell align="right">Lbs/hr</TableCell>
              <TableCell align="right">Min/bag</TableCell>
              <TableCell align="right">Issues</TableCell>
              <TableCell align="right">Quality %</TableCell>
              <TableCell>Target</TableCell>
              <TableCell>vs prior</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {employees.length === 0 ? (
              <TableRow><TableCell colSpan={11} align="center">No employee data for this period.</TableCell></TableRow>
            ) : employees.map((e) => (
              <TableRow
                key={e.user_name}
                hover
                sx={{ cursor: "pointer" }}
                onClick={() => setSelectedEmployee(e.user_name)}
                selected={selectedEmployee === e.user_name}
              >
                <TableCell>{e.user_name}{e.rank ? ` (#${e.rank})` : ""}</TableCell>
                <TableCell align="right">{e.bag_count}</TableCell>
                <TableCell align="right">{formatLbs(e.total_lbs)}</TableCell>
                <TableCell align="right">{formatFoldingHours(e.total_folding_seconds)}</TableCell>
                <TableCell align="right">{formatRate(e.bags_per_hour)}</TableCell>
                <TableCell align="right">{formatRate(e.lbs_per_hour)}</TableCell>
                <TableCell align="right">{e.avg_minutes_per_bag != null ? formatRate(e.avg_minutes_per_bag) : "—"}</TableCell>
                <TableCell align="right">{e.issue_count ?? "—"}</TableCell>
                <TableCell align="right">{e.issue_free_percent != null ? `${formatRate(e.issue_free_percent, 1)}%` : "—"}</TableCell>
                <TableCell><Chip size="small" label={e.target_status} color={targetStatusChipColor(e.target_status)} /></TableCell>
                <TableCell>
                  {e.comparison?.lbs_per_hour?.available
                    ? `${comparisonArrow(e.comparison.lbs_per_hour.direction)} ${formatComparison(e.comparison.lbs_per_hour)}`
                    : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {selectedEmployee ? (
          <Box mt={3}>
            <Typography variant="subtitle2" fontWeight={700} mb={1}>Bags folded by {selectedEmployee}</Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Bag ID</TableCell>
                  <TableCell>Customer</TableCell>
                  <TableCell align="right">Weight</TableCell>
                  <TableCell>Folding start</TableCell>
                  <TableCell>Folding end</TableCell>
                  <TableCell>Duration</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Exception</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {employeeBags.length === 0 ? (
                  <TableRow><TableCell colSpan={9} align="center">No bags in period.</TableCell></TableRow>
                ) : employeeBags.map((r) => (
                  <TableRow key={r.bag_id} hover>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                    <TableCell>{r.name_clean || "—"}</TableCell>
                    <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : r.registry_weight_num != null ? formatLbs(r.registry_weight_num) : "—"}</TableCell>
                    <TableCell>{formatDateTime(r.folding_start_at)}</TableCell>
                    <TableCell>{formatDateTime(r.folding_end_at)}</TableCell>
                    <TableCell>{formatFoldingDuration(r.duration_seconds)}</TableCell>
                    <TableCell><Chip size="small" label={r.status} color={r.status === "CALCULATED" ? "success" : "warning"} /></TableCell>
                    <TableCell>{r.exception_code || "—"}</TableCell>
                    <TableCell><Button size="small" onClick={() => openDrawer(r.bag_id)}>Timeline</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        ) : null}
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>Folding records</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Bag</TableCell><TableCell>Customer</TableCell><TableCell>User</TableCell>
              <TableCell>Duration</TableCell><TableCell>Status</TableCell><TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {records.map((r) => (
              <TableRow key={r.bag_id} hover>
                <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                <TableCell>{r.name_clean || "—"}</TableCell>
                <TableCell>{r.assigned_user_name || "—"}</TableCell>
                <TableCell>{formatFoldingDuration(r.duration_seconds)}</TableCell>
                <TableCell><Chip size="small" label={r.status} color={r.status === "CALCULATED" ? "success" : "warning"} /></TableCell>
                <TableCell><Button size="small" onClick={() => openDrawer(r.bag_id)}>View</Button></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>Exceptions</Typography>
        <Table size="small">
          <TableHead><TableRow><TableCell>Bag</TableCell><TableCell>Code</TableCell><TableCell>User</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>
            {exceptions.map((r) => (
              <TableRow key={r.bag_id} hover>
                <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                <TableCell>{r.exception_code}</TableCell>
                <TableCell>{r.assigned_user_name || "—"}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5}>
                    <Button size="small" onClick={() => openDrawer(r.bag_id)}>View</Button>
                    {admin ? <Button size="small" onClick={() => openOverride(r)}>Override</Button> : null}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Drawer anchor="right" open={Boolean(drawerBagId)} onClose={() => setDrawerBagId(null)}>
        <Box sx={{ width: { xs: "100vw", sm: 480 }, p: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>Bag {drawerBagId}</Typography>
          {drawerDetail?.performance ? (
            <>
              <Typography variant="body2">Status: {drawerDetail.performance.status}</Typography>
              <Typography variant="body2">User: {drawerDetail.performance.assigned_user_name || "—"}</Typography>
              {admin ? <Button size="small" sx={{ mt: 1 }} onClick={() => openOverride(drawerDetail.performance)}>Override</Button> : null}
            </>
          ) : null}
          <Box mt={2}><FoldingScanEventsTable events={drawerDetail?.scan_events} /></Box>
        </Box>
      </Drawer>

      <Dialog open={overrideOpen} onClose={() => setOverrideOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Override — {overrideBagId}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Assigned user" value={overrideForm.assigned_user_name} onChange={(e) => setOverrideForm((f) => ({ ...f, assigned_user_name: e.target.value }))} fullWidth />
            <TextField label="Admin notes" value={overrideForm.admin_notes} onChange={(e) => setOverrideForm((f) => ({ ...f, admin_notes: e.target.value }))} fullWidth multiline />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOverrideOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitOverride}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={benchmarksOpen} onClose={() => setBenchmarksOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Performance settings</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {["bags_per_hour_target", "lbs_per_hour_target", "minutes_per_bag_target", "issue_free_percent_target"].map((k) => (
              <TextField key={k} label={k.replace(/_/g, " ")} type="number" value={benchForm[k] ?? ""} onChange={(e) => setBenchForm((f) => ({ ...f, [k]: e.target.value }))} fullWidth />
            ))}
            <FormControl fullWidth>
              <InputLabel>Week start day</InputLabel>
              <Select label="Week start day" value={benchForm.week_start_day || "MONDAY"} onChange={(e) => setBenchForm((f) => ({ ...f, week_start_day: e.target.value }))}>
                {["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"].map((d) => (
                  <MenuItem key={d} value={d}>{d}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBenchmarksOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveBenchmarks}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default RinseFoldingDashboardPage;
