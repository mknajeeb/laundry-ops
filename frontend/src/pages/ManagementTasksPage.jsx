import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
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
import TaskDashboardMonthlyChart from "../components/tasks/TaskDashboardMonthlyChart";
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
  getManagementTaskDashboard,
  getManagementTaskDashboardMonthly,
  manualCompleteManagementTask,
  rejectManagementTaskDashboard,
  updateManagementTaskRecord,
  voidManagementTaskActivity,
} from "../api";
import { businessTodayYmd } from "../utils/businessTime";
import { formatDashboardDate } from "../components/tasks/taskDashboardFormat";
import { formatDurationHm } from "../components/tasks/taskDashboardLabels";
import { printTaskDashboard } from "../components/tasks/taskDashboardPrint";
import {
  MAX_TASK_RANGE_DAYS,
  TASK_RANGE_PRESETS,
  inclusiveSpanDays,
  taskDashboardRange,
} from "../components/tasks/taskDashboardRange";

const ASSIGNMENT_PAGE_SIZE = 25;
const HISTORY_PAGE_SIZE = 40;

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

  const readOnly = Boolean(data?.read_only);
  const hideLabor = Boolean(data?.hide_labor_metrics || data?.labor_fields_hidden);
  const canManual = Boolean(data?.can_manual_complete) && !readOnly;
  const canManage = Boolean(data?.can_manage_tasks) && !readOnly;
  const canApprove = Boolean(data?.can_approve !== false) && !readOnly;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getManagementTaskDashboard({ business_date: today });
      setData(res.data || null);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [today]);

  const activeRange = taskDashboardRange(rangePreset, today, customStart, customEnd);
  const rangeSpan = inclusiveSpanDays(activeRange.start, activeRange.end);
  const loadMonthly = useCallback(async () => {
    if (rangeSpan > MAX_TASK_RANGE_DAYS) {
      setMonthly(null);
      setError(
        `This range is ${rangeSpan} days. Choose ${MAX_TASK_RANGE_DAYS} days or fewer.`
      );
      return;
    }
    try {
      const res = await getManagementTaskDashboardMonthly({
        start: activeRange.start,
        end: activeRange.end,
        group_by: groupBy,
        category: categoryTab === "all" ? "" : categoryTab,
        include_assignments: 1,
        assignment_offset: assignmentPage * ASSIGNMENT_PAGE_SIZE,
        assignment_limit: ASSIGNMENT_PAGE_SIZE,
        history_offset: historyPage * HISTORY_PAGE_SIZE,
        history_limit: HISTORY_PAGE_SIZE,
      });
      setMonthly(res.data || null);
      setError("");
    } catch (err) {
      setMonthly(null);
      setError(err?.response?.data?.error || err?.message || "Failed to load this date range");
    }
  }, [
    activeRange.start,
    activeRange.end,
    rangeSpan,
    groupBy,
    categoryTab,
    assignmentPage,
    historyPage,
  ]);

  useEffect(() => {
    load();
    loadMonthly();
  }, [load, loadMonthly]);

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
    const rows = Array.isArray(monthly?.assignments) ? monthly.assignments : [];
    if (categoryTab === "all") return rows;
    return rows.filter((r) => String(r.category_code || "intra_day") === categoryTab);
  }, [categoryTab, monthly]);

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
        include_assignments: 1,
        assignment_limit: 0,
      });
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

        {loading && !data ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress />
          </Box>
        ) : (
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
              <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                {activeRange.start} – {activeRange.end} ET
              </Typography>
            </Stack>
            <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
              Activities
            </Typography>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 0.75 }}>
              <Metric label="Assigned" value={categoryMetrics.activitiesAssigned} hint="Shared assignments count once." />
              <Metric label="Completed" value={categoryMetrics.completedActivities} hint="Finished assignments. Includes pending verification and verified." />
              <Metric label="Pending Verification" value={categoryMetrics.pendingVerification} hint="Finished and waiting for a supervisor. Also included in Completed." />
              <Metric label="Verified" value={categoryMetrics.verifiedActivities} hint="Supervisor approved. Also included in Completed." />
              <Metric label="Overdue" value={categoryMetrics.overdue} hint="Not finished after the planned time." />
            </Stack>
            <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
              Employee participation
            </Typography>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1.25 }}>
              <Metric label="Assigned" value={categoryMetrics.employeesAssigned} hint="Each employee on each assignment." />
              <Metric label="Started" value={categoryMetrics.employeesStarted} hint="Participations that have started." />
              <Metric label="Finished" value={categoryMetrics.employeesFinished} hint="Participations that have finished." />
              {!hideLabor ? (
                <Metric label="Total Time" value={categoryMetrics.totalTimeLabel} hint="Sum of each employee's participation time." />
              ) : null}
            </Stack>

            {monthly ? (
              <Box sx={{ mb: 2 }}>
                <TaskDashboardMonthlyChart data={monthly} hideLabor={hideLabor} />
              </Box>
            ) : null}

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

            <Stack spacing={1.25}>
              {monthly == null ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
                  <CircularProgress size={28} />
                </Box>
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
                filteredAssignments.map((row) => {
                  const key = row.assignment_key || `${row.role}-${row.assignment_group_id}`;
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
                })
              )}
            </Stack>
            {assignmentTotal > ASSIGNMENT_PAGE_SIZE ? (
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
                <Typography
                  variant="subtitle2"
                  sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal, mb: 0.5 }}
                >
                  Management history
                </Typography>
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
              </Box>
            ) : null}
          </>
        )}

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
