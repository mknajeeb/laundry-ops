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

function SummaryCard({ label, value, sub, onClick, clickable }) {
  const canClick = clickable && onClick && value != null && value !== "—" && Number(value) !== 0;
  return (
    <Paper
      sx={{
        p: 2,
        height: "100%",
        cursor: canClick ? "pointer" : "default",
        "&:hover": canClick ? { bgcolor: "action.hover" } : undefined,
      }}
      onClick={canClick ? onClick : undefined}
    >
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      {canClick ? (
        <Link component="span" variant="h5" fontWeight={700} underline="hover">{value}</Link>
      ) : (
        <Typography variant="h5" fontWeight={700}>{value ?? "—"}</Typography>
      )}
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

function filterOperationalRecordsClient(rows, filter) {
  if (!filter) return rows;
  return (rows || []).filter((row) => {
    const ws = row.workitem_stats || {};
    const codes = row.exception_codes || [];
    switch (filter) {
      case "order_reject_no_start_cleaning_30_min":
        return codes.includes("ORDER_REJECT_NO_START_CLEANING_30_MIN");
      case "completed_without_final_clean_scan":
        return codes.includes("COMPLETED_WITHOUT_FINAL_CLEAN_SCAN");
      case "bags_with_issues":
        return ws.has_issue;
      case "bags_with_workitems":
        return ws.has_workitem;
      case "bags_with_bulk_workitems":
        return ws.has_bulk_workitem;
      case "total_issue_events":
        return (ws.create_issue_count || 0) > 0;
      case "total_workitem_events":
        return (ws.create_workitem_count || 0) > 0;
      case "total_bulk_workitem_events":
        return (ws.create_bulk_workitem_count || 0) > 0;
      default:
        return true;
    }
  });
}

function OperationalDetailPanel({ row }) {
  const details = row?.exception_details || {};
  const reject = details.ORDER_REJECT_NO_START_CLEANING_30_MIN;
  const missingClean = details.COMPLETED_WITHOUT_FINAL_CLEAN_SCAN;
  return (
    <Stack spacing={2} sx={{ mb: 2 }}>
      <Typography variant="body2"><strong>Bag ID:</strong> {row.bag_id}</Typography>
      <Typography variant="body2"><strong>Customer:</strong> {row.customer || row.name_clean || "—"}</Typography>
      <Typography variant="body2"><strong>Rush:</strong> {row.rush_label || "—"}</Typography>
      <Typography variant="body2"><strong>Status:</strong> {row.status || "—"}</Typography>
      <Typography variant="body2"><strong>In scoring:</strong> {row.in_scoring ? "Yes" : "No"}</Typography>
      <Typography variant="body2"><strong>Reason not scoring:</strong> {row.reason_not_scoring || "—"}</Typography>
      {reject ? (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700}>{reject.exception_label}</Typography>
          <Typography variant="body2">Sorting/prep end: {formatDateTime(reject.sorting_prep_end_time)}</Typography>
          <Typography variant="body2">Expected latest start-cleaning: {formatDateTime(reject.expected_latest_start_cleaning_time)}</Typography>
          <Typography variant="body2">Actual start-cleaning: {formatDateTime(reject.actual_start_cleaning_time) || "None"}</Typography>
          <Typography variant="body2">Create-issue present: {reject.create_issue_present ? "Yes" : "No"}</Typography>
          <Typography variant="body2">Reason: {reject.reason}</Typography>
        </Paper>
      ) : null}
      {missingClean ? (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700}>{missingClean.exception_label}</Typography>
          <Typography variant="body2">PROCESSED BY VENDOR: {formatDateTime(missingClean.processed_by_vendor_at)}</Typography>
          <Typography variant="body2">CLEAN rack after processed: {missingClean.has_clean_rack_after_processed ? "Yes" : "No"}</Typography>
          <Typography variant="body2">Reason: {missingClean.reason}</Typography>
          {(missingClean.rack_scans_after_processed || []).length ? (
            <Typography variant="body2" component="div">
              Rack scans after processed:
              <ul style={{ margin: "4px 0 0 16px" }}>
                {missingClean.rack_scans_after_processed.map((s, i) => (
                  <li key={i}>{s.rack} @ {formatDateTime(s.scanned_at)} {s.contains_clean ? "(CLEAN)" : ""}</li>
                ))}
              </ul>
            </Typography>
          ) : (
            <Typography variant="body2">No rack scans after PROCESSED BY VENDOR</Typography>
          )}
        </Paper>
      ) : null}
    </Stack>
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
    if (!onDrilldown || val === 0) return val;
    return (
      <Link
        component="button"
        variant="body2"
        onClick={() =>
          onDrilldown({
            group,
            bucket:
              field === "pending"
                ? "pending"
                : field === "completed"
                  ? "completed"
                  : field === "total"
                    ? null
                    : bucket || field,
            pendingField: field,
          })
        }
      >
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
            <TableCell align="right">{cell(key, "total", null)}</TableCell>
            <TableCell align="right">{cell(key, "completed", "completed")}</TableCell>
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
  const [recordDrill, setRecordDrill] = useState(null);
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
  const [drawerRow, setDrawerRow] = useState(null);
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
    setRecordDrill(null);
    setRushFilter("combined");
    setSearchTick((t) => t + 1);
  };

  const scrollToRecords = () => {
    document.getElementById("shift-records-section")?.scrollIntoView({ behavior: "smooth" });
  };

  const operationalRecords = summary?.operational?.records || [];
  const operationalStats = summary?.operational?.stats || {};
  const operationalLabels = summary?.operational?.stat_labels || {};

  const applyRecordDrill = (drill) => {
    setRecordDrill(drill);
    scrollToRecords();
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

  const overall = summary?.overall_production || {};
  const scoring = summary?.scoring_data || {};
  const speed = summary?.speed || {};
  const pendingGroups = summary?.pending?.groups || {};

  const pendingRows = useMemo(() => {
    const rows = summary?.pending?.rows || [];
    return rows.filter((r) => {
      if (rushFilter === "rush" && !r.rush) return false;
      if (rushFilter === "non_rush" && r.rush) return false;
      if (recordDrill?.source !== "pending") return true;
      if (recordDrill.group && recordDrill.group !== "combined") {
        const g = recordDrill.group === "rush" ? r.rush : !r.rush;
        if (!g) return false;
      }
      if (recordDrill.bucket === "not_weighed") return r.pending_bucket === "not_weighed";
      if (recordDrill.bucket === "weighed_not_washed") return r.pending_bucket === "weighed_not_washed";
      if (recordDrill.bucket === "in_washing") return r.pending_bucket === "in_washing";
      if (recordDrill.bucket === "completed") return r.is_completed;
      if (recordDrill.bucket === "pending") return !r.is_completed;
      return true;
    });
  }, [summary, rushFilter, recordDrill]);

  const displayRecords = useMemo(() => {
    if (recordDrill?.source === "employee" && recordDrill.user_name) {
      return records.filter((r) => r.assigned_user_name === recordDrill.user_name);
    }
    if (recordDrill?.source === "operational") {
      return filterOperationalRecordsClient(operationalRecords, recordDrill.filter);
    }
    if (recordDrill?.source === "scoring") {
      return records.filter((r) => (recordDrill.inScoring ? r.in_scoring : !r.in_scoring));
    }
    if (recordDrill?.source === "exceptions") {
      const foldEx = records.filter((r) => r.status === "EXCEPTION");
      const opEx = operationalRecords.filter((r) => (r.exception_codes || []).length > 0);
      const seen = new Set(foldEx.map((r) => r.bag_id));
      return [...foldEx, ...opEx.filter((r) => !seen.has(r.bag_id))];
    }
    if (recordDrill?.bag_ids?.length) {
      const ids = new Set(recordDrill.bag_ids);
      const fromFolding = records.filter((r) => ids.has(r.bag_id));
      const fromOps = operationalRecords.filter((r) => ids.has(r.bag_id));
      const seen = new Set(fromFolding.map((r) => r.bag_id));
      return [...fromFolding, ...fromOps.filter((r) => !seen.has(r.bag_id))];
    }
    const seen = new Set(records.map((r) => r.bag_id));
    const extraOps = operationalRecords.filter((r) => (r.exception_codes || []).length && !seen.has(r.bag_id));
    return [...records, ...extraOps];
  }, [records, operationalRecords, recordDrill]);

  const openDrawer = async (bagId, row = null) => {
    setDrawerBagId(bagId);
    setDrawerRow(row);
    setDrawerDetail(null);
    try {
      const res = await getFoldingPerformanceDetail(bagId);
      setDrawerDetail(res.data);
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Could not load bag detail" });
    }
  };

  const onPendingDrill = ({ group, bucket }) => {
    setRushFilter(group === "non_rush" ? "non_rush" : group === "rush" ? "rush" : "combined");
    const rows = (summary?.pending?.rows || []).filter((r) => {
      if (group === "rush" && !r.rush) return false;
      if (group === "non_rush" && r.rush) return false;
      if (bucket === "not_weighed") return r.pending_bucket === "not_weighed";
      if (bucket === "weighed_not_washed") return r.pending_bucket === "weighed_not_washed";
      if (bucket === "in_washing") return r.pending_bucket === "in_washing";
      if (bucket === "completed") return r.is_completed;
      if (bucket === "pending") return !r.is_completed;
      return true;
    });
    applyRecordDrill({
      source: "pending",
      group,
      bucket,
      bag_ids: rows.map((r) => r.bag_id),
      label: `Pending ${group || "combined"} / ${bucket || "all"}`,
    });
  };

  const onOperationalDrill = (filter, label) => {
    applyRecordDrill({ source: "operational", filter, label });
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
          <Box>
            <Typography variant="h6" fontWeight={700}>Pending order / bag status</Typography>
            {summary?.pending?.service_scope ? (
              <Typography variant="caption" color="text.secondary">
                {summary.pending.service_scope}
                {summary.pending.portal_alignment?.hd_excluded
                  ? ` · ${summary.pending.portal_alignment.hd_excluded} HD excluded (${summary.pending.portal_alignment.portal_active_total} active in portal)`
                  : null}
              </Typography>
            ) : null}
          </Box>
          <ToggleButtonGroup size="small" value={rushFilter} exclusive onChange={(_, v) => v && setRushFilter(v)}>
            <ToggleButton value="rush">Rush</ToggleButton>
            <ToggleButton value="non_rush">Non-Rush</ToggleButton>
            <ToggleButton value="combined">Combined</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        <PendingTable groups={pendingGroups} onDrilldown={onPendingDrill} />
        {recordDrill ? (
          <Chip
            sx={{ mt: 1 }}
            label={`Drilldown: ${recordDrill.label || `${recordDrill.source} / ${recordDrill.filter || recordDrill.bucket || "all"}`} (${displayRecords.length} records)`}
            onDelete={() => setRecordDrill(null)}
          />
        ) : null}
      </Paper>

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Operational exceptions &amp; workitems</Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {[
          "order_reject_no_start_cleaning_30_min",
          "completed_without_final_clean_scan",
          "bags_with_issues",
          "bags_with_workitems",
          "bags_with_bulk_workitems",
          "total_issue_events",
          "total_workitem_events",
          "total_bulk_workitem_events",
        ].map((key) => (
          <Grid item xs={6} md={3} key={key}>
            <SummaryCard
              label={operationalLabels[key] || key}
              value={operationalStats[key] ?? 0}
              clickable
              onClick={() => onOperationalDrill(key, operationalLabels[key] || key)}
            />
          </Grid>
        ))}
      </Grid>

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Team shift summary</Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}><SummaryCard label="Clocked labor hours" value={formatFoldingHours((overall.clocked_labor_hours || 0) * 3600)} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Processing labor hours" value={overall.processing_labor_hours} /></Grid>
        <Grid item xs={6} md={3}><SummaryCard label="Folding labor hours" value={overall.folding_labor_hours} /></Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Bags completed"
            value={overall.total_bags_completed}
            sub={`Processed: ${overall.total_bags_processed ?? "—"}`}
            clickable
            onClick={() => applyRecordDrill({ source: "scoring", inScoring: true, label: "Scoring bags (completed folding)" })}
          />
        </Grid>
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
            <Typography variant="body2">
              Scoring bags:{" "}
              <Link component="button" variant="body2" onClick={() => applyRecordDrill({ source: "scoring", inScoring: true, label: "Scoring records" })}>
                {scoring.scoring_bags ?? "—"}
              </Link>
            </Typography>
            <Typography variant="body2">Scoring lbs: {formatLbs(scoring.scoring_lbs)}</Typography>
            <Typography variant="body2">
              Excluded records:{" "}
              <Link component="button" variant="body2" onClick={() => applyRecordDrill({ source: "scoring", inScoring: false, label: "Not-scoring records" })}>
                {scoring.excluded_records ?? "—"}
              </Link>
            </Typography>
            <Typography variant="body2">
              Exceptions not counted:{" "}
              <Link component="button" variant="body2" onClick={() => applyRecordDrill({ source: "exceptions", label: "All exceptions" })}>
                {scoring.exception_records_not_counted ?? "—"}
              </Link>
            </Typography>
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
                  applyRecordDrill({ source: "employee", bag_ids: null, label: `Employee: ${row.user_name}`, user_name: row.user_name });
                  setSearchTick((t) => t + 1);
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
                <TableCell align="right">
                  {(row.exceptions ?? 0) > 0 ? (
                    <Link
                      component="button"
                      variant="body2"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedEmployee(row.user_name);
                        setRecordFiltersApplied((s) => ({ ...s, user_name: row.user_name }));
                        applyRecordDrill({ source: "exceptions", label: `Exceptions: ${row.user_name}` });
                        setSearchTick((t) => t + 1);
                      }}
                    >
                      {row.exceptions}
                    </Link>
                  ) : (
                    row.exceptions ?? 0
                  )}
                </TableCell>
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
              <TableRow key={`${row.activity || "folding"}-${row.bag_id}`} hover sx={{ cursor: "pointer" }} onClick={() => openDrawer(row.bag_id, row)}>
                <TableCell>{row.activity || "folding"}</TableCell>
                <TableCell>{row.bag_id}</TableCell>
                <TableCell>{row.name_clean || row.customer}</TableCell>
                <TableCell>{row.weight_lbs ?? row.registry_weight_num}</TableCell>
                <TableCell>{formatDateTime(row.folding_start_at)}</TableCell>
                <TableCell>{formatDateTime(row.folding_end_at)}</TableCell>
                <TableCell>{formatFoldingDuration(row.duration_seconds)}</TableCell>
                <TableCell>{row.assigned_user_name || "—"}</TableCell>
                <TableCell>{row.exception_label || (row.status === "EXCEPTION" ? <FoldingExceptionCell row={row} /> : row.status)}</TableCell>
                <TableCell>{row.in_scoring ? "Yes" : "No"}</TableCell>
                <TableCell>{row.reason_not_scoring || "—"}</TableCell>
                <TableCell><Button size="small" onClick={(e) => { e.stopPropagation(); openDrawer(row.bag_id, row); }}>Timeline</Button></TableCell>
              </TableRow>
            ))}
            {!displayRecords.length ? (
              <TableRow><TableCell colSpan={12} align="center">No records</TableCell></TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      <Drawer anchor="right" open={!!drawerBagId} onClose={() => { setDrawerBagId(null); setDrawerRow(null); }} PaperProps={{ sx: { width: { xs: "100%", sm: 480 } } }}>
        <Box sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>Bag {drawerBagId}</Typography>
          {drawerRow?.activity === "operational" ? <OperationalDetailPanel row={drawerRow} /> : null}
          {drawerDetail ? <FoldingScanEventsTable events={drawerDetail.scan_events || []} /> : <Typography variant="body2">Loading…</Typography>}
        </Box>
      </Drawer>
    </Box>
  );
}
