import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
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
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
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
  formatCount,
  formatDateTime,
  formatFoldingDuration,
  formatLaborHours,
  formatLbs,
  formatPercent,
  formatRate,
} from "../utils/foldingFormat";

function KpiLine({ label, value, onClick }) {
  const clickable = onClick && value != null && value !== "—" && value !== 0 && value !== "0";
  return (
    <Typography variant="body2" sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
      <span>{label}</span>
      {clickable ? (
        <Link component="button" variant="body2" onClick={onClick} sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>
          {value}
        </Link>
      ) : (
        <span style={{ fontWeight: 600 }}>{value ?? "—"}</span>
      )}
    </Typography>
  );
}

function KpiCard({ title, children }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, height: "100%" }}>
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>{title}</Typography>
      <Stack spacing={0.75}>{children}</Stack>
    </Paper>
  );
}

function StatChip({ label, value, onClick }) {
  const n = Number(value);
  const clickable = onClick && Number.isFinite(n) && n > 0;
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        textAlign: "center",
        cursor: clickable ? "pointer" : "default",
        "&:hover": clickable ? { bgcolor: "action.hover" } : undefined,
      }}
      onClick={clickable ? onClick : undefined}
    >
      <Typography variant="caption" color="text.secondary" display="block" sx={{ lineHeight: 1.2, mb: 0.5 }}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={700}>{value ?? 0}</Typography>
    </Paper>
  );
}

