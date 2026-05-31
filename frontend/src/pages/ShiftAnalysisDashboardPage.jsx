import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Collapse,
  Drawer,
  FormControlLabel,
  FormGroup,
  Grid,
  IconButton,
  Link,
  Paper,
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
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
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
import {
  CHECKOUT_STATUS_LABELS,
  exceptionLabel,
  formatExceptionList,
  formatOperationalFlags,
  formatStageDetail,
  lifecycleStatusLabel,
} from "../utils/shiftAnalysisLabels";

const SECTION_PAPER = {
  p: 2,
  mb: 2.5,
  borderRadius: 2,
  border: "1px solid",
  borderColor: "divider",
  boxShadow: "none",
};

function PerformanceAdminNav() {
  const linkSx = { textTransform: "none", fontWeight: 600, minWidth: "auto", px: 1 };
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" alignItems="center">
      <Button size="small" variant="text" component={RouterLink} to="/performance/settings" sx={linkSx}>
        Settings
      </Button>
      <Button size="small" variant="text" component={RouterLink} to="/performance/user-mapping" sx={linkSx}>
        User Mapping
      </Button>
      <Button size="small" variant="text" component={RouterLink} to="/performance/backfill" sx={linkSx}>
        Backfill
      </Button>
      <Button size="small" variant="text" component={RouterLink} to="/checkout" sx={linkSx}>
        Checkout
      </Button>
    </Stack>
  );
}

function CompactKpi({ label, value, onClick, accent = "#0097b2" }) {
  const display = value ?? 0;
  const n = Number(display);
  const clickable = onClick && Number.isFinite(n) && n > 0;
  return (
    <Paper
      elevation={0}
      variant="outlined"
      onClick={clickable ? onClick : undefined}
      sx={{
        p: 1.25,
        borderRadius: 2,
        cursor: clickable ? "pointer" : "default",
        borderTop: `3px solid ${accent}`,
        height: "100%",
        transition: "box-shadow 0.15s ease",
        "&:hover": clickable ? { bgcolor: "grey.50", boxShadow: 1 } : undefined,
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.2, display: "block" }}>
        {label}
      </Typography>
      <Typography variant="h5" fontWeight={800} sx={{ mt: 0.35, lineHeight: 1.1 }}>
        {display}
      </Typography>
    </Paper>
  );
}

function DrilldownBar({ drill, count, onClear }) {
  if (!drill) return null;
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1.5 }}>
      <Chip
        size="small"
        color="primary"
        variant="outlined"
        label={`Drilldown: ${drill.label || drill.source} — ${count} records`}
      />
      <Button size="small" variant="outlined" onClick={onClear}>
        Clear drilldown
      </Button>
    </Stack>
  );
}

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

function StatChip({ label, value, onClick, accent }) {
  return <CompactKpi label={label} value={value ?? 0} onClick={onClick} accent={accent} />;
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
  { field: "ASSIGNED_NOT_SENT_TO_VENDOR", filter: { lifecycle_status: "ASSIGNED_NOT_SENT_TO_VENDOR" }, label: "Assigned / Not Sent", statusKey: true },
  { field: "SENT_TO_VENDOR", filter: { lifecycle_status: "SENT_TO_VENDOR" }, label: "Sent to Vendor", statusKey: true },
  { field: "pending_weighing", filter: { lifecycle_group: "pending_weighing" }, label: "Pending Weighing" },
  { field: "weighed_not_started", filter: { lifecycle_group: "weighed_not_started" }, label: "Weighed / Not Started" },
  { field: "sorted_ready", filter: { lifecycle_group: "sorted_ready" }, label: "Sorted / Ready" },
  { field: "wash_dry", filter: { lifecycle_group: "wash_dry" }, label: "Wash / Dry" },
  { field: "folded", filter: { lifecycle_group: "folded" }, label: "Folded / Completed" },
  { field: "sent_to_rinse", filter: { lifecycle_group: "sent_to_rinse" }, label: "Sent to Rinse" },
  { field: "needs_review", filter: { lifecycle_filter: "needs_review" }, label: "Needs Review", topLevel: true },
  { field: "with_exceptions", filter: { lifecycle_filter: "exceptions" }, label: "Exceptions", topLevel: true },
];

function formatExceptionFlags(flags, labels = {}) {
  return formatExceptionList(flags, labels);
}

