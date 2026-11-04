import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Skeleton,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import { useI18n } from "../i18n/I18nContext";
import ManagementHubNav from "../components/management/ManagementHubNav";
import TaskManualCompletionDialog from "../components/tasks/TaskManualCompletionDialog";
import TaskManageDialog from "../components/tasks/TaskManageDialog";
import TaskAssignmentCard from "../components/tasks/TaskAssignmentCard";
import TaskRecordDialog from "../components/tasks/TaskRecordDialog";
import { DEFAULT_CATEGORY_TABS } from "../components/tasks/taskDashboardLabels";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import {
  addManagementTaskRemark,
  approveManagementTaskDashboard,
  correctManagementTaskCompletion,
  getManagementTaskDashboardMonthly,
  manualCompleteManagementTask,
  rejectManagementTaskDashboard,
  updateManagementTaskRecord,
  voidManagementTaskActivity,
} from "../api";
import { businessTodayYmd } from "../utils/businessTime";
import { formatDashboardDate } from "../components/tasks/taskDashboardFormat";
import { formatDurationHm } from "../components/tasks/taskDashboardLabels";
import { printTaskDashboard, printTaskFrequency } from "../components/tasks/taskDashboardPrint";
import {
  MAX_TASK_RANGE_DAYS,
  TASK_RANGE_PRESETS,
  inclusiveSpanDays,
  taskDashboardRange,
} from "../components/tasks/taskDashboardRange";

const ASSIGNMENT_PAGE_SIZE = 25;
const HISTORY_PAGE_SIZE = 40;

