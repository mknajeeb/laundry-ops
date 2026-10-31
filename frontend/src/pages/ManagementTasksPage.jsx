import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import ManagementHubNav from "../components/management/ManagementHubNav";
import TaskDashboardMonthlyChart from "../components/tasks/TaskDashboardMonthlyChart";
import TaskManualCompletionDialog from "../components/tasks/TaskManualCompletionDialog";
import TaskManageDialog from "../components/tasks/TaskManageDialog";
import TaskAssignmentCard from "../components/tasks/TaskAssignmentCard";
import TaskRecordDialog from "../components/tasks/TaskRecordDialog";
import { DEFAULT_CATEGORY_TABS, dashboardHeadlineMetrics } from "../components/tasks/taskDashboardLabels";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import {
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

function Metric({ label, value, accent, hint }) {
  return (
    <Box
      sx={{
        p: 1.25,
        minWidth: 100,
        flex: "1 1 100px",
        borderRadius: 2,
        bgcolor: "#fff",
        border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        borderLeft: `3px solid ${accent || VEEWASH_DASHBOARD.primaryBlue}`,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="h5" sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal }}>
        {value ?? 0}
      </Typography>
      {hint ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25, lineHeight: 1.25 }}>
          {hint}
        </Typography>
      ) : null}
    </Box>
  );
}

/**
 * Management Task Dashboard — redesigned (Phase 3).
 * Rinse: read-only, no activity log, no labor, no edit/add/remove.
 */
export default function ManagementTasksPage() {
  const today = businessTodayYmd();
  const [date, setDate] = useState(today);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rejectId, setRejectId] = useState(null);
  const [reason, setReason] = useState("");
  const [openKeys, setOpenKeys] = useState(() => new Set());
  const [categoryTab, setCategoryTab] = useState("all");
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
    setError("");
    try {
      const res = await getManagementTaskDashboard({ business_date: date });
      setData(res.data || null);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date]);

  const loadMonthly = useCallback(async () => {
    try {
      const res = await getManagementTaskDashboardMonthly({ months: 6, as_of: date });
      setMonthly(res.data || null);
    } catch {
      setMonthly(null);
    }
  }, [date]);

  useEffect(() => {
    load();
    loadMonthly();
  }, [load, loadMonthly]);

  // Collapse-by-default for a cleaner first view.
  useEffect(() => {
    setOpenKeys(new Set());
  }, [date, data?.business_date]);

  const categoryTabs = useMemo(() => {
    const fromApi = (data?.categories || []).map((c) => ({
      code: c.code,
      name: c.name || c.code,
    }));
    return fromApi.length ? fromApi : DEFAULT_CATEGORY_TABS;
  }, [data]);

  const filteredAssignments = useMemo(() => {
    const rows = data?.shared_assignments || [];
    if (categoryTab === "all") return rows;
    return rows.filter((r) => String(r.category_code || "intra_day") === categoryTab);
  }, [data, categoryTab]);

  const categoryMetrics = useMemo(
    () => dashboardHeadlineMetrics(filteredAssignments),
    [filteredAssignments]
  );

  const toggle = (key) => {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const approve = async (activityId) => {
    setBusy(true);
    setError("");
    try {
      await approveManagementTaskDashboard({ activity_id: activityId });
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Approve failed");
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

  const printReport = () => window.print();

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100%", pb: 4 }}>
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 2 }, pt: 2 }}>
        {!readOnly ? <ManagementHubNav /> : null}

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
              {formatDashboardDate(date)}
              {readOnly ? " · Read-only" : ""}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <TextField
              type="date"
              size="small"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ bgcolor: "#fff", borderRadius: 1, minWidth: 150 }}
            />
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
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
              <Metric
                label="Employees Assigned"
                value={categoryMetrics.employeesAssigned}
                hint="One count per employee on each activity. Two activities count the same person twice."
              />
              <Metric
                label="Employees Started"
                value={categoryMetrics.employeesStarted}
                accent={VEEWASH_DASHBOARD.primaryBlue}
                hint="Assigned participations that have started."
              />
              <Metric
                label="Completed Activities"
                value={categoryMetrics.completedActivities}
                accent={VEEWASH_DASHBOARD.teal}
                hint="Assignments whose work is finished. A shared group counts once. Verified and pending verification are included here."
              />
              <Metric
                label="Verified Activities"
                value={categoryMetrics.verifiedActivities}
                accent={VEEWASH_DASHBOARD.tealDark}
                hint="Supervisor approved. Included in Completed Activities, not an extra completion."
              />
              <Metric
                label="Pending Verification"
                value={categoryMetrics.pendingVerification}
                accent={VEEWASH_DASHBOARD.pending}
                hint="Finished assignments awaiting approval. Included in Completed Activities."
              />
              {!hideLabor && data?.metrics?.time_spent_seconds != null ? (
                <Metric
                  label="Time on tasks"
                  value={`${Math.round((data.metrics.time_spent_seconds || 0) / 60)}m`}
                  accent={VEEWASH_DASHBOARD.monitoringText}
                />
              ) : null}
            </Stack>

            {monthly ? (
              <Box sx={{ mb: 2 }}>
                <TaskDashboardMonthlyChart data={monthly} hideLabor={hideLabor} />
              </Box>
            ) : null}

            <Tabs
              value={categoryTab}
              onChange={(_, v) => setCategoryTab(v)}
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
              {filteredAssignments.length === 0 ? (
                <Box
                  sx={{
                    p: 3,
                    textAlign: "center",
                    bgcolor: "#fff",
                    borderRadius: 2,
                    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  }}
                >
                  <Typography color="text.secondary">No assignments for this day.</Typography>
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
                    />
                  );
                })
              )}
            </Stack>

            {/* Management history: expandable per assignment only — no duplicate Activity Log for Rinse.
                For managers, correct/edit history lives in record dialogs + revisions API. */}
            {!readOnly && (data?.activity_log || []).length > 0 ? (
              <Box sx={{ mt: 3 }}>
                <Typography
                  variant="subtitle2"
                  sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal, mb: 0.5 }}
                >
                  Management history
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  Internal audit trail (hidden from Rinse). Prefer editing from the assignment card.
                </Typography>
                <Box
                  sx={{
                    bgcolor: "#fff",
                    borderRadius: 2,
                    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                    maxHeight: 280,
                    overflow: "auto",
                  }}
                >
                  {(data.activity_log || [])
                    .filter((row) =>
                      categoryTab === "all"
                        ? true
                        : String(row.category_code || "intra_day") === categoryTab
                    )
                    .slice(0, 40)
                    .map((row) => (
                      <Stack
                        key={row.id || `${row.role}-${row.started_at}-${row.employee_name}`}
                        direction={{ xs: "column", sm: "row" }}
                        justifyContent="space-between"
                        sx={{
                          px: 1.5,
                          py: 0.85,
                          borderBottom: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                        }}
                      >
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {row.employee_name || "—"} · {row.role_label || row.role}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {row.status_label || row.status}
                          {row.completion_source_label ? ` · ${row.completion_source_label}` : ""}
                        </Typography>
                      </Stack>
                    ))}
                </Box>
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
          businessDate={date}
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
