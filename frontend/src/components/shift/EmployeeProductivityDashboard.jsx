import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  FormControl,
  InputLabel,
  ListItemText,
  MenuItem,
  OutlinedInput,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { getBulkWorkitems, getEmployeeProductivityBags, getEmployeeProductivityDashboard, getVeewashStep1BagDetail, postEmployeeBagSessionAssignment, postVeewashStep1Correction } from "../../api";
import CopyableBagId from "../CopyableBagId";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { yesterdayRange, todayRange } from "../../utils/foldingDateRange";
import {
  DEFAULT_ROLE_FILTER_KEY,
  PERFORMANCE_TIER_STYLES,
  PRODUCTIVITY_TABLE_COLUMNS,
  bagsWithMissingPre,
  buildExecutiveSummaryCards,
  employeeDisplayLbs,
  employeeHasFolderDualProductivity,
  employeeMatchesRoleFilter,
  filterSessionsByRole,
  fmtDurationMinutes,
  fmtProductivityPct,
  fmtProductivityRate,
  fmtSummaryNumber,
  isMissingClockIn,
  rankEmployees,
} from "../../utils/employeeProductivityHelpers";
import EmployeeProductivityDrilldown, {
  EmployeeProductivityDrilldownCollapse,
} from "./EmployeeProductivityDrilldown";
import EmployeeProductivityLaborSection from "./EmployeeProductivityLaborSection";
import EditBagPanel from "./EditBagPanel";
import RushFilterChips from "./RushFilterChips";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import MetricCardGrid from "./MetricCardGrid";
import { friendlyApiError } from "../../utils/shiftMonitorHelpers";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET Date" },
];

