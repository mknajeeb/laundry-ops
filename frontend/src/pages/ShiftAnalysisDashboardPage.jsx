import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Drawer,
  FormControl,
  FormControlLabel,
  FormGroup,
  Grid,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import FoldingExceptionCell from "../components/folding/FoldingExceptionCell";
import FoldingDateRangeFilter from "../components/folding/FoldingDateRangeFilter";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import FoldingUserSelect from "../components/folding/FoldingUserSelect";
import EmployeeProductivitySection from "../components/folding/EmployeeProductivitySection";
import {
  getFoldingPerformanceDetail,
  getShiftAnalysisRecords,
  getShiftAnalysisSummary,
} from "../api";
import { defaultWeekRange, foldingRangeParams, todayRange } from "../utils/foldingDateRange";
import { formatAppliedRangeSummary } from "../utils/foldingEasternDate";
import {
  formatDateTime,
  formatFoldingDuration,
  formatFoldingHours,
  formatLbs,
  formatRate,
} from "../utils/foldingFormat";

function SummaryCard({ label, value, sub }) {
  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h5" fontWeight={700}>{value ?? "—"}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

function PendingTable({ groups, onDrilldown }) {
  const rows = [
    { key: "rush", label: "Rush" },
    { key: "non_rush", label: "Non-Rush" },
    { key: "combined", label: "Combined" },
  ];
  const cell = (group, field, bucket) => {
    const val = groups?.[group]?.[field] ?? 0;
    if (!onDrilldown || field === "total" || field === "completed" || val === 0) return val;
    return (
      <Link component="button" variant="body2" onClick={() => onDrilldown({ group, bucket: field === "pending" ? null : bucket || field })}>
        {val}
      </Link>
    );
  };
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Group</TableCell>
          <TableCell align="right">Total</TableCell>
          <TableCell align="right">Completed</TableCell>
          <TableCell align="right">Pending</TableCell>
          <TableCell align="right">Not Weighed</TableCell>
          <TableCell align="right">Weighed / Not Washed</TableCell>
          <TableCell align="right">In Washing</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map(({ key, label }) => (
          <TableRow key={key}>
            <TableCell>{label}</TableCell>
            <TableCell align="right">{groups?.[key]?.total ?? 0}</TableCell>
            <TableCell align="right">{groups?.[key]?.completed ?? 0}</TableCell>
            <TableCell align="right">{cell(key, "pending", null)}</TableCell>
            <TableCell align="right">{cell(key, "not_weighed", "not_weighed")}</TableCell>
            <TableCell align="right">{cell(key, "weighed_not_washed", "weighed_not_washed")}</TableCell>
            <TableCell align="right">{cell(key, "in_washing", "in_washing")}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const PROCESSING_ACTIVITIES = [
  { id: "weighing", label: "Weighing" },
  { id: "sorting", label: "Sorting" },
  { id: "wash_load", label: "Wash/load" },
];

function exportRecordsCsv(rows, filename = "shift-analysis-records.csv") {
  const headers = [
    "activity", "bag_id", "customer", "weight_lbs", "start", "end", "duration_seconds",
    "operator", "status", "in_scoring", "reason_not_scoring", "exception_code",
  ];
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(
      [
        "folding",
        JSON.stringify(r.bag_id || ""),
        JSON.stringify(r.name_clean || r.customer || ""),
        r.weight_lbs ?? r.registry_weight_num ?? "",
        r.folding_start_at ?? "",
        r.folding_end_at ?? "",
        r.duration_seconds ?? "",
        JSON.stringify(r.assigned_user_name || ""),
        JSON.stringify(r.status || ""),
        r.in_scoring ? "yes" : "no",
        JSON.stringify(r.reason_not_scoring || ""),
        JSON.stringify(r.exception_code || ""),
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

export default function ShiftAnalysisDashboardPage({ user }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialToday = todayRange();
  const [rangePreset, setRangePreset] = useState("today");
  const [dateStart, setDateStart] = useState(initialToday.start);
  const [dateEnd, setDateEnd] = useState(initialToday.end);
  const [listDateField, setListDateField] = useState("folding_work_date");
  const [applied, setApplied] = useState({
    preset: "today",
    dateStart: initialToday.start,
    dateEnd: initialToday.end,
    listDateField: "folding_work_date",
  });
  const [processingActs, setProcessingActs] = useState(["weighing", "sorting", "wash_load"]);
  const [employeeView, setEmployeeView] = useState(searchParams.get("activity") === "folding" ? "folding" : "processing");
  const [selectedEmployee, setSelectedEmployee] = useState(searchParams.get("user") || "");
  const [rushFilter, setRushFilter] = useState("combined");
  const [pendingDrill, setPendingDrill] = useState(null);
  const [recordTab, setRecordTab] = useState(
    searchParams.get("status") === "exception" ? "exceptions" : "all"
  );
  const [recordSearch, setRecordSearch] = useState({ bag_id: "", customer: "", user_name: "" });
  const [recordFiltersApplied, setRecordFiltersApplied] = useState({ bag_id: "", customer: "", user_name: "" });
  const [summary, setSummary] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [drawerBagId, setDrawerBagId] = useState(null);
  const [drawerDetail, setDrawerDetail] = useState(null);
  const [searchTick, setSearchTick] = useState(0);
  const initialSearch = useRef(false);

  const rangeParams = useMemo(
    () => foldingRangeParams({
      dateStart: applied.dateStart,
      dateEnd: applied.dateEnd,
      dateField: applied.listDateField,
    }),
    [applied]
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    setMessage({ type: "", text: "" });
    const scoringFilter =
      recordTab === "scoring" ? "scoring" : recordTab === "not_scoring" ? "not_scoring" : undefined;
    const status = recordTab === "exceptions" ? "EXCEPTION" : undefined;
    const recordParams = {
      ...rangeParams,
      limit: 500,
      user_name: selectedEmployee || recordFiltersApplied.user_name || undefined,
      bag_id: recordFiltersApplied.bag_id || undefined,
      customer: recordFiltersApplied.customer || undefined,
      scoring_filter: scoringFilter,
      status,
    };

    let summaryError = "";
    let recordsError = "";

    try {
      const sumRes = await getShiftAnalysisSummary({
        ...rangeParams,
        processing_activities: processingActs.join(","),
      });
      setSummary(sumRes.data);
    } catch (e) {
      summaryError = e?.response?.data?.error || e?.message || "Failed to load shift summary";
      setSummary(null);
    }

    try {
      const recRes = await getShiftAnalysisRecords(recordParams);
      setRecords(recRes.data?.rows || []);
    } catch (e) {
      recordsError = e?.response?.data?.error || e?.message || "Failed to load records";
      setRecords([]);
    }

    if (summaryError && recordsError) {
      setMessage({ type: "error", text: summaryError });
    } else if (summaryError || recordsError) {
      setMessage({
        type: "warning",
        text: summaryError || recordsError,
      });
    }

    setLoading(false);
  }, [rangeParams, processingActs, recordTab, selectedEmployee, recordFiltersApplied]);

  const handleSearch = () => {
    setApplied({ preset: rangePreset, dateStart, dateEnd, listDateField });
    setRecordFiltersApplied({ ...recordSearch });
    setSearchTick((t) => t + 1);
  };

  const clearFilters = () => {
    setRecordSearch({ bag_id: "", customer: "", user_name: "" });
    setRecordFiltersApplied({ bag_id: "", customer: "", user_name: "" });
    setSelectedEmployee("");
    setPendingDrill(null);
    setRushFilter("combined");
    setSearchTick((t) => t + 1);
  };

  useEffect(() => {
    if (searchParams.get("status") === "exception") setRecordTab("exceptions");
    const u = searchParams.get("user");
    if (u) setSelectedEmployee(u);
  }, [searchParams]);

  useEffect(() => {
    if (initialSearch.current) return;
    initialSearch.current = true;
    setSearchTick(1);
  }, []);

  useEffect(() => {
    if (searchTick < 1) return;
    loadData();
  }, [searchTick, loadData]);

  const pendingRows = useMemo(() => {
    const rows = summary?.pending?.rows || [];
    return rows.filter((r) => {
      if (rushFilter === "rush" && !r.rush) return false;
      if (rushFilter === "non_rush" && r.rush) return false;
      if (!pendingDrill) return true;
      if (pendingDrill.group && pendingDrill.group !== "combined") {
        const g = pendingDrill.group === "rush" ? r.rush : !r.rush;
        if (!g) return false;
      }
      if (pendingDrill.bucket === "not_weighed") return r.pending_bucket === "not_weighed";
      if (pendingDrill.bucket === "weighed_not_washed") return r.pending_bucket === "weighed_not_washed";
      if (pendingDrill.bucket === "in_washing") return r.pending_bucket === "in_washing";
      if (pendingDrill.bucket === "pending") return !r.is_completed;
      return true;
    });
  }, [summary, rushFilter, pendingDrill]);

  const displayRecords = useMemo(() => {
    if (!pendingDrill?.bag_ids) return records;
    const ids = new Set(pendingDrill.bag_ids);
    return records.filter((r) => ids.has(r.bag_id));
  }, [records, pendingDrill]);

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

  const overall = summary?.overall_production || {};
  const scoring = summary?.scoring_data || {};
  const speed = summary?.speed || {};
  const pendingGroups = summary?.pending?.groups || {};

  const onPendingDrill = ({ group, bucket }) => {
    setPendingDrill({ group, bucket });
    setRushFilter(group === "non_rush" ? "non_rush" : group === "rush" ? "rush" : "combined");
    const rows = (summary?.pending?.rows || []).filter((r) => {
      if (group === "rush" && !r.rush) return false;
      if (group === "non_rush" && r.rush) return false;
      if (bucket === "not_weighed") return r.pending_bucket === "not_weighed";
      if (bucket === "weighed_not_washed") return r.pending_bucket === "weighed_not_washed";
      if (bucket === "in_washing") return r.pending_bucket === "in_washing";
      if (bucket === "pending") return !r.is_completed;
      return true;
    });
    setPendingDrill({ group, bucket, bag_ids: rows.map((r) => r.bag_id) });
    document.getElementById("shift-records-section")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1500, mx: "auto" }}>
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems="flex-start" gap={2} mb={2}>
        <Box>
          <Typography variant="h4" fontWeight={800}>Shift Analysis Dashboard</Typography>
          <Typography variant="body2" color="text.secondary">
            Track pending work, completed work, labor hours, processing speed, folding speed, and employee performance.
          </Typography>
        </Box>
        <Stack spacing={1.5} alignItems="flex-end">
          <FoldingDateRangeFilter
            preset={rangePreset}
            onPresetChange={setRangePreset}
            dateStart={dateStart}
            dateEnd={dateEnd}
            onDateStartChange={setDateStart}
            onDateEndChange={setDateEnd}
            dateField={listDateField}
            onDateFieldChange={setListDateField}
          />
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Button variant="contained" size="small" onClick={handleSearch} disabled={loading}>Search</Button>
            <Button variant="outlined" size="small" onClick={clearFilters} disabled={loading}>Clear filters</Button>
            <Button variant="outlined" size="small" onClick={() => setSearchTick((t) => t + 1)} disabled={loading}>Refresh</Button>
            <Button variant="outlined" size="small" onClick={() => exportRecordsCsv(displayRecords, `shift-analysis-${applied.dateStart}.csv`)} disabled={!displayRecords.length}>
              Export
            </Button>
          </Stack>
        </Stack>
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {formatAppliedRangeSummary({ dateStart: applied.dateStart, dateEnd: applied.dateEnd, preset: applied.preset })}
        {summary?.pending?.completion_field ? ` · Completed = ${summary.pending.completion_field}` : ""}
      </Typography>

      {message.text ? (
        <Alert severity={message.type || "info"} sx={{ mb: 2 }} onClose={() => setMessage({ type: "", text: "" })}>
          {message.text}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="h6" fontWeight={700}>Pending order / bag status</Typography>
          <ToggleButtonGroup size="small" value={rushFilter} exclusive onChange={(_, v) => v && setRushFilter(v)}>
            <ToggleButton value="rush">Rush</ToggleButton>
            <ToggleButton value="non_rush">Non-Rush</ToggleButton>
            <ToggleButton value="combined">Combined</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        <PendingTable groups={pendingGroups} onDrilldown={onPendingDrill} />
        {pendingDrill ? (
          <Chip
            sx={{ mt: 1 }}
            label={`Pending drilldown: ${pendingDrill.group || "combined"} / ${pendingDrill.bucket || "all"} (${pendingRows.length} bags)`}
            onDelete={() => setPendingDrill(null)}
          />
        ) : null}
      </Paper>

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Team shift summary</Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}><SummaryCard label="Clocked labor hours" value={formatFoldingHours((overall.clocked_labor_hours || 0) * 3600)} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Processing labor hours" value={overall.processing_labor_hours} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Folding labor hours" value={overall.folding_labor_hours} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Bags completed" value={overall.total_bags_completed} sub={`Processed: ${overall.total_bags_processed ?? "—"}`} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Lbs folded" value={formatLbs(overall.total_lbs_folded)} sub={`Processed: ${formatLbs(overall.total_lbs_processed)}`} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Processing people" value={overall.processing_people_count} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Folding people" value={overall.folding_people_count} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Avg folding speed" value={formatRate(overall.folding_bags_per_hour)} sub="bags/hr" /></Grid>
      </Grid>

      <FormGroup row sx={{ mb: 2 }}>
        <Typography variant="body2" sx={{ mr: 2, alignSelf: "center" }}>Processing activities:</Typography>
        {PROCESSING_ACTIVITIES.map(({ id, label }) => (
          <FormControlLabel
            key={id}
            control={
              <Checkbox
                checked={processingActs.includes(id)}
                onChange={(e) => {
                  setProcessingActs((prev) =>
                    e.target.checked ? [...prev, id] : prev.filter((x) => x !== id)
                  );
                }}
              />
            }
            label={label}
          />
        ))}
      </FormGroup>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} gutterBottom>Overall Production</Typography>
            <Typography variant="body2">All bags: {overall.total_bags_completed ?? "—"} · All lbs: {formatLbs(overall.total_lbs_folded)}</Typography>
            <Typography variant="body2">All hours: {formatFoldingHours((overall.clocked_labor_hours || 0) * 3600)}</Typography>
            <Typography variant="body2">Processing speed: {formatRate(overall.processing_bags_per_hour)} bags/hr</Typography>
            <Typography variant="body2">Folding speed: {formatRate(overall.folding_bags_per_hour)} bags/hr</Typography>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} gutterBottom>Scoring Data</Typography>
            <Typography variant="body2">Scoring bags: {scoring.scoring_bags ?? "—"} · Scoring lbs: {formatLbs(scoring.scoring_lbs)}</Typography>
            <Typography variant="body2">Excluded records: {scoring.excluded_records ?? "—"}</Typography>
            <Typography variant="body2">Exceptions not counted: {scoring.exception_records_not_counted ?? "—"}</Typography>
            <Typography variant="body2">Scoring quality %: {scoring.scoring_quality_percent != null ? `${scoring.scoring_quality_percent}%` : "—"}</Typography>
          </Paper>
        </Grid>
      </Grid>

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Team speed</Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {["processing", "folding", "combined"].map((key) => (
          <Grid item xs={12} md={4} key={key}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} textTransform="capitalize">{key}</Typography>
              <Typography variant="body2">Bags/hr: {formatRate(speed[key]?.bags_per_hour)}</Typography>
              <Typography variant="body2">Lbs/hr: {formatRate(speed[key]?.lbs_per_hour)}</Typography>
              <Typography variant="body2">Min/bag: {formatRate(speed[key]?.minutes_per_bag, 1)}</Typography>
              <Typography variant="body2">People: {speed[key]?.people_count ?? "—"}</Typography>
              <Typography variant="body2">Labor hours: {speed[key]?.labor_hours ?? "—"}</Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems="center" gap={2} mb={2}>
          <Typography variant="h6" fontWeight={700}>Individual employees</Typography>
          <ToggleButtonGroup size="small" value={employeeView} exclusive onChange={(_, v) => v && setEmployeeView(v)}>
            <ToggleButton value="processing">Processing</ToggleButton>
            <ToggleButton value="folding">Folding</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell align="right">Clocked hrs</TableCell>
              <TableCell align="right">Overall bags</TableCell>
              <TableCell align="right">Scoring bags</TableCell>
              <TableCell align="right">Overall lbs</TableCell>
              <TableCell align="right">Scoring lbs</TableCell>
              <TableCell align="right">Overall bags/hr</TableCell>
              <TableCell align="right">Scoring bags/hr</TableCell>
              <TableCell align="right">Exceptions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(summary?.employees || []).map((row) => (
              <TableRow
                key={row.user_name}
                hover
                selected={selectedEmployee === row.user_name}
                sx={{ cursor: "pointer" }}
                onClick={() => {
                  setSelectedEmployee(row.user_name);
                  setRecordSearch((s) => ({ ...s, user_name: row.user_name }));
                  setRecordFiltersApplied((s) => ({ ...s, user_name: row.user_name }));
                  setSearchParams({ user: row.user_name, activity: employeeView });
                  setSearchTick((t) => t + 1);
                  document.getElementById("shift-records-section")?.scrollIntoView({ behavior: "smooth" });
                }}
              >
                <TableCell>{row.user_name}</TableCell>
                <TableCell align="right">{row.clocked_hours ?? "—"}</TableCell>
                <TableCell align="right">{row.overall_bags ?? "—"}</TableCell>
                <TableCell align="right">{row.scoring_bags ?? "—"}</TableCell>
                <TableCell align="right">{formatLbs(row.overall_lbs)}</TableCell>
                <TableCell align="right">{formatLbs(row.scoring_lbs)}</TableCell>
                <TableCell align="right">{formatRate(row.overall_bags_per_hour)}</TableCell>
                <TableCell align="right">{formatRate(row.scoring_bags_per_hour)}</TableCell>
                <TableCell align="right">{row.exceptions ?? 0}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      {selectedEmployee ? (
        <Paper sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>Employee detail — {selectedEmployee}</Typography>
          <EmployeeProductivitySection
            selectedEmployee={selectedEmployee}
            appliedDateStart={applied.dateStart}
            appliedDateEnd={applied.dateEnd}
            appliedListDateField={applied.listDateField}
            searchTick={searchTick}
            admin={false}
            onOpenTimeline={openDrawer}
          />
        </Paper>
      ) : null}

      <Paper sx={{ p: 2, mb: 3 }} id="shift-records-section">
        <Typography variant="h6" fontWeight={700} gutterBottom>Records & exceptions</Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} mb={2} flexWrap="wrap">
          <FoldingUserSelect label="Employee" value={recordSearch.user_name} onChange={(v) => setRecordSearch((s) => ({ ...s, user_name: v }))} />
          <TextField size="small" label="Bag ID" value={recordSearch.bag_id} onChange={(e) => setRecordSearch((s) => ({ ...s, bag_id: e.target.value }))} />
          <TextField size="small" label="Customer" value={recordSearch.customer} onChange={(e) => setRecordSearch((s) => ({ ...s, customer: e.target.value }))} />
          <Button variant="contained" size="small" onClick={handleSearch}>Search</Button>
          <Button variant="outlined" size="small" onClick={clearFilters}>Clear filters</Button>
        </Stack>
        <Tabs value={recordTab} onChange={(_, v) => setRecordTab(v)} sx={{ mb: 2 }}>
          <Tab value="all" label="All records" />
          <Tab value="scoring" label="Scoring records" />
          <Tab value="not_scoring" label="Not scoring" />
          <Tab value="exceptions" label="Exceptions / needs review" />
        </Tabs>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Activity</TableCell>
              <TableCell>Bag ID</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell>Weight</TableCell>
              <TableCell>Start</TableCell>
              <TableCell>End</TableCell>
              <TableCell>Duration</TableCell>
              <TableCell>Operator</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>In scoring</TableCell>
              <TableCell>Reason</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {displayRecords.map((row) => (
              <TableRow key={row.bag_id} hover>
                <TableCell>folding</TableCell>
                <TableCell>{row.bag_id}</TableCell>
                <TableCell>{row.name_clean || row.customer}</TableCell>
                <TableCell>{row.weight_lbs ?? row.registry_weight_num}</TableCell>
                <TableCell>{formatDateTime(row.folding_start_at)}</TableCell>
                <TableCell>{formatDateTime(row.folding_end_at)}</TableCell>
                <TableCell>{formatFoldingDuration(row.duration_seconds)}</TableCell>
                <TableCell>{row.assigned_user_name}</TableCell>
                <TableCell><FoldingExceptionCell row={row} /></TableCell>
                <TableCell>{row.in_scoring ? "Yes" : "No"}</TableCell>
                <TableCell>{row.reason_not_scoring || "—"}</TableCell>
                <TableCell><Button size="small" onClick={() => openDrawer(row.bag_id)}>Timeline</Button></TableCell>
              </TableRow>
            ))}
            {!displayRecords.length ? (
              <TableRow><TableCell colSpan={12} align="center">No records</TableCell></TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      <Drawer anchor="right" open={!!drawerBagId} onClose={() => setDrawerBagId(null)} PaperProps={{ sx: { width: { xs: "100%", sm: 480 } } }}>
        <Box sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Bag {drawerBagId}</Typography>
          {drawerDetail ? <FoldingScanEventsTable events={drawerDetail.scan_events || []} /> : <Typography variant="body2">Loading…</Typography>}
        </Box>
      </Drawer>
    </Box>
  );
}