function EmployeeReport({ report, hideLabor, loading }) {
  const [openId, setOpenId] = useState(null);
  if (loading) return <Skeleton variant="rounded" height={88} />;
  const people = report?.employees || [];
  return (
    <Stack spacing={1}>
      <Typography variant="caption" color="text.secondary">
        {report?.unique_activities || 0} activities. A shared activity counts once in this total.
      </Typography>
      {people.length === 0 ? (
        <Typography color="text.secondary">No employee activity in this range.</Typography>
      ) : (
        people.map((person) => {
          const open = openId === person.employee_id;
          return (
            <Box
              key={person.employee_id}
              sx={{ bgcolor: "#fff", border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`, borderRadius: 2, px: 1.5, py: 1 }}
            >
              <Box onClick={() => setOpenId(open ? null : person.employee_id)} sx={{ cursor: "pointer" }}>
                <Typography sx={{ fontWeight: 800 }}>{person.employee_name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {person.assigned} assigned · {person.completed} completed · {person.in_progress} in progress · {person.not_started} not started · {person.verified} verified
                </Typography>
              </Box>
              {open
                ? (person.activities || []).map((activity) => (
                    <Box key={`${activity.assignment_key}-${activity.business_date}`} sx={{ mt: 0.75, pl: 0.5 }}>
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        {activity.activity} · {formatDashboardDate(activity.business_date)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {activity.status_label}
                        {activity.verification_label ? ` · ${activity.verification_label}` : ""}
                        {activity.participation_status ? ` · ${activity.participation_status}` : ""}
                        {!hideLabor && activity.duration_seconds != null
                          ? ` · ${formatDurationHm(activity.duration_seconds)}`
                          : ""}
                        {activity.checklist_required
                          ? ` · checklist ${activity.checklist_done || 0}/${activity.checklist_required}`
                          : ""}
                        {activity.checklist_completed_by_employee
                          ? ` · ${activity.checklist_completed_by_employee} items by this employee`
                          : ""}
                      </Typography>
                      {(activity.started_at || activity.ended_at) && !hideLabor ? (
                        <Typography variant="caption" color="text.secondary" display="block">
                          {activity.started_at ? `Start ${formatDashboardDate(activity.started_at)}` : "Not started"}
                          {activity.ended_at ? ` · Finish ${formatDashboardDate(activity.ended_at)}` : ""}
                        </Typography>
                      ) : null}
                    </Box>
                  ))
                : null}
            </Box>
          );
        })
      )}
    </Stack>
  );
}

function FrequencyReport({ groups, loading }) {
  const [openRole, setOpenRole] = useState("");
  if (loading) return <Skeleton variant="rounded" height={88} />;
  const rows = Array.isArray(groups) ? groups : [];
  if (!rows.length) return <Typography color="text.secondary">No activities in this range.</Typography>;
  return (
    <Stack spacing={1}>
      {rows.map((group) => {
        const open = openRole === (group.role || group.activity);
        return (
          <Box
            key={group.role || group.activity}
            sx={{ bgcolor: "#fff", border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`, borderRadius: 2, px: 1.5, py: 1 }}
          >
            <Box
              onClick={() => setOpenRole(open ? "" : group.role || group.activity)}
              sx={{ cursor: "pointer" }}
            >
              <Typography sx={{ fontWeight: 800 }}>{group.activity}</Typography>
              <Typography variant="body2" color="text.secondary">
                {Number(group.assigned) === 1 ? "1 time" : `${group.assigned} times`}
                {group.completion_rate == null ? "" : ` · ${group.completion_rate}% completed`}
              </Typography>
            </Box>
            {open
              ? (group.dates || []).map((row) => (
                  <Typography
                    key={`${group.role}-${row.business_date}-${row.status}`}
                    variant="body2"
                    sx={{ mt: 0.5 }}
                  >
                    {formatDashboardDate(row.business_date)} — {row.status_label} — {(row.employees || []).join(", ") || "—"}
                  </Typography>
                ))
              : null}
          </Box>
        );
      })}
    </Stack>
  );
}

function Metric({ label, value, hint }) {
  return (
    <Tooltip title={hint || ""} enterTouchDelay={0} arrow>
      <Box
        className="task-metric"
        sx={{
          px: 1,
          py: 0.6,
          minWidth: 88,
          borderRadius: 1.5,
          bgcolor: "#fff",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.1 }}>
          {label}
        </Typography>
        <Typography sx={{ fontWeight: 800, fontSize: "1.05rem", lineHeight: 1.2 }}>{value}</Typography>
      </Box>
    </Tooltip>
  );
}

/**
 * Management Task Dashboard — redesigned (Phase 3).
 * Rinse: read-only, no activity log, no labor, no edit/add/remove.
 */
export default function ManagementTasksPage() {
  const { locale } = useI18n();
  const today = businessTodayYmd();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rejectId, setRejectId] = useState(null);
  const [reason, setReason] = useState("");
  const [openKeys, setOpenKeys] = useState(() => new Set());
  const [categoryTab, setCategoryTab] = useState("all");
  const [rangePreset, setRangePreset] = useState("today");
  const [groupBy, setGroupBy] = useState("daily");
  const [customStart, setCustomStart] = useState(today);
  const [customEnd, setCustomEnd] = useState(today);
  const [assignmentPage, setAssignmentPage] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualMode, setManualMode] = useState("record");
  const [manualContext, setManualContext] = useState(null);
  const [monthly, setMonthly] = useState(null);
  const [recordOpen, setRecordOpen] = useState(false);
  const [recordMode, setRecordMode] = useState("edit");
  const [recordContext, setRecordContext] = useState(null);
  const [view, setView] = useState("operations");
  const [activityRole, setActivityRole] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const requestSeq = useRef(0);

  const readOnly = Boolean(data?.read_only);
  const hideLabor = Boolean(data?.hide_labor_metrics || data?.labor_fields_hidden);
  const canManual = Boolean(data?.can_manual_complete) && !readOnly;
  const canManage = Boolean(data?.can_manage_tasks) && !readOnly;
  const canApprove = Boolean(data?.can_approve !== false) && !readOnly;

  const activeRange = taskDashboardRange(rangePreset, today, customStart, customEnd);
  const rangeSpan = inclusiveSpanDays(activeRange.start, activeRange.end);
  const load = useCallback(async () => {
    if (rangeSpan > MAX_TASK_RANGE_DAYS) {
      setMonthly(null);
      setData(null);
      setError(`This range is ${rangeSpan} days. Choose ${MAX_TASK_RANGE_DAYS} days or fewer.`);
      setLoading(false);
      return;
    }
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    setLoading(true);
    try {
      const res = await getManagementTaskDashboardMonthly({
        start: activeRange.start,
        end: activeRange.end,
        group_by: groupBy,
        category: categoryTab === "all" ? "" : categoryTab,
        activity: activityRole,
        employee_id: employeeId,
        status: statusFilter,
        include_assignments: 1,
        assignment_offset: assignmentPage * ASSIGNMENT_PAGE_SIZE,
        assignment_limit: ASSIGNMENT_PAGE_SIZE,
        history_offset: historyOpen ? historyPage * HISTORY_PAGE_SIZE : 0,
        history_limit: historyOpen ? HISTORY_PAGE_SIZE : 0,
      });
      if (seq !== requestSeq.current) return;
      setMonthly(res.data || null);
      setData(res.data || null);
      setError("");
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(err?.response?.data?.error || err?.message || "Failed to load this date range");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [
    activeRange.start,
    activeRange.end,
    rangeSpan,
    groupBy,
    categoryTab,
    activityRole,
    employeeId,
    statusFilter,
    assignmentPage,
    historyPage,
    historyOpen,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  // Collapse-by-default for a cleaner first view.
  useEffect(() => {
    setOpenKeys(new Set());
  }, [activeRange.start, activeRange.end, data?.business_date]);

  const categoryTabs = useMemo(() => {
    const fromApi = (monthly?.categories || data?.categories || []).map((c) => ({
      code: c.code || c.category_code,
      name: c.name || c.category_name || c.code,
    }));
    return fromApi.length ? fromApi : DEFAULT_CATEGORY_TABS;
  }, [data, monthly]);

  const filteredAssignments = useMemo(() => {
    return Array.isArray(monthly?.assignments) ? monthly.assignments : [];
  }, [monthly]);
  const activityOptions = monthly?.filter_options?.activities || [];
  const employeeOptions = monthly?.filter_options?.employees || [];
  const groupedAssignments = useMemo(() => {
    const order = categoryTabs.map((tab) => tab.code);
    const buckets = new Map();
    for (const row of filteredAssignments) {
      const code = row.category_code || "intra_day";
      if (!buckets.has(code)) buckets.set(code, []);
      buckets.get(code).push(row);
    }
    return [...buckets.keys()]
      .sort((left, right) => {
        const leftAt = order.indexOf(left);
        const rightAt = order.indexOf(right);
        return (leftAt === -1 ? 999 : leftAt) - (rightAt === -1 ? 999 : rightAt);
      })
      .map((code) => ({
        code,
        name: categoryTabs.find((tab) => tab.code === code)?.name || code,
        rows: buckets.get(code),
      }));
  }, [filteredAssignments, categoryTabs]);

  const categoryMetrics = useMemo(() => {
    const totals = monthly?.totals || {};
    const people = monthly?.participation || {};
    return {
      activitiesAssigned: totals.assigned ?? 0,
      completedActivities: totals.completed ?? 0,
      pendingVerification: totals.pending_verification ?? 0,
      verifiedActivities: totals.verified ?? 0,
      overdue: totals.overdue ?? 0,
      employeesAssigned: people.employees_assigned ?? 0,
      employeesStarted: people.employees_started ?? 0,
      employeesFinished: people.employees_finished ?? 0,
      totalTimeLabel: formatDurationHm(people.total_time_seconds ?? 0),
    };
  }, [monthly]);
  const assignmentTotal = Number(monthly?.assignment_total || 0);
  const historyRows = Array.isArray(monthly?.history) ? monthly.history : [];
  const historyTotal = Number(monthly?.history_total || 0);

  const toggle = (key) => {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const approve = async (activityId, supervisorRemark = "") => {
    setBusy(true);
    setError("");
    try {
      const ids = Array.isArray(activityId) ? activityId : [activityId];
      await approveManagementTaskDashboard({
        activity_ids: ids,
        supervisor_remark: supervisorRemark || "",
      });
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Approve failed");
    } finally {
      setBusy(false);
    }
  };

  const addRemark = async (row, body, taskCode) => {
    const activityId = (row.contributions || [])
      .map((item) => item.activity?.id || item.activity_id)
      .find(Boolean);
    if (!activityId) {
      setError("Start the activity before adding a remark.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await addManagementTaskRemark({
        activity_id: activityId,
        body,
        task_code: taskCode || "",
      });
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not save the remark");
    } finally {
      setBusy(false);
    }
  };

  const confirmReject = async () => {
    if (!rejectId) return;
    setBusy(true);
    setError("");
    try {
      await rejectManagementTaskDashboard({ activity_id: rejectId, reason });
      setRejectId(null);
      setReason("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Reject failed");
    } finally {
      setBusy(false);
    }
  };

  const openManual = (row, contribution, mode) => {
    setManualMode(mode);
    setManualContext({ row, contribution });
    setManualOpen(true);
  };

  const submitManual = async (body) => {
    setBusy(true);
    try {
      if (manualMode === "correct") await correctManagementTaskCompletion(body);
      else await manualCompleteManagementTask(body);
      setManualOpen(false);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const openRecord = (row, contribution, activity, mode) => {
    setRecordMode(mode);
    setRecordContext({
      row,
      contribution,
      activity,
      assignmentLabel: row?.role_label || row?.role,
      employeeName: contribution?.employee_name,
    });
    setRecordOpen(true);
  };

  const submitRecord = async (payload) => {
    setBusy(true);
    try {
      if (payload.mode === "void") {
        await voidManagementTaskActivity({
          activity_id: payload.activity_id,
          reason: payload.reason,
          remarks: payload.remarks,
        });
      } else {
        await updateManagementTaskRecord({
          activity_id: payload.activity_id,
          started_at: payload.started_at,
          ended_at: payload.ended_at,
          business_date: payload.business_date,
          reason: payload.reason,
          remarks: payload.remarks,
        });
      }
      setRecordOpen(false);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const printReport = async () => {
    const categoryLabel =
      categoryTab === "all"
        ? "All"
        : categoryTabs.find((tab) => tab.code === categoryTab)?.name || categoryTab;
    if (rangeSpan > MAX_TASK_RANGE_DAYS) {
      setError(`This range is ${rangeSpan} days. Choose ${MAX_TASK_RANGE_DAYS} days or fewer.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await getManagementTaskDashboardMonthly({
        start: activeRange.start,
        end: activeRange.end,
        group_by: groupBy,
        category: categoryTab === "all" ? "" : categoryTab,
        activity: activityRole,
        employee_id: employeeId,
        status: statusFilter,
        include_assignments: 1,
        assignment_limit: 0,
        history_limit: 0,
      });
      if (view === "frequency") {
        printTaskFrequency({
          rangeStart: activeRange.start,
          rangeEnd: activeRange.end,
          categoryLabel,
          groups: res.data?.activity_frequency || [],
        });
        return;
      }
      printTaskDashboard({
        rangeStart: activeRange.start,
        rangeEnd: activeRange.end,
        categoryLabel,
        groupBy,
        rows: res.data?.assignments || [],
        hideLabor,
        hideRemarks: Boolean(readOnly),
        locale,
      });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not prepare the print report");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box className="task-dashboard-print-root" sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100%", pb: 4 }}>
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 2 }, pt: 2 }}>
        {!readOnly ? (
          <Box className="no-print">
            <ManagementHubNav />
          </Box>
        ) : null}

        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "flex-end" }}
          spacing={1.5}
          sx={{ mb: 2, mt: readOnly ? 0 : 1 }}
        >
          <Box>
            <Typography
              variant="h5"
              sx={{ fontWeight: 900, color: VEEWASH_DASHBOARD.wfCharcoal, letterSpacing: -0.3 }}
            >
              Task Dashboard
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {activeRange.start === activeRange.end
                ? formatDashboardDate(activeRange.start)
                : `${activeRange.start} – ${activeRange.end}`}
              {readOnly ? " · Read-only" : ""}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap className="no-print">
            <Button
              size="small"
              startIcon={<PrintIcon />}
              onClick={printReport}
              variant="outlined"
              sx={{ bgcolor: "#fff" }}
            >
              Print
            </Button>
            {canManage ? (
              <Button
                size="small"
                variant="contained"
                onClick={() => setManageOpen(true)}
                sx={{
                  bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                  "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
                }}
              >
                Manage tasks
              </Button>
            ) : null}
            {canManage ? (
              <Button
                size="small"
                component={RouterLink}
                to="/management/task-management"
                sx={{ bgcolor: "#fff" }}
              >
                Full editor
              </Button>
            ) : null}
          </Stack>
        </Stack>

        {error ? (
          <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
            {error}
          </Alert>
        ) : null}

          <>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1 }} className="no-print">
              <TextField
                select
                size="small"
                label="Range"
                value={rangePreset}
                onChange={(e) => {
                  setRangePreset(e.target.value);
                  setAssignmentPage(0);
                  setHistoryPage(0);
                }}
                sx={{ minWidth: 160 }}
              >
                {TASK_RANGE_PRESETS.map((preset) => (
                  <MenuItem key={preset.id} value={preset.id}>
                    {preset.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="Grouping"
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value)}
                sx={{ minWidth: 130 }}
              >
                <MenuItem value="daily">Daily</MenuItem>
                <MenuItem value="weekly">Weekly</MenuItem>
                <MenuItem value="monthly">Monthly</MenuItem>
              </TextField>
              {rangePreset === "custom" ? (
                <>
                  <TextField
                    size="small"
                    type="date"
                    label="Start"
                    value={customStart}
                    onChange={(e) => {
                      setCustomStart(e.target.value);
                      setAssignmentPage(0);
                      setHistoryPage(0);
                    }}
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    size="small"
                    type="date"
                    label="End"
                    value={customEnd}
                    onChange={(e) => {
                      setCustomEnd(e.target.value);
                      setAssignmentPage(0);
                      setHistoryPage(0);
                    }}
                    InputLabelProps={{ shrink: true }}
                  />
                </>
              ) : null}
              <TextField
                select
                size="small"
                label="Activity"
                value={activityRole}
                onChange={(e) => {
                  setActivityRole(e.target.value);
                  setAssignmentPage(0);
                }}
                sx={{ minWidth: 160 }}
              >
                <MenuItem value="">All activities</MenuItem>
                {activityOptions.map((option) => (
                  <MenuItem key={option.role} value={option.role}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="Employee"
                value={employeeId}
                onChange={(e) => {
                  setEmployeeId(e.target.value);
                  setAssignmentPage(0);
                }}
                sx={{ minWidth: 160 }}
              >
                <MenuItem value="">All employees</MenuItem>
                {employeeOptions.map((option) => (
                  <MenuItem key={option.employee_id} value={String(option.employee_id)}>
                    {option.employee_name}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="Status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setAssignmentPage(0);
                }}
                sx={{ minWidth: 150 }}
              >
                <MenuItem value="">All statuses</MenuItem>
                <MenuItem value="not_started">Not Started</MenuItem>
                <MenuItem value="in_progress">In Progress</MenuItem>
                <MenuItem value="pending_verification">Pending Verification</MenuItem>
                <MenuItem value="verified">Verified</MenuItem>
                <MenuItem value="overdue">Overdue</MenuItem>
                <MenuItem value="needs_correction">Needs Correction</MenuItem>
              </TextField>
            </Stack>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1.25 }}>
              <Metric label="Assigned" value={categoryMetrics.activitiesAssigned} hint="Shared assignments count once." />
              <Metric label="Completed" value={categoryMetrics.completedActivities} hint="Finished assignments. Includes pending verification and verified." />
              <Metric label="Pending" value={categoryMetrics.pendingVerification} hint="Finished and waiting for verification." />
              <Metric label="Verified" value={categoryMetrics.verifiedActivities} hint="Supervisor approved." />
              <Metric label="Overdue" value={categoryMetrics.overdue} hint="Not finished after the planned time." />
              {!hideLabor ? (
                <Metric label="Time" value={categoryMetrics.totalTimeLabel} hint="Sum of each employee's participation time." />
              ) : null}
            </Stack>

            <Tabs
              value={view}
              onChange={(_, value) => setView(value)}
              sx={{
                mb: 1,
                minHeight: 36,
                "& .MuiTab-root": { minHeight: 36, textTransform: "none", fontWeight: 700 },
                "& .Mui-selected": { color: `${VEEWASH_DASHBOARD.primaryBlue} !important` },
                "& .MuiTabs-indicator": { bgcolor: VEEWASH_DASHBOARD.primaryBlue },
              }}
            >
              <Tab value="operations" label="Operations" />
              <Tab value="employee" label="By Employee" />
              <Tab value="frequency" label="Frequency" />
            </Tabs>

            {view === "operations" ? (
            <Tabs
              value={categoryTab}
                onChange={(_, v) => {
                  setCategoryTab(v);
                  setAssignmentPage(0);
                  setHistoryPage(0);
                }}
              variant="scrollable"
              scrollButtons="auto"
              sx={{
                mb: 1.5,
                minHeight: 36,
                "& .MuiTab-root": { minHeight: 36, textTransform: "none", fontWeight: 700 },
                "& .Mui-selected": { color: `${VEEWASH_DASHBOARD.primaryBlue} !important` },
                "& .MuiTabs-indicator": { bgcolor: VEEWASH_DASHBOARD.primaryBlue },
              }}
            >
              <Tab value="all" label="All" />
              {categoryTabs.map((t) => (
                <Tab key={t.code} value={t.code} label={t.name} />
              ))}
            </Tabs>
            ) : null}

            {view === "employee" ? (
              <EmployeeReport
                report={monthly?.employee_report}
                hideLabor={hideLabor}
                loading={monthly == null}
              />
            ) : null}
            {view === "frequency" ? (
              <FrequencyReport groups={monthly?.activity_frequency} loading={monthly == null} />
            ) : null}

            {view === "operations" ? (
            <Stack spacing={1.5}>
              {monthly == null ? (
                <Stack spacing={1}>
                  <Skeleton variant="rounded" height={72} />
                  <Skeleton variant="rounded" height={72} />
                  <Skeleton variant="rounded" height={72} />
                </Stack>
              ) : filteredAssignments.length === 0 ? (
                <Box
                  sx={{
                    p: 3,
                    textAlign: "center",
                    bgcolor: "#fff",
                    borderRadius: 2,
                    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  }}
                >
                  <Typography color="text.secondary">No assignments in this range.</Typography>
                </Box>
              ) : (
                groupedAssignments.map((bucket) => (
                  <Box key={bucket.code}>
                    <Typography variant="caption" sx={{ fontWeight: 800, color: "text.secondary" }}>
                      {bucket.name}
                    </Typography>
                    <Stack spacing={1} sx={{ mt: 0.5 }}>
                      {bucket.rows.map((row) => {
                        const key = row.assignment_key || `${row.role}-${row.assignment_group_id}-${row.business_date}`;
                        return (
                          <TaskAssignmentCard
                            key={key}
                            row={row}
                            expanded={openKeys.has(key)}
                            onToggle={() => toggle(key)}
                            readOnly={readOnly}
                            hideLabor={hideLabor}
                            canApprove={canApprove}
                            canManual={canManual}
                            onApprove={approve}
                            onReject={(id) => {
                              setRejectId(id);
                              setReason("");
                            }}
                            onManual={openManual}
                            onEditRecord={(r, c, act) => openRecord(r, c, act, "edit")}
                            onVoidRecord={(r, c, act) => openRecord(r, c, act, "void")}
                            rejectId={rejectId}
                            reason={reason}
                            setReason={setReason}
                            onConfirmReject={confirmReject}
                            onCancelReject={() => setRejectId(null)}
                            onAddRemark={readOnly ? undefined : (body, taskCode) => addRemark(row, body, taskCode)}
                          />
                        );
                      })}
                    </Stack>
                  </Box>
                ))
              )}
            </Stack>
            ) : null}
            {view === "operations" && assignmentTotal > ASSIGNMENT_PAGE_SIZE ? (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }} className="no-print">
                <Button
                  size="small"
                  disabled={assignmentPage <= 0}
                  onClick={() => setAssignmentPage((page) => Math.max(0, page - 1))}
                >
                  Previous
                </Button>
                <Typography variant="caption" color="text.secondary">
                  Activities {assignmentPage * ASSIGNMENT_PAGE_SIZE + 1}–
                  {Math.min(assignmentTotal, (assignmentPage + 1) * ASSIGNMENT_PAGE_SIZE)} of {assignmentTotal}
                </Typography>
                <Button
                  size="small"
                  disabled={(assignmentPage + 1) * ASSIGNMENT_PAGE_SIZE >= assignmentTotal}
                  onClick={() => setAssignmentPage((page) => page + 1)}
                >
                  Next
                </Button>
              </Stack>
            ) : null}

            {!readOnly ? (
              <Box className="no-print" sx={{ mt: 3 }}>
                <Button
                  size="small"
                  onClick={() => setHistoryOpen((open) => !open)}
                  sx={{ textTransform: "none", fontWeight: 800, px: 0 }}
                >
                  {historyOpen ? "Hide audit history" : "Audit history"}
                </Button>
                {historyOpen ? (
                <>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  {activeRange.start} – {activeRange.end} ET. Completion and verification stay separate.
                  {historyTotal ? ` ${historyTotal} records.` : ""}
                </Typography>
                <Box
                  sx={{
                    bgcolor: "#fff",
                    borderRadius: 2,
                    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  }}
                >
                  {historyRows.length === 0 ? (
                    <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, py: 1.25 }}>
                      No management history in this range.
                    </Typography>
                  ) : (
                    historyRows.map((row) => (
                      <Stack
                        key={row.id || `${row.role}-${row.started_at}-${row.employee_name}`}
                        direction={{ xs: "column", sm: "row" }}
                        justifyContent="space-between"
                        spacing={0.5}
                        sx={{
                          px: 1.5,
                          py: 0.85,
                          borderBottom: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                        }}
                      >
                        <Box>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {formatDashboardDate(row.business_date)} · {row.employee_name || "—"} ·{" "}
                            {row.role_label || row.role}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            Completion: {row.status_label || row.status || "—"}
                            {row.completion_source_label ? ` · ${row.completion_source_label}` : ""}
                          </Typography>
                        </Box>
                        <Typography variant="caption" sx={{ fontWeight: 700 }}>
                          Verification: {row.verification_label || "Not verified"}
                        </Typography>
                      </Stack>
                    ))
                  )}
                </Box>
                {historyTotal > HISTORY_PAGE_SIZE ? (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                    <Button
                      size="small"
                      disabled={historyPage <= 0}
                      onClick={() => setHistoryPage((page) => Math.max(0, page - 1))}
                    >
                      Previous
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      History {historyPage * HISTORY_PAGE_SIZE + 1}–
                      {Math.min(historyTotal, (historyPage + 1) * HISTORY_PAGE_SIZE)} of {historyTotal}
                    </Typography>
                    <Button
                      size="small"
                      disabled={(historyPage + 1) * HISTORY_PAGE_SIZE >= historyTotal}
                      onClick={() => setHistoryPage((page) => page + 1)}
                    >
                      Next
                    </Button>
                  </Stack>
                ) : null}
                </>
                ) : (
                  <Typography variant="caption" color="text.secondary" display="block">
                    Detailed audit rows stay unloaded until you open them.
                  </Typography>
                )}
              </Box>
            ) : null}
          </>

        {busy ? (
          <Box sx={{ position: "fixed", bottom: 16, right: 16 }}>
            <CircularProgress size={28} />
          </Box>
        ) : null}
      </Box>

      {canManage ? (
        <TaskManageDialog open={manageOpen} onClose={() => setManageOpen(false)} onSaved={load} />
      ) : null}
      {canManual ? (
        <TaskManualCompletionDialog
          open={manualOpen}
          mode={manualMode}
          context={manualContext}
          businessDate={activeRange.end}
          onClose={() => setManualOpen(false)}
          onSubmit={submitManual}
          busy={busy}
        />
      ) : null}
      {canManual ? (
        <TaskRecordDialog
          open={recordOpen}
          mode={recordMode}
          activity={recordContext?.activity}
          assignmentLabel={recordContext?.assignmentLabel}
          employeeName={recordContext?.employeeName}
          onClose={() => setRecordOpen(false)}
          onSubmit={submitRecord}
          busy={busy}
        />
      ) : null}
    </Box>
  );
}