function LifecyclePendingTable({ groups, onDrilldown, showUnknownColumn }) {
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

  const groupCell = (groupKey, col) => {
    const g = groups?.[groupKey] || {};
    let val = 0;
    if (col.topLevel) {
      val = g[col.field] ?? 0;
    } else if (col.statusKey) {
      val = g.by_lifecycle_status?.[col.field] ?? 0;
    } else {
      val = g.by_lifecycle_group?.[col.field] ?? 0;
    }
    return cell(groupKey, val, col.filter);
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
                  {groupCell(key, col)}
                </TableCell>
              ))}
              {showUnknownColumn ? (
                <TableCell align="right">
                  {groupCell(key, { field: "unknown", filter: { lifecycle_group: "unknown" } })}
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
      <Typography variant="body2"><strong>Lifecycle:</strong> {lifecycleStatusLabel(row.current_lifecycle_status)}</Typography>
      <Typography variant="body2"><strong>Checkout:</strong> {CHECKOUT_STATUS_LABELS[row.checkout_status] || row.checkout_status || "—"}</Typography>
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
  const [expandedRows, setExpandedRows] = useState(() => new Set());
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
    setExpandedRows(new Set());
    setSearchTick((t) => t + 1);
  };

  const scrollToRecords = () => {
    document.getElementById("shift-records-section")?.scrollIntoView({ behavior: "smooth" });
  };

  const operationalRecords = summary?.operational?.records || [];
  const operationalStats = summary?.operational?.stats || {};
  const operationalLabels = summary?.operational?.stat_labels || {};

  const clearDrilldown = () => {
    setRecordDrill(null);
    setExpandedRows(new Set());
  };

  const applyRecordDrill = (drill) => {
    setRecordDrill(drill);
    setExpandedRows(new Set());
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
  const lifecycleStatusLabels = summary?.pending?.lifecycle_status_labels || {};

  const filterLifecycleRows = useCallback((rows, drill) => {
    if (!drill || drill.source !== "lifecycle") return rows;
    return (rows || []).filter((r) => {
      if (drill.group === "rush" && !r.rush) return false;
      if (drill.group === "non_rush" && r.rush) return false;
      if (drill.lifecycle_group && r.lifecycle_group !== drill.lifecycle_group) return false;
      if (drill.lifecycle_status && r.current_lifecycle_status !== drill.lifecycle_status) return false;
      if (drill.lifecycle_filter === "needs_review" && !r.needs_review) return false;
      if (drill.lifecycle_filter === "exceptions" && !(r.exception_flags || []).length) return false;
      if (drill.lifecycle_filter === "completed") {
        return ["FOLDED_COMPLETED", "SENT_TO_RINSE"].includes(r.current_lifecycle_status);
      }
      if (drill.lifecycle_filter === "pending") {
        return !["FOLDED_COMPLETED", "SENT_TO_RINSE"].includes(r.current_lifecycle_status);
      }
      if (drill.checkout_filter === "checkout_pending") {
        return r.rush && r.checkout_status === "NOT_CHECKED_OUT";
      }
      if (drill.checkout_filter === "checked_out") {
        return r.rush && r.checkout_status === "CHECKED_OUT";
      }
      if (drill.checkout_filter === "checkout_needs_review") {
        return r.rush && r.checkout_status === "CHECKOUT_NEEDS_REVIEW";
      }
      return true;
    });
  }, []);

  const lifecycleRows = useMemo(
    () => filterLifecycleRows(summary?.pending?.rows || [], recordDrill),
    [summary, recordDrill, filterLifecycleRows]
  );

  const displayRecords = useMemo(() => {
    if (!recordDrill) return [];
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
    return [];
  }, [records, operationalRecords, recordDrill, lifecycleRows]);

  const toggleRowExpanded = (rowKey) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(rowKey)) next.delete(rowKey);
      else next.add(rowKey);
      return next;
    });
  };

  const expandAllRows = () => {
    setExpandedRows(new Set(displayRecords.map((r) => `${r.activity || "folding"}-${r.bag_id}`)));
  };

  const collapseAllRows = () => setExpandedRows(new Set());

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

  const onLifecycleDrill = ({ group, lifecycle_group: lifecycleGroup, lifecycle_status: lifecycleStatus, lifecycle_filter: lifecycleFilter }) => {
    const groupLabel = group === "rush" ? "Rush" : group === "non_rush" ? "Non-Rush" : "Combined";
    let columnLabel = "All";
    if (lifecycleStatus) {
      columnLabel = lifecycleStatusLabel(lifecycleStatus, lifecycleStatusLabels);
    } else if (lifecycleGroup) {
      columnLabel = lifecycleGroupLabels[lifecycleGroup] || lifecycleGroup;
      if (lifecycleGroup === "folded") columnLabel = "Folded / Completed";
    } else if (lifecycleFilter === "completed") columnLabel = "Completed";
    else if (lifecycleFilter === "pending") columnLabel = "Pending";
    else if (lifecycleFilter === "needs_review") columnLabel = "Needs Review";
    else if (lifecycleFilter === "exceptions") columnLabel = "Exceptions";

    applyRecordDrill({
      source: "lifecycle",
      group,
      lifecycle_group: lifecycleGroup,
      lifecycle_status: lifecycleStatus,
      lifecycle_filter: lifecycleFilter,
      label: `${groupLabel} — ${columnLabel}`,
    });
  };

  const onOperationalDrill = (filter, label) => {
    applyRecordDrill({ source: "operational", filter, label });
  };

  const onCheckoutDrill = (checkoutFilter, label) => {
    applyRecordDrill({
      source: "lifecycle",
      group: "rush",
      checkout_filter: checkoutFilter,
      label: `Rush — ${label}`,
    });
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1400, mx: "auto" }}>
      <Stack direction={{ xs: "column", lg: "row" }} justifyContent="space-between" alignItems={{ xs: "stretch", lg: "flex-start" }} gap={2} mb={2}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h4" fontWeight={800} sx={{ lineHeight: 1.15 }}>
            Shift Analysis
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {formatAppliedRangeSummary({ dateStart: applied.dateStart, dateEnd: applied.dateEnd, preset: applied.preset })}
          </Typography>
          <Box sx={{ mt: 1 }}>
            <PerformanceAdminNav />
          </Box>
        </Box>
        <Stack spacing={1} alignItems={{ xs: "stretch", lg: "flex-end" }} sx={{ minWidth: { lg: 360 } }}>
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
          <Stack direction="row" spacing={0.75} flexWrap="wrap" justifyContent="flex-end">
            <Button variant="contained" size="small" onClick={handleSearch} disabled={loading}>Apply</Button>
            <Button variant="outlined" size="small" onClick={clearFilters} disabled={loading}>Clear</Button>
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

      {message.text ? (
        <Alert severity={message.type || "info"} sx={{ mb: 2 }} onClose={() => setMessage({ type: "", text: "" })}>
          {message.text}
        </Alert>
      ) : null}

      {/* Layer 2 — Lifecycle summary */}
      <Paper sx={SECTION_PAPER}>
        <Box sx={{ mb: 1.5 }}>
          <Typography variant="h6" fontWeight={700}>Production lifecycle</Typography>
          <Typography variant="caption" color="text.secondary">
            WF bags at vendor · {summary?.pending?.status_model || "lifecycle"}
            {summary?.pending?.evaluation_time ? ` · ${formatDateTime(summary.pending.evaluation_time)}` : ""}
          </Typography>
        </Box>

        <LifecyclePendingTable
          groups={pendingGroups}
          onDrilldown={onLifecycleDrill}
          showUnknownColumn={showUnknownColumn}
        />

        <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
          Rush facility checkout (operational)
        </Typography>
        <Grid container spacing={1.25}>
          {[
            ["checkout_pending", "Checkout Pending", "#b45309"],
            ["checked_out", "Checked Out", "#15803d"],
            ["checkout_needs_review", "Checkout Needs Review", "#dc2626"],
          ].map(([key, label, color]) => (
            <Grid item xs={12} sm={4} key={key}>
              <CompactKpi
                label={label}
                value={checkoutRush[key] ?? 0}
                accent={color}
                onClick={() => onCheckoutDrill(key, label)}
              />
            </Grid>
          ))}
        </Grid>

        <Accordion disableGutters elevation={0} sx={{ mt: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="caption" fontWeight={600}>Legacy bucket comparison (debug)</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <LegacyPendingTable legacyBuckets={summary?.pending?.legacy_buckets} />
          </AccordionDetails>
        </Accordion>
      </Paper>

      {/* Layer 3 — Team summary (single row, no repetition) */}
      <Paper sx={SECTION_PAPER}>
        <Typography variant="h6" fontWeight={700} gutterBottom>Team & labor</Typography>
        <Grid container spacing={1.25}>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Clocked hrs" value={formatLaborHours(overall.clocked_labor_hours, 1)} accent="#334155" />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Bags folded" value={formatCount(overall.total_bags_completed)} accent="#0097b2" onClick={() => applyRecordDrill({ source: "all", label: "All completed bags" })} />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Lbs folded" value={formatLbs(overall.total_lbs_folded)} accent="#0097b2" />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Scoring bags" value={formatCount(scoring.scoring_bags)} accent="#7c3aed" onClick={() => applyRecordDrill({ source: "scoring", inScoring: true, label: "Scoring records" })} />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Quality" value={formatPercent(scoring.scoring_quality_percent)} accent="#7c3aed" />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Folding bags/hr" value={formatRate(speed.folding?.bags_per_hour ?? overall.folding_bags_per_hour)} accent="#0f766e" />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Processing bags/hr" value={formatRate(speed.processing?.bags_per_hour ?? overall.processing_bags_per_hour)} accent="#0f766e" />
          </Grid>
          <Grid item xs={6} sm={4} md={2}>
            <CompactKpi label="Excluded" value={formatCount(scoring.excluded_records)} accent="#94a3b8" onClick={() => applyRecordDrill({ source: "scoring", inScoring: false, label: "Not-scoring records" })} />
          </Grid>
        </Grid>
      </Paper>

      {/* Operational exceptions — compact */}
      <Paper sx={SECTION_PAPER}>
        <Typography variant="h6" fontWeight={700} gutterBottom>Operational exceptions</Typography>
        <Grid container spacing={1.25}>
          {[
            "order_reject_no_start_cleaning_after_limit",
            "completed_without_final_clean_scan",
            "bags_with_issues",
            "bags_with_workitems",
            "bags_with_bulk_workitems",
          ].map((key) => (
            <Grid item xs={6} sm={4} md={2.4} key={key}>
              <CompactKpi
                label={operationalLabels[key] || key}
                value={operationalStats[key] ?? 0}
                accent="#dc2626"
                onClick={() => onOperationalDrill(key, operationalLabels[key] || key)}
              />
            </Grid>
          ))}
        </Grid>
      </Paper>

      {/* Layer 4 — Employees */}
      <Paper sx={SECTION_PAPER}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} gap={1.5} mb={1.5}>
          <Typography variant="h6" fontWeight={700}>Employee performance</Typography>
          <ToggleButtonGroup size="small" value={employeeView} exclusive onChange={(_, v) => v && setEmployeeView(v)}>
            <ToggleButton value="processing">Processing</ToggleButton>
            <ToggleButton value="folding">Folding</ToggleButton>
            <ToggleButton value="combined">Combined</ToggleButton>
          </ToggleButtonGroup>
        </Stack>
        {employeeView === "processing" ? (
          <FormGroup row sx={{ mb: 1.5 }}>
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
        ) : null}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Employee</TableCell>
              <TableCell align="right">Activity hrs</TableCell>
              <TableCell align="right">Bags</TableCell>
              <TableCell align="right">Lbs</TableCell>
              <TableCell align="right">Bags/hr</TableCell>
              <TableCell align="right">Lbs/hr</TableCell>
              <TableCell align="right">Needs review</TableCell>
              <TableCell align="right">Exceptions</TableCell>
              <TableCell align="right">Details</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(summary?.employees || []).map((row) => (
              <TableRow key={row.user_name} hover selected={selectedEmployee === row.user_name}>
                <TableCell>{row.user_name}</TableCell>
                <TableCell align="right">{formatLaborHours(row.clocked_hours, 1)}</TableCell>
                <TableCell align="right">{formatCount(row.overall_bags)}</TableCell>
                <TableCell align="right">{formatLbs(row.overall_lbs)}</TableCell>
                <TableCell align="right">{formatRate(row.overall_bags_per_hour)}</TableCell>
                <TableCell align="right">{formatRate(row.overall_lbs_per_hour)}</TableCell>
                <TableCell align="right">{formatCount(row.needs_review ?? 0)}</TableCell>
                <TableCell align="right">
                  {(row.exceptions ?? 0) > 0 ? (
                    <Link
                      component="button"
                      variant="body2"
                      onClick={() => {
                        setSelectedEmployee(row.user_name);
                        setRecordFiltersApplied((s) => ({ ...s, user_name: row.user_name }));
                        applyRecordDrill({ source: "exceptions", label: `Exceptions — ${row.user_name}` });
                        setSearchTick((t) => t + 1);
                      }}
                    >
                      {row.exceptions}
                    </Link>
                  ) : (
                    row.exceptions ?? 0
                  )}
                </TableCell>
                <TableCell align="right">
                  <Button
                    size="small"
                    onClick={() => {
                      setSelectedEmployee(row.user_name);
                      setRecordSearch((s) => ({ ...s, user_name: row.user_name }));
                      setRecordFiltersApplied((s) => ({ ...s, user_name: row.user_name }));
                      applyRecordDrill({ source: "employee", label: `Employee — ${row.user_name}`, user_name: row.user_name });
                      setSearchTick((t) => t + 1);
                    }}
                  >
                    Open
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!(summary?.employees || []).length ? (
              <TableRow><TableCell colSpan={9} align="center">No employee data for this range</TableCell></TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      {selectedEmployee ? (
        <Paper sx={SECTION_PAPER}>
          <Typography variant="subtitle1" fontWeight={700} gutterBottom>{selectedEmployee}</Typography>
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

      {/* Layer 5 — Records drilldown */}
      <Paper sx={SECTION_PAPER} id="shift-records-section">
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }} gap={1} mb={1}>
          <Typography variant="h6" fontWeight={700}>Records</Typography>
          {recordDrill ? (
            <Stack direction="row" spacing={0.75}>
              <Button size="small" onClick={expandAllRows}>Expand all</Button>
              <Button size="small" onClick={collapseAllRows}>Collapse all</Button>
            </Stack>
          ) : null}
        </Stack>

        <DrilldownBar drill={recordDrill} count={displayRecords.length} onClear={clearDrilldown} />

        {!recordDrill ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
            Click any lifecycle or operational stat above to drill down into matching records.
          </Typography>
        ) : (
          <>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} mb={1.5} flexWrap="wrap">
              <FoldingUserSelect label="Employee" value={recordSearch.user_name} onChange={(v) => setRecordSearch((s) => ({ ...s, user_name: v }))} />
              <TextField size="small" label="Bag ID" value={recordSearch.bag_id} onChange={(e) => setRecordSearch((s) => ({ ...s, bag_id: e.target.value }))} />
              <TextField size="small" label="Customer" value={recordSearch.customer} onChange={(e) => setRecordSearch((s) => ({ ...s, customer: e.target.value }))} />
              {recordDrill.source !== "lifecycle" ? (
                <Tabs value={recordTab} onChange={(_, v) => setRecordTab(v)} sx={{ minHeight: 36 }}>
                  <Tab value="all" label="All" sx={{ minHeight: 36, py: 0.5 }} />
                  <Tab value="scoring" label="Scoring" sx={{ minHeight: 36, py: 0.5 }} />
                  <Tab value="not_scoring" label="Not scoring" sx={{ minHeight: 36, py: 0.5 }} />
                  <Tab value="exceptions" label="Exceptions" sx={{ minHeight: 36, py: 0.5 }} />
                </Tabs>
              ) : null}
            </Stack>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell width={40} />
                  <TableCell>Bag ID</TableCell>
                  <TableCell>Customer</TableCell>
                  <TableCell>Rush</TableCell>
                  <TableCell>Lifecycle group</TableCell>
                  <TableCell>Lifecycle status</TableCell>
                  <TableCell>Status time</TableCell>
                  <TableCell>Needs review</TableCell>
                  <TableCell>Exceptions</TableCell>
                  <TableCell>Checkout status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {displayRecords.map((row) => {
                  const rowKey = `${row.activity || "folding"}-${row.bag_id}`;
                  const isOpen = expandedRows.has(rowKey);
                  const isLifecycle = row.activity === "lifecycle";
                  return (
                    <Fragment key={rowKey}>
                      <TableRow hover>
                        <TableCell>
                          <IconButton size="small" onClick={() => toggleRowExpanded(rowKey)} aria-label={isOpen ? "Collapse" : "Expand"}>
                            {isOpen ? <KeyboardArrowUpIcon fontSize="small" /> : <KeyboardArrowDownIcon fontSize="small" />}
                          </IconButton>
                        </TableCell>
                        <TableCell>{row.bag_id}</TableCell>
                        <TableCell>{row.customer || row.name_clean || "—"}</TableCell>
                        <TableCell>{row.rush_label || "—"}</TableCell>
                        <TableCell>{isLifecycle ? (row.lifecycle_group_label || lifecycleGroupLabels[row.lifecycle_group] || row.lifecycle_group) : (row.activity || "folding")}</TableCell>
                        <TableCell>
                          {isLifecycle
                            ? lifecycleStatusLabel(row.current_lifecycle_status, lifecycleStatusLabels)
                            : (row.exception_label || row.status || "—")}
                        </TableCell>
                        <TableCell>{formatDateTime(isLifecycle ? row.status_timestamp : row.folding_start_at)}</TableCell>
                        <TableCell>{row.needs_review ? "Yes" : "No"}</TableCell>
                        <TableCell>
                          {isLifecycle
                            ? formatExceptionFlags(row.exception_flags, lifecycleStatusLabels)
                            : (row.exception_code ? exceptionLabel(row.exception_code) : "—")}
                        </TableCell>
                        <TableCell>
                          {isLifecycle
                            ? (CHECKOUT_STATUS_LABELS[row.checkout_status] || row.checkout_status || "—")
                            : "—"}
                        </TableCell>
                        <TableCell align="right">
                          <Button size="small" onClick={() => openDrawer(row.bag_id, row)}>Timeline</Button>
                        </TableCell>
                      </TableRow>
                      <TableRow key={`${rowKey}-detail`}>
                        <TableCell colSpan={11} sx={{ py: 0, borderBottom: isOpen ? undefined : 0 }}>
                          <Collapse in={isOpen} timeout="auto" unmountOnExit>
                            <Box sx={{ py: 1.5, px: 1 }}>
                              {isLifecycle ? (
                                <Stack spacing={0.75}>
                                  {row.status_source_event ? (
                                    <Typography variant="body2">
                                      <strong>Status source:</strong>{" "}
                                      {row.status_source_event.purpose || "—"}
                                      {row.status_source_event.scanned_at ? ` @ ${formatDateTime(row.status_source_event.scanned_at)}` : ""}
                                      {row.status_source_event.user_name ? ` (${row.status_source_event.user_name})` : ""}
                                    </Typography>
                                  ) : null}
                                  <Typography variant="body2"><strong>Stage detail:</strong> {formatStageDetail(row.stage_detail)}</Typography>
                                  <Typography variant="body2"><strong>Operational flags:</strong> {formatOperationalFlags(row.operational_flags)}</Typography>
                                  <Typography variant="body2"><strong>Exception flags:</strong> {formatExceptionFlags(row.exception_flags, lifecycleStatusLabels)}</Typography>
                                  <Typography variant="body2"><strong>Checkout detail:</strong> {CHECKOUT_STATUS_LABELS[row.checkout_status] || row.checkout_status || "—"}</Typography>
                                  {row.stage_detail?.reject_after_create_issue ? (
                                    <Typography variant="body2"><strong>Reject detail:</strong> {row.stage_detail.reject_after_create_issue.reason || "—"}</Typography>
                                  ) : null}
                                </Stack>
                              ) : (
                                <Stack spacing={0.75}>
                                  <Typography variant="body2"><strong>Operator:</strong> {row.assigned_user_name || "—"}</Typography>
                                  <Typography variant="body2"><strong>Weight:</strong> {formatLbs(row.weight_lbs ?? row.registry_weight_num)}</Typography>
                                  <Typography variant="body2"><strong>Duration:</strong> {formatFoldingDuration(row.duration_seconds)}</Typography>
                                  <Typography variant="body2"><strong>In scoring:</strong> {row.in_scoring ? "Yes" : "No"}</Typography>
                                  {row.reason_not_scoring ? (
                                    <Typography variant="body2"><strong>Reason not scoring:</strong> {row.reason_not_scoring}</Typography>
                                  ) : null}
                                </Stack>
                              )}
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  );
                })}
                {!displayRecords.length ? (
                  <TableRow><TableCell colSpan={11} align="center">No records match this drilldown</TableCell></TableRow>
                ) : null}
              </TableBody>
            </Table>
          </>
        )}
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