function SummaryMetricGrid({ items }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "repeat(2, minmax(0, 1fr))",
          sm: "repeat(4, minmax(0, 1fr))",
        },
        gap: 1,
      }}
    >
      {items.map((item, idx) => (
        <Box key={item.key || `${item.label}-${idx}`} sx={{ minWidth: 0, overflow: "hidden" }}>
          <Typography
            variant="caption"
            color="text.secondary"
            fontWeight={700}
            display="block"
            sx={{ whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.25 }}
          >
            {item.label}
          </Typography>
          <Typography variant="body2" fontWeight={700} sx={{ wordBreak: "break-word" }}>
            {item.value ?? "—"}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function fmtFoldHoursLabel(hours) {
  if (hours == null || Number.isNaN(Number(hours))) return null;
  const total = Math.max(0, Math.round(Number(hours) * 60));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h 00m`;
  return `${m}m`;
}

function FolderSegmentList({ segments, totalFoldHours }) {
  if (!Array.isArray(segments) || !segments.length) return null;
  const totalLabel = fmtFoldHoursLabel(totalFoldHours);
  return (
    <Box sx={{ mt: 1.25 }}>
      <Typography variant="caption" fontWeight={800} display="block" sx={{ mb: 0.75 }}>
        {totalLabel ? `Total Fold Time: ${totalLabel}` : "Folder Role Segments"}
      </Typography>
      {segments.length > 1 ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
          {segments.length} Fold sessions (summed for rate denominator — not last session only)
        </Typography>
      ) : null}
      <Stack spacing={0.75}>
        {segments.map((seg, idx) => {
          const startLabel = formatFriendlyEtWall(seg.segment_start) || "—";
          const endLabel =
            seg.segment_end_or_open === "Open"
              ? "Open"
              : formatFriendlyEtWall(seg.segment_end || seg.effective_role_end) || "—";
          const sessionDur = fmtFoldHoursLabel(seg.role_hours);
          return (
            <Box
              key={seg.segment_id || `${seg.segment_start}-${idx}`}
              sx={{
                p: 1,
                borderRadius: 1,
                border: "1px solid",
                borderColor: "divider",
                bgcolor: "#fff",
              }}
            >
              <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
                Session {idx + 1}
                {seg.role_status === "open" ? " · Open" : " · Closed"}
                {" · "}
                {startLabel} → {endLabel}
                {sessionDur ? ` · ${sessionDur}` : ""}
              </Typography>
              <SummaryMetricGrid
                items={[
                  { label: "Completed Bags", value: seg.completed_bags ?? 0 },
                  { label: "Credited Lbs", value: fmtSummaryNumber(seg.credited_lbs, 2) },
                  {
                    label: "Active Completion End",
                    value: formatFriendlyEtWall(seg.active_completion_end) || "—",
                  },
                  { label: "Role Hours", value: fmtSummaryNumber(seg.role_hours, 2) },
                  {
                    label: "Active Completion Hours",
                    value: fmtSummaryNumber(seg.active_completion_hours, 2),
                  },
                  { label: "Idle Time", value: fmtSummaryNumber(seg.idle_time_hours, 2) },
                ]}
              />
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}

function EmployeeSummaryPanel({ emp, onSendForReview, sendingReview = false, missingPreCount = 0 }) {
  const missingClockIn = isMissingClockIn(emp);
  const dual = employeeHasFolderDualProductivity(emp);
  const productiveHrs = emp.productive_hours ?? emp.worked_hours;
  const displayLbs =
    dual && emp.folder_credited_lbs != null ? emp.folder_credited_lbs : employeeDisplayLbs(emp);

  const reviewActions =
    typeof onSendForReview === "function" ? (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Button
          size="small"
          variant="contained"
          disabled={sendingReview || missingPreCount <= 0}
          onClick={(e) => {
            e.stopPropagation();
            onSendForReview();
          }}
          data-testid="employee-send-for-review"
        >
          {sendingReview
            ? "Sending…"
            : missingPreCount > 0
              ? `Send Missing PRE for Review (${missingPreCount})`
              : "Send for Review"}
        </Button>
        {missingPreCount > 0 ? (
          <Typography variant="caption" color="warning.main" fontWeight={700}>
            {missingPreCount} bag{missingPreCount === 1 ? "" : "s"} missing PRE credit
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary">
            No Missing PRE bags
          </Typography>
        )}
      </Stack>
    ) : null;

  if (dual) {
    const totalFoldHours = emp.role_hours ?? productiveHrs;
    const totalFoldLabel = fmtFoldHoursLabel(totalFoldHours);
    const roleItems = [
      {
        label: "Total Fold Time",
        value: totalFoldLabel || fmtSummaryNumber(totalFoldHours, 2),
      },
      { label: "Role Hours", value: fmtSummaryNumber(totalFoldHours, 2) },
      { label: "Role Bags / Hour", value: fmtProductivityRate(emp.role_bags_per_hour, false) },
      { label: "Role Lbs / Hour", value: fmtProductivityRate(emp.role_lbs_per_hour, false) },
      { label: "Role Productivity %", value: fmtProductivityPct(emp.role_productivity_pct) },
    ];
    const activeItems = [
      {
        label: "Active Completion Hours",
        value: fmtSummaryNumber(emp.active_completion_hours, 2),
      },
      { label: "Active Bags / Hour", value: fmtProductivityRate(emp.active_bags_per_hour, false) },
      { label: "Active Lbs / Hour", value: fmtProductivityRate(emp.active_lbs_per_hour, false) },
      { label: "Active Productivity %", value: fmtProductivityPct(emp.active_productivity_pct) },
    ];
    const roleStatusLabel =
      emp.role_status === "open"
        ? "Open"
        : emp.role_status === "unresolved" || emp.role_end_missing
          ? "Unresolved"
          : "Closed";
    const metaItems = [
      { label: "Completed Bags", value: emp.completed_bags ?? 0 },
      { label: "Credited Lbs (PRE)", value: displayLbs },
      {
        label: "Folding Target",
        value: `${fmtSummaryNumber(emp.folding_lbs_per_hour_target, 1)} lbs/hour`,
      },
      {
        label: "Folder Role Start",
        value: formatFriendlyEtWall(emp.folder_role_start) || "—",
      },
      {
        label: "Folder Role End",
        value:
          emp.role_status === "open" || emp.folder_role_end_display === "Open"
            ? "Open"
            : emp.role_end_missing || emp.folder_role_end_display === "Unresolved"
              ? "Unresolved"
              : formatFriendlyEtWall(emp.folder_role_end) || "—",
      },
      {
        label: "First Completed",
        value:
          formatFriendlyEtWall(
            emp.folder_first_completed || emp.first_completed_time_et || emp.first_completion_time,
          ) || "—",
      },
      {
        label: "Last Completed",
        value:
          formatFriendlyEtWall(
            emp.folder_last_completed || emp.last_completed_time_et || emp.last_completion_time,
          ) || "—",
      },
      {
        label: "Role Status",
        value: roleStatusLabel,
      },
      { label: "Sessions", value: emp.total_sessions ?? 0 },
      {
        label: "Session Time (all Fold)",
        value:
          totalFoldLabel
          || emp.total_session_label
          || fmtDurationMinutes(emp.total_session_minutes),
      },
      {
        label: "Idle Time",
        value:
          emp.total_idle_minutes != null
            ? (emp.total_idle_label || fmtDurationMinutes(emp.total_idle_minutes))
            : fmtSummaryNumber(emp.idle_time_hours, 2),
      },
      {
        label: "Idle %",
        value: emp.session_idle_pct != null ? `${Number(emp.session_idle_pct).toFixed(1)}%` : "—",
      },
    ];

    return (
      <Box
        sx={{
          mb: 1.25,
          p: 1.25,
          borderRadius: 1.5,
          border: "1px solid",
          borderColor: "divider",
          bgcolor: "#f8fafc",
        }}
      >
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
          Employee Summary
        </Typography>
        {reviewActions}
        {emp.rates_provisional || emp.role_end_missing ? (
          <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
            Role end unresolved — rates marked provisional; unresolved duration excluded from
            authoritative aggregates.
          </Alert>
        ) : null}
        <Typography variant="caption" fontWeight={800} display="block" sx={{ mb: 0.75 }}>
          Full Role Performance
        </Typography>
        <SummaryMetricGrid items={roleItems} />
        <Typography variant="caption" fontWeight={800} display="block" sx={{ mt: 1.25, mb: 0.75 }}>
          Through Last Completion
        </Typography>
        <SummaryMetricGrid items={activeItems} />
        <Typography variant="caption" fontWeight={800} display="block" sx={{ mt: 1.25, mb: 0.75 }}>
          Role Window
        </Typography>
        <SummaryMetricGrid items={metaItems} />
        <FolderSegmentList
          segments={emp.folder_role_segments}
          totalFoldHours={totalFoldHours}
        />
      </Box>
    );
  }

  const items = [
    { label: "Completed Bags", value: emp.completed_bags ?? 0 },
    { label: "Credited Lbs (PRE)", value: displayLbs },
    { label: "Productive Hours", value: missingClockIn ? "N/A" : fmtSummaryNumber(productiveHrs, 2) },
    { label: "Bags / Hr", value: fmtProductivityRate(emp.completed_bags_per_hour ?? emp.bags_per_hour, missingClockIn) },
    {
      label: "Employee Lbs / Hour (PRE)",
      value: fmtProductivityRate(emp.completed_lbs_per_hour ?? emp.lbs_per_hour, missingClockIn),
    },
    {
      label: "First Completed",
      value: formatFriendlyEtWall(emp.first_completed_time_et || emp.first_completion_time_et || emp.first_completion_time) || "—",
    },
    {
      label: "Last Completed",
      value: formatFriendlyEtWall(emp.last_completed_time_et || emp.last_completion_time_et || emp.last_completion_time) || "—",
    },
    { label: "Sessions", value: emp.total_sessions ?? 0 },
    {
      label: "Session Time",
      value: emp.total_session_label || fmtDurationMinutes(emp.total_session_minutes),
    },
    {
      label: "Idle Time",
      value: emp.total_idle_label || fmtDurationMinutes(emp.total_idle_minutes),
    },
    {
      label: "Idle %",
      value: emp.session_idle_pct != null ? `${Number(emp.session_idle_pct).toFixed(1)}%` : "—",
    },
  ];

  return (
    <Box
      sx={{
        mb: 1.25,
        p: 1.25,
        borderRadius: 1.5,
        border: "1px solid",
        borderColor: "divider",
        bgcolor: "#f8fafc",
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
        Employee Summary
      </Typography>
      {reviewActions}
      <SummaryMetricGrid items={items} />
    </Box>
  );
}

/**
 * Phase 2 — Employee Productivity Dashboard.
 * Reads frozen Phase 1 `employee_completed_bags_today` only.
 * Ranking is client-side; date changes fetch this section only.
 */
export default function EmployeeProductivityDashboard({
  initialSection,
  initialDateEt,
  rushFilter: rushFilterProp = "all",
  refreshToken = 0,
  onRushChange,
}) {
  const [expandedEmployee, setExpandedEmployee] = useState(null);
  const [reconOpen, setReconOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [rankBy, setRankBy] = useState("bags");
  const [sortDir, setSortDir] = useState("desc");
  const [roleFilterKeys, setRoleFilterKeys] = useState([DEFAULT_ROLE_FILTER_KEY]);
  const [rushFilter, setRushFilter] = useState(rushFilterProp || "all");
  const [datePreset, setDatePreset] = useState(() => resolvePreset(initialDateEt));
  const [customDate, setCustomDate] = useState(initialDateEt || todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(initialDateEt || todayRange().start);
  const [section, setSection] = useState(initialSection || null);
  const [laborSummary, setLaborSummary] = useState(null);
  const [scopeLabel, setScopeLabel] = useState(initialSection?.productivity_scope_label || "WF Only");
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");
  const [sendingReview, setSendingReview] = useState(false);
  const [assigningSession, setAssigningSession] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [reviewBag, setReviewBag] = useState(null);
  const [reviewCatalog, setReviewCatalog] = useState([]);
  const [reviewLoadingBagId, setReviewLoadingBagId] = useState(null);

  useEffect(() => {
    setRushFilter(rushFilterProp || "all");
  }, [rushFilterProp]);

  useEffect(() => {
    if (!initialDateEt || initialDateEt === activeDateEt) return;
    setActiveDateEt(initialDateEt);
    setDatePreset(resolvePreset(initialDateEt));
    setCustomDate(initialDateEt);
    setExpandedEmployee(null);
  }, [initialDateEt]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchSection = useCallback(async (dateEt, rush = rushFilterProp || "all", signal) => {
    if (!dateEt) return;
    setLoading(true);
    setFetchError("");
    try {
      const res = await getEmployeeProductivityDashboard(
        { date_et: dateEt, rush_filter: rush },
        signal ? { signal } : {},
      );
      setSection(res.data?.employee_completed_bags_today || null);
      setLaborSummary(res.data?.labor_summary || null);
      setScopeLabel(
        res.data?.productivity_scope_label
          || res.data?.employee_completed_bags_today?.productivity_scope_label
          || "WF Only",
      );
      setActiveDateEt(dateEt);
    } catch (e) {
      if (e?.code === "ERR_CANCELED" || e?.name === "CanceledError") return;
      setFetchError(
        friendlyApiError(e?.response?.data?.error, "Unable to load employee productivity."),
      );
      if (
        initialSection
        && !initialSection.bags_stripped_for_summary
        && dateEt === (initialDateEt || activeDateEt)
      ) {
        setSection(initialSection);
      }
    } finally {
      setLoading(false);
    }
  }, [activeDateEt, initialDateEt, initialSection, rushFilterProp]);

  useEffect(() => {
    const dateEt = initialDateEt || activeDateEt;
    if (!dateEt) return;
    const controller = new AbortController();
    // Defer so metric drawer / summary requests win the connection pool first.
    const timer = window.setTimeout(() => {
      fetchSection(dateEt, rushFilterProp || "all", controller.signal);
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [initialDateEt, rushFilterProp, refreshToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const employees = section?.employees || [];
  const executiveSummary = section?.executive_summary || {};
  const recon = section?.reconciliation || {};
  const banner = section?.reconciliation_banner || recon;
  const reconciled = banner.status === "reconciled" || recon.ok === true;
  const creditedAssigned = banner.employee_completed_bags_credited ?? recon.employee_attributed_bag_count ?? 0;
  const unassigned = recon.unassigned_count ?? 0;
  const creditedTotal = recon.credited_total ?? creditedAssigned + unassigned;
  const workload = banner.workload_completed_today ?? recon.workload_completed_today ?? 0;
  const selectedDate = section?.selected_date_et || activeDateEt;
  const productivityScopeLabel = section?.productivity_scope_label || scopeLabel || "WF Only";
  const expandedBagCount = (
    (section?.employees || []).find((e) => e.employee === expandedEmployee) || {}
  ).bags?.length || 0;

  useEffect(() => {
    if (!expandedEmployee || !selectedDate) return;
    if (expandedBagCount) return;
    const controller = new AbortController();
    (async () => {
      try {
        const res = await getEmployeeProductivityBags(
          {
            date_et: selectedDate,
            employee: expandedEmployee,
            rush_filter: rushFilter,
          },
          { signal: controller.signal },
        );
        const bags = res.data?.bags || [];
        const sessions = res.data?.sessions || [];
        setSection((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            employees: (prev.employees || []).map((row) =>
              row.employee === expandedEmployee
                ? { ...row, bags, sessions, bags_stripped_for_summary: false }
                : row
            ),
          };
        });
      } catch (e) {
        if (e?.code === "ERR_CANCELED" || e?.name === "CanceledError") return;
      }
    })();
    return () => controller.abort();
  }, [expandedEmployee, selectedDate, rushFilter, expandedBagCount]);

  const ensureReviewCatalog = useCallback(async () => {
    if (reviewCatalog.length) return reviewCatalog;
    try {
      const res = await getBulkWorkitems({ active_only: true });
      const rows = res?.data?.items || res?.data?.workitems || res?.data || [];
      const list = (Array.isArray(rows) ? rows : []).filter((w) => w?.active !== false);
      setReviewCatalog(list);
      return list;
    } catch (_) {
      return [];
    }
  }, [reviewCatalog]);

  const sendBagsForReview = useCallback(
    async (bags, { reasonCode = "MISSING_PRE_EVIDENCE" } = {}) => {
      const targets = (bags || []).filter((b) => b?.bag_id);
      if (!targets.length || !selectedDate) return { ok: false, sent: 0 };
      setSendingReview(true);
      setReviewError("");
      let sent = 0;
      const errors = [];
      try {
        for (const bag of targets) {
          try {
            const res = await postVeewashStep1Correction({
              action: "move_to_review",
              bag_id: bag.bag_id,
              selected_date_et: selectedDate,
              reason_code: reasonCode,
              reason:
                reasonCode === "MISSING_PRE_EVIDENCE"
                  ? "Missing PRE evidence — sent from employee productivity"
                  : "Manager sent bag for review from employee productivity",
            });
            if (res?.data?.ok) sent += 1;
            else errors.push(res?.data?.error || bag.bag_id);
          } catch (e) {
            errors.push(e?.response?.data?.error || e?.message || bag.bag_id);
          }
        }
        if (sent > 0) {
          await fetchSection(selectedDate, rushFilter);
        }
        if (errors.length) {
          setReviewError(
            friendlyApiError(errors[0], `Sent ${sent}; ${errors.length} failed.`),
          );
        }
        return { ok: errors.length === 0, sent, errors };
      } finally {
        setSendingReview(false);
      }
    },
    [fetchSection, rushFilter, selectedDate],
  );

  const openReviewBag = useCallback(
    async (bag) => {
      if (!bag?.bag_id || !selectedDate) return;
      setReviewError("");
      setReviewLoadingBagId(bag.bag_id);
      try {
        await ensureReviewCatalog();
        const res = await getVeewashStep1BagDetail({
          date: selectedDate,
          metric: "completed",
          queue: "completed",
          bag_id: bag.bag_id,
          include_details: true,
        });
        if (Array.isArray(res?.data?.active_bulk_workitems) && res.data.active_bulk_workitems.length) {
          setReviewCatalog(res.data.active_bulk_workitems);
        }
        const detail =
          (res?.data?.bags || []).find((b) => b.bag_id === bag.bag_id) || res?.data?.bags?.[0];
        setReviewBag({
          ...(detail || bag),
          ...bag,
          ...(detail || {}),
          _detailsLoaded: true,
          pre_weight_lbs:
            detail?.pre_weight_lbs ?? bag.evidence_pre_weight_lbs ?? bag.pre_weight_lbs ?? null,
          post_weight_lbs:
            detail?.post_weight_lbs ?? bag.evidence_post_weight_lbs ?? bag.post_weight_lbs ?? null,
          post_weight_value:
            detail?.post_weight_value ?? detail?.post_weight_lbs ?? bag.post_weight_lbs ?? null,
        });
      } catch (e) {
        setReviewError(
          friendlyApiError(e?.response?.data?.error || e?.message, "Unable to open bag review."),
        );
      } finally {
        setReviewLoadingBagId(null);
      }
    },
    [ensureReviewCatalog, selectedDate],
  );

  const rankedEmployees = useMemo(() => {
    const filtered = (employees || []).filter((emp) => employeeMatchesRoleFilter(emp, roleFilterKeys));
    return rankEmployees(filtered, rankBy, sortDir);
  }, [employees, rankBy, sortDir, roleFilterKeys]);
  const completedAttributionAudit = section?.completed_attribution_audit || section?.attribution_audit || [];
  const availableRoleFilters = useMemo(() => {
    const fromApi = section?.available_role_filters || [];
    if (fromApi.length) return fromApi;
    return [
      {
        key: DEFAULT_ROLE_FILTER_KEY,
        label: "Rinse WF — Folder",
        category: "Rinse WF",
        role: "Folder",
      },
    ];
  }, [section?.available_role_filters]);

  const handleSortColumn = (columnId) => {
    if (rankBy === columnId) {
      setSortDir((prev) => (prev === "desc" ? "asc" : "desc"));
      return;
    }
    setRankBy(columnId);
    setSortDir(columnId === "employee" ? "asc" : "desc");
  };

  const assignBagSession = useCallback(
    async (bag, sessionId) => {
      if (!bag?.bag_id || !selectedDate) return;
      setAssigningSession(true);
      setReviewError("");
      try {
        const sessions = filterSessionsByRole(
          (employees.find((e) => e.employee === expandedEmployee) || {}).sessions || [],
          roleFilterKeys,
        );
        const match = sessions.find((s) => s.session_id === sessionId);
        await postEmployeeBagSessionAssignment({
          bag_id: bag.bag_id,
          date_et: selectedDate,
          session_id: sessionId,
          segment_id: match?.segment_id ?? null,
          employee: expandedEmployee,
        });
        await fetchSection(selectedDate, rushFilter);
      } catch (e) {
        setReviewError(
          friendlyApiError(e?.response?.data?.error || e?.message, "Unable to save session assignment."),
        );
      } finally {
        setAssigningSession(false);
      }
    },
    [employees, expandedEmployee, fetchSection, roleFilterKeys, rushFilter, selectedDate],
  );

  const kpiCards = useMemo(
    () => buildExecutiveSummaryCards(executiveSummary, productivityScopeLabel),
    [executiveSummary, productivityScopeLabel],
  );

  const applyDate = (isoDate) => {
    if (!isoDate) return;
    setActiveDateEt(isoDate);
    setExpandedEmployee(null);
    fetchSection(isoDate, rushFilter);
  };

  const handleRushChange = (nextRush) => {
    setRushFilter(nextRush);
    onRushChange?.(nextRush);
    setExpandedEmployee(null);
    fetchSection(activeDateEt, nextRush);
  };

  const handleDatePreset = (_, value) => {
    if (!value) return;
    setDatePreset(value);
    if (value === "today") applyDate(todayRange().start);
    else if (value === "yesterday") applyDate(yesterdayRange().start);
    else if (value === "custom") setCustomDate(activeDateEt);
  };

  if (!section && loading) {
    return (
      <Paper elevation={0} sx={{ mt: 1.5, mb: 1.5, p: 2, borderRadius: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <CircularProgress size={20} />
          <Typography variant="body2" color="text.secondary" fontWeight={600}>
            Loading employee productivity…
          </Typography>
        </Stack>
      </Paper>
    );
  }

  if (!section && !loading && !fetchError) return null;

  return (
    <Paper
      elevation={0}
      sx={{
        mt: 1.5,
        mb: 1.5,
        borderRadius: 2,
        overflow: "hidden",
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#ffffff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Box
        sx={{
          px: { xs: 1.25, sm: 1.75 },
          py: { xs: 1, sm: 1.25 },
          bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
          color: "#fff",
        }}
      >
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }} spacing={0.75}>
          <Box>
            <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.0625rem" }}>
              Employee Productivity Dashboard
            </Typography>
            <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block" }}>
              ET {selectedDate || activeDateEt} · Completed production credit only
            </Typography>
          </Box>
          <Chip
            size="small"
            label={`Productivity Scope: ${productivityScopeLabel}`}
            sx={{
              bgcolor: "rgba(255,255,255,0.14)",
              color: "#fff",
              fontWeight: 700,
              border: "1px solid rgba(255,255,255,0.35)",
            }}
          />
        </Stack>
      </Box>

      <Box sx={{ p: { xs: 1, sm: 1.25 } }}>
        <Box sx={{ mb: 1.25, display: "flex", flexWrap: "wrap", gap: 1, alignItems: "center" }}>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={datePreset}
            onChange={handleDatePreset}
            sx={{ flexWrap: "wrap" }}
          >
            {DATE_PRESETS.map((p) => (
              <ToggleButton key={p.id} value={p.id} sx={{ textTransform: "none", fontWeight: 600 }}>
                {p.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          {datePreset === "custom" ? (
            <>
              <TextField
                type="date"
                size="small"
                label="Custom ET Date"
                value={customDate || ""}
                onChange={(e) => setCustomDate(e.target.value)}
                InputLabelProps={{ shrink: true }}
                sx={{ width: 170 }}
              />
              <Typography
                component="button"
                type="button"
                onClick={() => customDate && applyDate(customDate)}
                disabled={loading || !customDate}
                sx={{
                  border: "1px solid",
                  borderColor: "divider",
                  borderRadius: 1,
                  px: 1.25,
                  py: 0.5,
                  fontSize: 13,
                  fontWeight: 600,
                  bgcolor: "background.paper",
                  cursor: loading || !customDate ? "not-allowed" : "pointer",
                }}
              >
                Apply
              </Typography>
            </>
          ) : null}
          {loading ? <CircularProgress size={18} /> : null}
          <RushFilterChips value={rushFilter} onChange={handleRushChange} disabled={loading} />
          <FormControl size="small" sx={{ minWidth: { xs: "100%", sm: 240 } }}>
            <InputLabel id="productivity-role-filter-label">Role filter</InputLabel>
            <Select
              labelId="productivity-role-filter-label"
              multiple
              value={roleFilterKeys}
              onChange={(e) => {
                const next = typeof e.target.value === "string"
                  ? e.target.value.split(",")
                  : e.target.value;
                setRoleFilterKeys(next.length ? next : [DEFAULT_ROLE_FILTER_KEY]);
              }}
              input={<OutlinedInput label="Role filter" />}
              renderValue={(selected) =>
                availableRoleFilters
                  .filter((r) => selected.includes(r.key))
                  .map((r) => r.label)
                  .join(", ") || "Rinse WF — Folder"
              }
            >
              {availableRoleFilters.map((opt) => (
                <MenuItem key={opt.key} value={opt.key}>
                  <Checkbox checked={roleFilterKeys.includes(opt.key)} size="small" />
                  <ListItemText primary={opt.label} />
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>

        {fetchError ? (
          <Alert severity="error" sx={{ mb: 1.25 }}>{fetchError}</Alert>
        ) : null}
        {executiveSummary.missing_weight_warning ? (
          <Alert severity="warning" sx={{ mb: 1.25 }}>
            {executiveSummary.missing_weight_warning}
          </Alert>
        ) : null}

        <Box sx={{ mb: 1.5 }}>
          <MetricCardGrid
            sections={[
              {
                key: "kpi",
                layout: "kpi",
                cards: kpiCards.map((card) => ({
                  ...card,
                  count: card.value,
                  size: "kpi",
                })),
              },
            ]}
          />
        </Box>

        <EmployeeProductivityLaborSection laborSummary={laborSummary} />

        <Box sx={{ mb: 1.25 }}>
          <Typography
            variant="caption"
            color={reconciled ? "text.secondary" : "error.main"}
            onClick={() => setReconOpen((v) => !v)}
            sx={{
              cursor: "pointer",
              userSelect: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 0.35,
              fontWeight: 600,
            }}
          >
            <ExpandMoreIcon
              fontSize="inherit"
              sx={{
                transform: reconOpen ? "rotate(180deg)" : "rotate(-90deg)",
                transition: "transform 0.2s",
              }}
            />
            Reconciliation diagnostic
            {!reconOpen ? (
              <Typography component="span" variant="caption" color="inherit" sx={{ ml: 0.25 }}>
                · {banner.status_label || (reconciled ? "Reconciled" : "Mismatch")}
              </Typography>
            ) : null}
          </Typography>
          <Collapse in={reconOpen}>
            <Box
              sx={{
                mt: 0.75,
                p: 1,
                border: "1px solid",
                borderColor: reconciled ? "divider" : "error.light",
                borderRadius: 1.5,
                bgcolor: reconciled ? "grey.50" : "error.50",
              }}
            >
              <Typography variant="caption" display="block" color="text.secondary" sx={{ mb: 0.35 }}>
                Scope: {productivityScopeLabel}
              </Typography>
              <Typography variant="caption" display="block">
                Completed workload bags in scope: {workload}
              </Typography>
              <Typography variant="caption" display="block">
                Employee completed bags: {creditedAssigned}
              </Typography>
              {unassigned > 0 ? (
                <Typography variant="caption" display="block">
                  Unassigned completed bags: {unassigned}
                </Typography>
              ) : null}
              <Typography variant="caption" display="block" fontWeight={700}>
                Credited total (assigned + unassigned): {creditedTotal}
              </Typography>
              <Typography variant="caption" display="block">
                Employee completed + unassigned must equal completed workload
              </Typography>
              <Typography variant="caption" display="block" fontWeight={700} sx={{ mt: 0.35 }}>
                Status: {banner.status_label || (reconciled ? "Reconciled ✓" : "Mismatch ✗")}
              </Typography>
              {recon.wf_count != null || recon.hd_count != null ? (
                <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.35 }}>
                  WF {recon.wf_count ?? "—"} · HD {recon.hd_count ?? "—"}
                  {recon.difference != null && recon.difference !== 0
                    ? ` · difference ${recon.difference}`
                    : ""}
                </Typography>
              ) : null}
              {(recon.missing_from_employee_dashboard?.length > 0
                || recon.extra_in_employee_dashboard?.length > 0
                || recon.duplicate_bag_ids?.length > 0) ? (
                <Typography variant="caption" color="error.main" display="block" sx={{ mt: 0.35, lineHeight: 1.4 }}>
                  {recon.missing_from_employee_dashboard?.length
                    ? `Missing from dashboard: ${recon.missing_from_employee_dashboard.join(", ")}. `
                    : ""}
                  {recon.extra_in_employee_dashboard?.length
                    ? `Extra in dashboard: ${recon.extra_in_employee_dashboard.join(", ")}. `
                    : ""}
                  {recon.duplicate_bag_ids?.length
                    ? `Duplicates: ${recon.duplicate_bag_ids.join(", ")}`
                    : ""}
                </Typography>
              ) : null}
            </Box>
          </Collapse>
        </Box>

        <Box sx={{ mb: 1.25 }}>
          <Typography
            variant="caption"
            color="text.secondary"
            onClick={() => setAuditOpen((v) => !v)}
            sx={{
              cursor: "pointer",
              userSelect: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 0.35,
              fontWeight: 600,
            }}
          >
            <ExpandMoreIcon
              fontSize="inherit"
              sx={{
                transform: auditOpen ? "rotate(180deg)" : "rotate(-90deg)",
                transition: "transform 0.2s",
              }}
            />
            Completed attribution debug
            {!auditOpen ? (
              <Typography component="span" variant="caption" color="inherit" sx={{ ml: 0.25 }}>
                · {completedAttributionAudit.length} bags
              </Typography>
            ) : null}
          </Typography>
          <Collapse in={auditOpen}>
            <TableContainer sx={{ mt: 0.75, maxHeight: 320, overflow: "auto" }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 700 }}>Bag</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>WF/HD</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Rush</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Employee</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Signal</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>Excluded</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {completedAttributionAudit.map((row) => (
                    <TableRow key={row.bag_id}>
                      <TableCell>
                        <CopyableBagId bagId={row.bag_id} />
                      </TableCell>
                      <TableCell>{row.workflow || row.service_type || "—"}</TableCell>
                      <TableCell>{row.rush_label || row.rush_bucket || "—"}</TableCell>
                      <TableCell>{row.credited_employee || "—"}</TableCell>
                      <TableCell>{row.credit_signal || row.credit_event_type || "—"}</TableCell>
                      <TableCell>{row.excluded_reason || (row.included_in_employee_productivity ? "—" : "Unassigned")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Collapse>
        </Box>

        <Box sx={{ mb: 1.25 }}>
          <Typography variant="caption" color="text.secondary" display="block">
            Click a column header to sort. Default role filter: Rinse WF — Folder.
          </Typography>
        </Box>

        <TableContainer
          sx={{
            overflowX: "auto",
            maxWidth: "100%",
            WebkitOverflowScrolling: "touch",
          }}
        >
          <Table size="medium" aria-label="Employee productivity dashboard" sx={{ minWidth: { xs: 640, sm: 720 } }}>
            <TableHead>
              <TableRow>
                {PRODUCTIVITY_TABLE_COLUMNS.map((col) => (
                  <TableCell
                    key={col.id}
                    align={col.align || "left"}
                    sortDirection={rankBy === col.id ? sortDir : false}
                    sx={{ fontWeight: 700, py: 1.25, whiteSpace: "nowrap" }}
                  >
                    <TableSortLabel
                      active={rankBy === col.id}
                      direction={rankBy === col.id ? sortDir : "desc"}
                      onClick={() => handleSortColumn(col.id)}
                      sx={{
                        fontSize: { xs: "0.75rem", sm: "0.875rem" },
                        whiteSpace: "normal",
                        lineHeight: 1.2,
                        maxWidth: { xs: 96, sm: "none" },
                      }}
                    >
                      {col.label}
                    </TableSortLabel>
                  </TableCell>
                ))}
                <TableCell padding="checkbox" sx={{ py: 1.25 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {rankedEmployees.map((emp) => {
                const open = expandedEmployee === emp.employee;
                const missingClockIn = isMissingClockIn(emp);
                const dual = employeeHasFolderDualProductivity(emp);
                const productiveHrs = emp.role_hours ?? emp.productive_hours ?? emp.worked_hours;
                const tier = PERFORMANCE_TIER_STYLES[emp.performance_tier] || PERFORMANCE_TIER_STYLES.middle;
                const colSpan = PRODUCTIVITY_TABLE_COLUMNS.length + 1;
                const bagsHr = dual
                  ? fmtProductivityRate(emp.role_bags_per_hour, false)
                  : fmtProductivityRate(emp.completed_bags_per_hour ?? emp.bags_per_hour, missingClockIn);
                const lbsHr = dual
                  ? fmtProductivityRate(emp.role_lbs_per_hour, false)
                  : fmtProductivityRate(emp.completed_lbs_per_hour ?? emp.lbs_per_hour, missingClockIn);
                return (
                  <Fragment key={emp.employee}>
                    <TableRow
                      hover
                      onClick={() => setExpandedEmployee((prev) => (prev === emp.employee ? null : emp.employee))}
                      sx={{
                        cursor: "pointer",
                        bgcolor: tier.bgcolor,
                        "& td": {
                          borderBottom: open ? undefined : "1px solid",
                          borderColor: "divider",
                          py: 1.35,
                        },
                      }}
                    >
                      <TableCell
                        sx={{
                          fontWeight: 700,
                          position: { xs: "sticky", sm: "static" },
                          left: 0,
                          bgcolor: tier.bgcolor !== "transparent" ? tier.bgcolor : "background.paper",
                          zIndex: 1,
                          maxWidth: { xs: 120, sm: "none" },
                          wordBreak: "break-word",
                        }}
                      >
                        {emp.employee}
                      </TableCell>
                      <TableCell align="right">{emp.completed_bags ?? 0}</TableCell>
                      <TableCell align="right">{bagsHr}</TableCell>
                      <TableCell align="right">{employeeDisplayLbs(emp)}</TableCell>
                      <TableCell align="right">{lbsHr}</TableCell>
                      <TableCell align="right">
                        {missingClockIn && !dual ? "N/A" : fmtSummaryNumber(productiveHrs, 2)}
                      </TableCell>
                      <TableCell padding="checkbox">
                        <ExpandMoreIcon
                          fontSize="small"
                          sx={{
                            transform: open ? "rotate(180deg)" : "none",
                            transition: "transform 0.2s",
                            color: "text.secondary",
                          }}
                        />
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell
                        colSpan={colSpan}
                        sx={{
                          py: 0,
                          borderBottom: open ? undefined : "none",
                          // Keep expanded content viewport-width on mobile while the ranking
                          // table itself remains horizontally scrollable.
                          position: { xs: "relative", sm: "static" },
                        }}
                      >
                        <EmployeeProductivityDrilldownCollapse open={open}>
                          <Box
                            sx={{
                              py: 1.25,
                              px: { xs: 0.25, sm: 0.5 },
                              width: { xs: "min(100vw - 2rem, 100%)", sm: "100%" },
                              maxWidth: { xs: "calc(100vw - 2rem)", sm: "none" },
                              position: { xs: "sticky", sm: "static" },
                              left: 0,
                              overflowX: "hidden",
                              boxSizing: "border-box",
                            }}
                          >
                            <EmployeeSummaryPanel
                              emp={emp}
                              missingPreCount={bagsWithMissingPre(emp.bags).length}
                              sendingReview={sendingReview}
                              onSendForReview={() =>
                                sendBagsForReview(bagsWithMissingPre(emp.bags))
                              }
                            />
                            <EmployeeProductivityDrilldown
                              bags={emp.bags}
                              sessions={emp.sessions}
                              roleFilterKeys={roleFilterKeys}
                              referenceDateEt={selectedDate}
                              bagsLoading={loading && emp.bags == null}
                              onReviewBag={openReviewBag}
                              onSendBagForReview={(bag) =>
                                sendBagsForReview([bag], {
                                  reasonCode: bagsWithMissingPre([bag]).length
                                    ? "MISSING_PRE_EVIDENCE"
                                    : "MANAGER_SENT_FOR_REVIEW",
                                })
                              }
                              sendingReview={sendingReview || reviewLoadingBagId != null}
                              onAssignSession={assignBagSession}
                              assigning={assigningSession}
                            />
                          </Box>
                        </EmployeeProductivityDrilldownCollapse>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
      {reviewError ? (
        <Alert severity="error" sx={{ mt: 1.25 }} onClose={() => setReviewError("")}>
          {reviewError}
        </Alert>
      ) : null}
      {reviewBag ? (
        <EditBagPanel
          bag={reviewBag}
          selectedDateEt={selectedDate}
          catalog={reviewCatalog}
          onCancel={() => setReviewBag(null)}
          onError={(msg) => setReviewError(msg || "Review save failed")}
          onReloadLatest={async (bagId) => {
            const res = await getVeewashStep1BagDetail({
              date: selectedDate,
              metric: "completed",
              queue: "completed",
              bag_id: bagId,
              include_details: true,
            });
            const detail =
              (res?.data?.bags || []).find((b) => b.bag_id === bagId) || res?.data?.bags?.[0];
            if (detail) {
              setReviewBag((prev) => ({ ...(prev || {}), ...detail, _detailsLoaded: true }));
            }
            return detail;
          }}
          onSaved={async () => {
            setReviewBag(null);
            await fetchSection(selectedDate, rushFilter);
          }}
        />
      ) : null}
    </Paper>
  );
}

function resolvePreset(isoDate) {
  const today = todayRange().start;
  const yesterday = yesterdayRange().start;
  if (!isoDate || isoDate === today) return "today";
  if (isoDate === yesterday) return "yesterday";
  return "custom";
}