function filterOperationalRecordsClient(rows, filter) {
  if (!filter) return rows;
  return (rows || []).filter((row) => {
    const ws = row.workitem_stats || {};
    const codes = row.exception_codes || [];
    switch (filter) {
      case "order_reject_no_start_cleaning_after_limit":
      case "order_reject_no_start_cleaning_30_min":
        return codes.includes("ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT")
          || codes.includes("ORDER_REJECT_NO_START_CLEANING_30_MIN");
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
  const reject = details.ORDER_REJECT_NO_START_CLEANING_AFTER_LIMIT || details.ORDER_REJECT_NO_START_CLEANING_30_MIN;
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
          <Typography variant="body2">Configured limit: {reject.configured_limit_minutes ?? "—"} min</Typography>
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

const LIFECYCLE_TABLE_ROWS = [
  { key: "rush", label: "Rush" },
  { key: "non_rush", label: "Non-Rush" },
  { key: "combined", label: "Combined" },
];

const LIFECYCLE_GROUP_COLUMNS = [
  { field: "pending_weighing", filter: { lifecycle_group: "pending_weighing" }, label: "Pending Weighing" },
  { field: "weighed_not_started", filter: { lifecycle_group: "weighed_not_started" }, label: "Weighed / Not Started" },
  { field: "sorted_ready", filter: { lifecycle_group: "sorted_ready" }, label: "Sorted / Ready" },
  { field: "wash_dry", filter: { lifecycle_group: "wash_dry" }, label: "Wash / Dry" },
  { field: "folded", filter: { lifecycle_group: "folded" }, label: "Folded" },
  { field: "sent_to_rinse", filter: { lifecycle_group: "sent_to_rinse" }, label: "Sent to Rinse" },
  { field: "needs_review", filter: { lifecycle_filter: "needs_review" }, label: "Needs Review", topLevel: true },
  { field: "with_exceptions", filter: { lifecycle_filter: "exceptions" }, label: "Exceptions", topLevel: true },
];

function formatExceptionFlags(flags, labels = {}) {
  const list = Array.isArray(flags) ? flags : [];
  if (!list.length) return "—";
  return list.map((c) => labels[c] || c.replace(/_/g, " ")).join(", ");
}

function formatOperationalFlags(flags) {
  const f = flags || {};
  const parts = [];
  if (f.has_create_issue) parts.push("create-issue");
  if (f.has_create_workitem) parts.push("workitem");
  if (f.has_create_bulk_workitem) parts.push("bulk workitem");
  if (f.has_workitem) parts.push("workitem (any)");
  return parts.length ? parts.join(", ") : "—";
}

function LifecyclePendingTable({ groups, groupLabels, onDrilldown, showUnknownColumn }) {
  const cell = (groupKey, val, filterExtra) => {
    if (!onDrilldown || !val) return val ?? 0;
    return (
      <Link
        component="button"
        variant="body2"
        onClick={() => onDrilldown({ group: groupKey, ...filterExtra })}
      >
        {val}
      </Link>
    );
  };

  const groupCell = (groupKey, field, filterExtra, topLevel = false) => {
    const g = groups?.[groupKey] || {};
    const val = topLevel ? (g[field] ?? 0) : (g.by_lifecycle_group?.[field] ?? 0);
    return cell(groupKey, val, filterExtra);
  };

  return (
    <Box sx={{ overflowX: "auto" }}>
      <Table size="small" sx={{ minWidth: 1100 }}>
        <TableHead>
          <TableRow>
            <TableCell>Group</TableCell>
            <TableCell align="right">Total</TableCell>
            <TableCell align="right">Completed</TableCell>
            <TableCell align="right">Pending</TableCell>
            {LIFECYCLE_GROUP_COLUMNS.map((col) => (
              <TableCell key={col.field} align="right">{col.label}</TableCell>
            ))}
            {showUnknownColumn ? <TableCell align="right">Unknown lifecycle</TableCell> : null}
          </TableRow>
        </TableHead>
        <TableBody>
          {LIFECYCLE_TABLE_ROWS.map(({ key, label }) => (
            <TableRow key={key}>
              <TableCell>{label}</TableCell>
              <TableCell align="right">{cell(key, groups?.[key]?.total ?? 0, { lifecycle_filter: null })}</TableCell>
              <TableCell align="right">{cell(key, groups?.[key]?.completed ?? 0, { lifecycle_filter: "completed" })}</TableCell>
              <TableCell align="right">{cell(key, groups?.[key]?.pending ?? 0, { lifecycle_filter: "pending" })}</TableCell>
              {LIFECYCLE_GROUP_COLUMNS.map((col) => (
                <TableCell key={col.field} align="right">
                  {groupCell(key, col.field, col.filter, col.topLevel)}
                </TableCell>
              ))}
              {showUnknownColumn ? (
                <TableCell align="right">
                  {groupCell(key, "unknown", { lifecycle_group: "unknown" })}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function LegacyPendingTable({ legacyBuckets }) {
  const groups = legacyBuckets || {};
  const rows = LIFECYCLE_TABLE_ROWS;
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
            <TableCell align="right">{groups?.[key]?.pending ?? 0}</TableCell>
            <TableCell align="right">{groups?.[key]?.not_weighed ?? 0}</TableCell>
            <TableCell align="right">{groups?.[key]?.weighed_not_washed ?? 0}</TableCell>
            <TableCell align="right">{groups?.[key]?.in_washing ?? 0}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function LifecycleDetailPanel({ row }) {
  const reject = row?.stage_detail?.reject_after_create_issue;
  return (
    <Stack spacing={1.5} sx={{ mb: 2 }}>
      <Typography variant="body2"><strong>Bag ID:</strong> {row.bag_id}</Typography>
      <Typography variant="body2"><strong>Customer:</strong> {row.customer || "—"}</Typography>
      <Typography variant="body2"><strong>Lifecycle:</strong> {row.lifecycle_status_label || row.current_lifecycle_status}</Typography>
      <Typography variant="body2"><strong>Checkout:</strong> {row.checkout_status || "—"}</Typography>
      <Typography variant="body2"><strong>Status time:</strong> {formatDateTime(row.status_timestamp)}</Typography>
      <Typography variant="body2"><strong>Exceptions:</strong> {formatExceptionFlags(row.exception_flags)}</Typography>
      {reject ? (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700}>Reject after create-issue</Typography>
          <Typography variant="body2">Rejected: {reject.order_rejected_full ? "Yes" : "No"}</Typography>
          <Typography variant="body2">Create-issue: {formatDateTime(reject.create_issue_time)}</Typography>
          <Typography variant="body2">Deadline: {formatDateTime(reject.reject_deadline)}</Typography>
          <Typography variant="body2">Evaluation: {formatDateTime(reject.evaluation_time)}</Typography>
        </Paper>
      ) : null}
    </Stack>
  );
}

const PROCESSING_ACTIVITIES = [
  { id: "weighing", label: "Weighing" },
  { id: "sorting", label: "Sorting" },
  { id: "wash_load", label: "Wash/load" },
];

function exportRecordsCsv(rows, filename = "shift-analysis-records.csv", { lifecycle = false } = {}) {
  const headers = lifecycle
    ? [
        "activity", "bag_id", "customer", "rush_label", "lifecycle_group", "current_lifecycle_status",
        "status_timestamp", "needs_review", "exception_flags", "checkout_status", "legacy_pending_bucket",
      ]
    : [
        "activity", "bag_id", "customer", "weight_lbs", "start", "end", "duration_seconds",
        "operator", "status", "in_scoring", "reason_not_scoring", "exception_code",
      ];
  const lines = [headers.join(",")];
  for (const r of rows) {
    if (lifecycle) {
      lines.push(
        [
          "lifecycle",
          JSON.stringify(r.bag_id || ""),
          JSON.stringify(r.customer || ""),
          JSON.stringify(r.rush_label || ""),
          JSON.stringify(r.lifecycle_group || ""),
          JSON.stringify(r.current_lifecycle_status || ""),
          r.status_timestamp ?? "",
          r.needs_review ? "yes" : "no",
          JSON.stringify((r.exception_flags || []).join(";")),
          JSON.stringify(r.checkout_status || ""),
          JSON.stringify(r.legacy_pending_bucket || ""),
        ].join(",")
      );
    } else {
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
  const lifecycleGroupLabels = summary?.pending?.lifecycle_group_labels || {};
  const showUnknownColumn = (pendingGroups.combined?.by_lifecycle_group?.unknown ?? 0) > 0;
  const checkoutRush = summary?.pending?.checkout_summary?.rush || {};
  const checkoutLabels = summary?.pending?.checkout_summary?.labels || {};

  const filterLifecycleRows = useCallback((rows, drill) => {
    if (!drill || drill.source !== "lifecycle") return rows;
    return (rows || []).filter((r) => {
      if (drill.group === "rush" && !r.rush) return false;
      if (drill.group === "non_rush" && r.rush) return false;
      if (drill.lifecycle_group && r.lifecycle_group !== drill.lifecycle_group) return false;
      if (drill.lifecycle_filter === "needs_review" && !r.needs_review) return false;
      if (drill.lifecycle_filter === "exceptions" && !(r.exception_flags || []).length) return false;
      if (drill.lifecycle_filter === "completed") {
        return ["FOLDED_COMPLETED", "SENT_TO_RINSE"].includes(r.current_lifecycle_status);
      }
      if (drill.lifecycle_filter === "pending") {
        return !["FOLDED_COMPLETED", "SENT_TO_RINSE"].includes(r.current_lifecycle_status);
      }
      return true;
    });
  }, []);

  const lifecycleRows = useMemo(
    () => filterLifecycleRows(summary?.pending?.rows || [], recordDrill),
    [summary, recordDrill, filterLifecycleRows]
  );

  const displayRecords = useMemo(() => {
    if (recordDrill?.source === "lifecycle") {
      return lifecycleRows.map((r) => ({ ...r, activity: "lifecycle" }));
    }
    if (recordDrill?.source === "all") {
      const seen = new Set(records.map((r) => r.bag_id));
      const extraOps = operationalRecords.filter((r) => !seen.has(r.bag_id));
      return [...records, ...extraOps];
    }
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
  }, [records, operationalRecords, recordDrill, lifecycleRows]);

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

  const onLifecycleDrill = ({ group, lifecycle_group: lifecycleGroup, lifecycle_filter: lifecycleFilter }) => {
    const groupLabel = group === "rush" ? "Rush" : group === "non_rush" ? "Non-Rush" : "Combined";
    let columnLabel = "All";
    if (lifecycleGroup) {
      columnLabel = lifecycleGroupLabels[lifecycleGroup] || lifecycleGroup;
    } else if (lifecycleFilter === "completed") columnLabel = "Completed";
    else if (lifecycleFilter === "pending") columnLabel = "Pending";
    else if (lifecycleFilter === "needs_review") columnLabel = "Needs Review";
    else if (lifecycleFilter === "exceptions") columnLabel = "Exceptions";

    setRushFilter(group === "non_rush" ? "non_rush" : group === "rush" ? "rush" : "combined");
    applyRecordDrill({
      source: "lifecycle",
      group,
      lifecycle_group: lifecycleGroup,
      lifecycle_filter: lifecycleFilter,
      label: `${groupLabel} — ${columnLabel}`,
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
            <Button variant="outlined" size="small" component={RouterLink} to="/performance/settings">Settings</Button>
            <Button variant="outlined" size="small" component={RouterLink} to="/performance/user-mapping">User mapping</Button>
            <Button variant="contained" size="small" onClick={handleSearch} disabled={loading}>Search</Button>
            <Button variant="outlined" size="small" onClick={clearFilters} disabled={loading}>Clear filters</Button>
            <Button variant="outlined" size="small" onClick={() => setSearchTick((t) => t + 1)} disabled={loading}>Refresh</Button>
            <Button
              variant="outlined"
              size="small"
              onClick={() => exportRecordsCsv(
                displayRecords,
                `shift-analysis-${applied.dateStart}.csv`,
                { lifecycle: recordDrill?.source === "lifecycle" }
              )}
              disabled={!displayRecords.length}
            >
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
            <Typography variant="h6" fontWeight={700}>Lifecycle bag status</Typography>
            {summary?.pending?.status_model ? (
              <Typography variant="caption" color="text.secondary" display="block">
                Model: {summary.pending.status_model}
                {summary.pending.evaluation_time ? ` · Eval: ${formatDateTime(summary.pending.evaluation_time)}` : ""}
              </Typography>
            ) : null}
            {summary?.pending?.service_scope ? (
              <Typography variant="caption" color="text.secondary">
                {summary.pending.service_scope}
                {summary.pending.portal_alignment?.hd_excluded
                  ? ` · ${summary.pending.portal_alignment.hd_excluded} HD excluded (${summary.pending.portal_alignment.portal_active_total} active in portal)`
                  : null}
                {summary?.pending?.completion_field ? ` · ${summary.pending.completion_field}` : ""}
              </Typography>
            ) : null}
          </Box>
          <ToggleButtonGroup size="small" value={rushFilter} exclusive onChange={(_, v) => v && setRushFilter(v)}>
            <ToggleButton value="rush">Rush</ToggleButton>
            <ToggleButton value="non_rush">Non-Rush</ToggleButton>
            <ToggleButton value="combined">Combined</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        <LifecyclePendingTable
          groups={pendingGroups}
          groupLabels={lifecycleGroupLabels}
          onDrilldown={onLifecycleDrill}
          showUnknownColumn={showUnknownColumn}
        />
        {recordDrill?.source === "lifecycle" ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
            <Chip
              label={`Drilldown: ${recordDrill.label || "Lifecycle"} (${lifecycleRows.length} records)`}
              onDelete={() => setRecordDrill(null)}
            />
            <Button size="small" onClick={() => setRecordDrill(null)}>Clear drilldown</Button>
          </Stack>
        ) : null}

        <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
          Facility checkout (Rush only — operational)
        </Typography>
        <Grid container spacing={1.5} sx={{ mb: 1 }}>
          {[
            ["checkout_pending", checkoutLabels.checkout_pending || "Rush checkout pending"],
            ["checked_out", checkoutLabels.checked_out || "Rush checked out"],
            ["checkout_needs_review", checkoutLabels.checkout_needs_review || "Checkout needs review"],
          ].map(([key, label]) => (
            <Grid item xs={12} sm={4} key={key}>
              <StatChip label={label} value={checkoutRush[key] ?? 0} />
            </Grid>
          ))}
        </Grid>

        <Accordion disableGutters elevation={0} sx={{ mt: 1, border: "1px solid", borderColor: "divider" }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2" fontWeight={600}>Legacy bucket comparison (debug)</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <LegacyPendingTable legacyBuckets={summary?.pending?.legacy_buckets} />
          </AccordionDetails>
        </Accordion>
      </Paper>

      {recordDrill?.source === "lifecycle" ? (
        <Paper sx={{ p: 2, mb: 3 }} id="shift-lifecycle-records-section">
          <Typography variant="h6" fontWeight={700} gutterBottom>Lifecycle records</Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Bag ID</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell>Rush / Non-Rush</TableCell>
                <TableCell>Lifecycle Group</TableCell>
                <TableCell>Current Lifecycle Status</TableCell>
                <TableCell>Status Time</TableCell>
                <TableCell>Needs Review</TableCell>
                <TableCell>Exception Flags</TableCell>
                <TableCell>Operational Flags</TableCell>
                <TableCell>Checkout Status</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {lifecycleRows.map((row) => (
                <TableRow
                  key={row.bag_id}
                  hover
                  sx={{ cursor: "pointer" }}
                  onClick={() => openDrawer(row.bag_id, { ...row, activity: "lifecycle" })}
                >
                  <TableCell>{row.bag_id}</TableCell>
                  <TableCell>{row.customer}</TableCell>
                  <TableCell>{row.rush_label}</TableCell>
                  <TableCell>{row.lifecycle_group_label || row.lifecycle_group}</TableCell>
                  <TableCell>{row.lifecycle_status_label || row.current_lifecycle_status}</TableCell>
                  <TableCell>{formatDateTime(row.status_timestamp)}</TableCell>
                  <TableCell>{row.needs_review ? "Yes" : "No"}</TableCell>
                  <TableCell>{formatExceptionFlags(row.exception_flags)}</TableCell>
                  <TableCell>{formatOperationalFlags(row.operational_flags)}</TableCell>
                  <TableCell>{row.checkout_status || "—"}</TableCell>
                  <TableCell>
                    <Button size="small" onClick={(e) => { e.stopPropagation(); openDrawer(row.bag_id, { ...row, activity: "lifecycle" }); }}>
                      Detail
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!lifecycleRows.length ? (
                <TableRow><TableCell colSpan={11} align="center">No lifecycle records for this drilldown</TableCell></TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Operational exceptions &amp; workitems</Typography>
      <Grid container spacing={1.5} sx={{ mb: 3 }}>
        {[
          "order_reject_no_start_cleaning_after_limit",
          "completed_without_final_clean_scan",
          "bags_with_issues",
          "bags_with_workitems",
          "bags_with_bulk_workitems",
          "total_issue_events",
          "total_workitem_events",
          "total_bulk_workitem_events",
        ].map((key) => (
          <Grid item xs={6} sm={4} md={3} key={key}>
            <StatChip
              label={operationalLabels[key] || key}
              value={operationalStats[key] ?? 0}
              onClick={() => onOperationalDrill(key, operationalLabels[key] || key)}
            />
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={4}>
          <KpiCard title="Overall Production">
            <KpiLine
              label="Bags"
              value={formatCount(overall.total_bags_completed)}
              onClick={() => applyRecordDrill({ source: "all", label: "All completed bags" })}
            />
            <KpiLine label="Lbs" value={formatLbs(overall.total_lbs_folded)} />
            <KpiLine label="Labor hrs" value={formatLaborHours(overall.clocked_labor_hours, 1)} />
            <KpiLine
              label="Processing speed"
              value={overall.processing_bags_per_hour != null ? `${formatRate(overall.processing_bags_per_hour)} bags/hr` : "—"}
            />
            <KpiLine
              label="Folding speed"
              value={overall.folding_bags_per_hour != null ? `${formatRate(overall.folding_bags_per_hour)} bags/hr` : "—"}
            />
          </KpiCard>
        </Grid>
        <Grid item xs={12} md={4}>
          <KpiCard title="Scoring Data">
            <KpiLine
              label="Bags scored"
              value={formatCount(scoring.scoring_bags)}
              onClick={() => applyRecordDrill({ source: "scoring", inScoring: true, label: "Scoring records" })}
            />
            <KpiLine label="Lbs scored" value={formatLbs(scoring.scoring_lbs)} />
            <KpiLine
              label="Excluded"
              value={formatCount(scoring.excluded_records)}
              onClick={() => applyRecordDrill({ source: "scoring", inScoring: false, label: "Not-scoring records" })}
            />
            <KpiLine
              label="Exceptions not counted"
              value={formatCount(scoring.exception_records_not_counted)}
              onClick={() => applyRecordDrill({ source: "exceptions", label: "Exceptions not counted" })}
            />
            <KpiLine label="Quality" value={formatPercent(scoring.scoring_quality_percent)} />
          </KpiCard>
        </Grid>
        <Grid item xs={12} md={4}>
          <KpiCard title="Labor summary">
            <KpiLine label="Clocked hrs" value={formatLaborHours(overall.clocked_labor_hours, 1)} />
            <KpiLine label="Processing hrs" value={formatLaborHours(overall.processing_labor_hours, 1)} />
            <KpiLine label="Folding hrs" value={formatLaborHours(overall.folding_labor_hours, 1)} />
            <KpiLine
              label="Processing people"
              value={formatCount(overall.processing_people_count)}
              onClick={() => { setEmployeeView("processing"); scrollToRecords(); }}
            />
            <KpiLine
              label="Folding people"
              value={formatCount(overall.folding_people_count)}
              onClick={() => { setEmployeeView("folding"); scrollToRecords(); }}
            />
          </KpiCard>
        </Grid>
      </Grid>

      <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
          Processing activities included
        </Typography>
        <FormGroup row sx={{ mb: 0.5 }}>
          {PROCESSING_ACTIVITIES.map(({ id, label }) => (
            <FormControlLabel
              key={id}
              control={
                <Checkbox
                  size="small"
                  checked={processingActs.includes(id)}
                  onChange={(e) => {
                    setProcessingActs((prev) =>
                      e.target.checked ? [...prev, id] : prev.filter((x) => x !== id)
                    );
                  }}
                />
              }
              label={<Typography variant="body2">{label}</Typography>}
            />
          ))}
        </FormGroup>
        <Typography variant="caption" color="text.secondary">
          Controls processing speed and processing activity-hour calculations.
        </Typography>
      </Paper>

      <Typography variant="subtitle1" fontWeight={700} gutterBottom>Team speed</Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={4}>
          <KpiCard title="Processing">
            <KpiLine label="Bags/hr" value={formatRate(speed.processing?.bags_per_hour)} />
            <KpiLine label="Lbs/hr" value={formatRate(speed.processing?.lbs_per_hour)} />
            <KpiLine label="Labor hrs" value={formatLaborHours(speed.processing?.labor_hours, 1)} />
            <KpiLine label="People" value={formatCount(speed.processing?.people_count)} />
          </KpiCard>
        </Grid>
        <Grid item xs={12} md={4}>
          <KpiCard title="Folding">
            <KpiLine label="Bags/hr" value={formatRate(speed.folding?.bags_per_hour)} />
            <KpiLine label="Lbs/hr" value={formatRate(speed.folding?.lbs_per_hour)} />
            <KpiLine label="Labor hrs" value={formatLaborHours(speed.folding?.labor_hours, 1)} />
            <KpiLine label="People" value={formatCount(speed.folding?.people_count)} />
            <KpiLine label="Min/bag" value={formatRate(speed.folding?.minutes_per_bag, 1)} />
          </KpiCard>
        </Grid>
        <Grid item xs={12} md={4}>
          <KpiCard title="Combined">
            {speed.combined?.bags_per_hour != null || speed.combined?.lbs_per_hour != null ? (
              <>
                <KpiLine label="Bags/hr" value={formatRate(speed.combined?.bags_per_hour)} />
                <KpiLine label="Lbs/hr" value={formatRate(speed.combined?.lbs_per_hour)} />
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">Combined metrics pending</Typography>
            )}
            <KpiLine label="Total labor hrs" value={formatLaborHours(speed.combined?.labor_hours ?? overall.clocked_labor_hours, 1)} />
            <KpiLine label="Total people" value={formatCount(speed.combined?.people_count)} />
          </KpiCard>
        </Grid>
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
          {drawerRow?.activity === "lifecycle" ? <LifecycleDetailPanel row={drawerRow} /> : null}
          {drawerRow?.activity === "operational" ? <OperationalDetailPanel row={drawerRow} /> : null}
          {drawerDetail ? <FoldingScanEventsTable events={drawerDetail.scan_events || []} /> : <Typography variant="body2">Loading…</Typography>}
        </Box>
      </Drawer>
    </Box>
  );
}
