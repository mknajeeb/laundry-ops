import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import PrintIcon from "@mui/icons-material/Print";
import ManagementHubNav from "../components/management/ManagementHubNav";
import TaskDashboardMonthlyChart from "../components/tasks/TaskDashboardMonthlyChart";
import TaskManualCompletionDialog from "../components/tasks/TaskManualCompletionDialog";
import TaskManageDialog from "../components/tasks/TaskManageDialog";
import {
  DEFAULT_CATEGORY_TABS,
  formatEtWall,
  friendlyStatusLabel,
  statusChipColor,
} from "../components/tasks/taskDashboardLabels";
import {
  approveManagementTaskDashboard,
  correctManagementTaskCompletion,
  getManagementTaskDashboard,
  getManagementTaskDashboardMonthly,
  manualCompleteManagementTask,
  rejectManagementTaskDashboard,
} from "../api";
import { businessTodayYmd } from "../utils/businessTime";
import { formatCompletionInput } from "../opsMobile/TaskCompletionInputs";

function Metric({ label, value }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, minWidth: 110, flex: "1 1 110px" }}>
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="h5" sx={{ fontWeight: 800 }}>
        {value ?? 0}
      </Typography>
    </Paper>
  );
}

function formatDuration(seconds) {
  if (seconds == null) return "—";
  const sec = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function StatusChip({ status }) {
  return (
    <Chip
      size="small"
      label={friendlyStatusLabel(status)}
      color={statusChipColor(status)}
    />
  );
}

/**
 * Management Task Dashboard — compliance, verification, manual completion, monthly chart.
 * Rinse: read-only, no blue notices, no labor metrics, no manage/manual controls.
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

  const initial = today.slice(0, 7).split("-");
  const [chartYear, setChartYear] = useState(Number(initial[0]));
  const [chartMonth, setChartMonth] = useState(Number(initial[1]));
  const [chartCategory, setChartCategory] = useState("");
  const [monthly, setMonthly] = useState(null);
  const [monthlyLoading, setMonthlyLoading] = useState(false);

  const [manageOpen, setManageOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualMode, setManualMode] = useState("manual");
  const [manualTarget, setManualTarget] = useState({ assignment: null, contribution: null });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementTaskDashboard({ date });
      setData(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load Task Dashboard");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date]);

  const loadMonthly = useCallback(async () => {
    setMonthlyLoading(true);
    try {
      const res = await getManagementTaskDashboardMonthly({
        year: chartYear,
        month: chartMonth,
        category: chartCategory || undefined,
      });
      setMonthly(res.data || null);
    } catch (e) {
      // Non-fatal for the day view
      setMonthly(null);
    } finally {
      setMonthlyLoading(false);
    }
  }, [chartYear, chartMonth, chartCategory]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadMonthly();
  }, [loadMonthly]);

  useEffect(() => {
    // Expand assignments by default so print/report and first glance show detail.
    const keys = (data?.shared_assignments || []).map((r) => r.assignment_key).filter(Boolean);
    if (keys.length) setOpenKeys(new Set(keys));
  }, [data?.shared_assignments]);

  const metrics = data?.metrics || {};
  const readOnly = data?.read_only === true;
  const hideLabor = data?.hide_labor_metrics === true || data?.labor_fields_hidden === true;
  const canManual = data?.can_manual_complete === true && !readOnly;
  const canManage = data?.can_manage_tasks === true && !readOnly;
  const shiftEnd = data?.shift_end || {};
  const blocking = shiftEnd.blocking_close || [];

  const categoryTabs = useMemo(() => {
    const fromApi = (data?.category_breakdown || []).map((c) => ({
      code: c.category_code,
      name: c.category_name,
    }));
    const base = DEFAULT_CATEGORY_TABS.map((t) => {
      const hit = fromApi.find((c) => c.code === t.code);
      return hit || t;
    });
    const extras = fromApi.filter((c) => !base.some((b) => b.code === c.code));
    return [{ code: "all", name: "All Categories" }, ...base, ...extras];
  }, [data?.category_breakdown]);

  const filteredAssignments = useMemo(() => {
    const rows = data?.shared_assignments || [];
    if (categoryTab === "all") return rows;
    return rows.filter((r) => (r.category_code || "intra_day") === categoryTab);
  }, [data?.shared_assignments, categoryTab]);

  const categoryMetrics = useMemo(() => {
    if (categoryTab === "all") return metrics;
    const cat = (data?.category_breakdown || []).find((c) => c.category_code === categoryTab);
    if (!cat) return {};
    const assigned = cat.assigned || 0;
    const completed = cat.completed || 0;
    return {
      total_assigned: assigned,
      started: completed + (cat.overdue || 0),
      completed,
      verified: cat.verified || 0,
      pending_verification: cat.pending_verification || 0,
      overdue: cat.overdue || 0,
      rejected: cat.rejected || 0,
      completion_rate: assigned ? Math.round((completed / assigned) * 1000) / 10 : null,
    };
  }, [categoryTab, data?.category_breakdown, metrics]);

  const approve = async (id) => {
    if (readOnly) return;
    setBusy(true);
    try {
      await approveManagementTaskDashboard({ activity_id: id });
      await load();
      await loadMonthly();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Approve failed");
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (readOnly || !rejectId) return;
    setBusy(true);
    try {
      await rejectManagementTaskDashboard({ activity_id: rejectId, reason });
      setRejectId(null);
      setReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Reject failed");
    } finally {
      setBusy(false);
    }
  };

  const openManual = (assignment, contribution, mode = "manual") => {
    setManualTarget({ assignment, contribution });
    setManualMode(mode);
    setManualOpen(true);
  };

  const submitManual = async (body) => {
    setBusy(true);
    setError("");
    try {
      if (manualMode === "correct") {
        await correctManagementTaskCompletion(body);
      } else {
        await manualCompleteManagementTask(body);
      }
      setManualOpen(false);
      await load();
      await loadMonthly();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Manual completion failed");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (key) => {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const printReport = () => {
    window.print();
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2.5 }, maxWidth: 1200, mx: "auto" }} className="task-dashboard-page">
      <style>{`
        @media print {
          .no-print, .MuiTabs-root, nav, header { display: none !important; }
          .task-dashboard-page { max-width: none !important; padding: 0 !important; }
          .task-dashboard-chart { break-inside: avoid; }
          .print-only { display: block !important; }
          .print-expand .MuiCollapse-wrapperInner, .print-expand .MuiCollapse-root {
            height: auto !important; visibility: visible !important;
          }
          .print-expand { height: auto !important; }
          body { background: #fff; }
        }
        .print-only { display: none; }
      `}</style>
      {!readOnly ? (
        <Box className="no-print">
          <ManagementHubNav />
        </Box>
      ) : null}
      <Box className="print-only" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 800 }}>
          VeeWash Task Report
        </Typography>
        <Typography variant="body2">
          Date: {date} · Printed {new Date().toLocaleString("en-US", { timeZone: "America/New_York" })} ET
        </Typography>
      </Box>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={1}
        sx={{ mb: 2 }}
        className="no-print"
      >
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            Task Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Track completion, verification, and monthly compliance.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          {canManage ? (
            <Button size="small" variant="outlined" onClick={() => setManageOpen(true)}>
              Manage Tasks
            </Button>
          ) : null}
          {!readOnly ? (
            <Button component={RouterLink} to="/management/task-management" size="small" variant="text">
              Full editor
            </Button>
          ) : null}
          <Button size="small" variant="contained" startIcon={<PrintIcon />} onClick={printReport}>
            Print Report
          </Button>
          <TextField
            type="date"
            size="small"
            label="Date"
            InputLabelProps={{ shrink: true }}
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </Stack>
      </Stack>

      {/* Rinse: no blue informational notices */}
      {!readOnly && data?.approval_policy_label ? (
        <Alert severity="info" sx={{ mb: 2 }} className="no-print">
          {data.approval_policy_label}
        </Alert>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} className="no-print">
          {error}
        </Alert>
      ) : null}

      <TaskDashboardMonthlyChart
        data={monthly}
        year={chartYear}
        month={chartMonth}
        category={chartCategory}
        categories={monthly?.categories || data?.category_breakdown?.map((c) => ({
          code: c.category_code,
          name: c.category_name,
        }))}
        onYearChange={setChartYear}
        onMonthChange={setChartMonth}
        onCategoryChange={setChartCategory}
        loading={monthlyLoading}
      />

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Tabs
            value={categoryTab}
            onChange={(_, v) => setCategoryTab(v)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ mb: 2 }}
            className="no-print"
          >
            {categoryTabs.map((t) => (
              <Tab key={t.code} value={t.code} label={t.name} />
            ))}
          </Tabs>
          <Typography className="print-only" sx={{ fontWeight: 700, mb: 1 }}>
            Category: {categoryTabs.find((t) => t.code === categoryTab)?.name || "All"}
          </Typography>

          <Stack direction="row" flexWrap="wrap" gap={1.25} sx={{ mb: 2.5 }}>
            <Metric label="Assigned" value={categoryMetrics.total_assigned} />
            <Metric label="Started" value={categoryMetrics.started} />
            <Metric label="Completed" value={categoryMetrics.completed} />
            <Metric label="Verified" value={categoryMetrics.verified ?? categoryMetrics.approved} />
            <Metric
              label="Pending Verification"
              value={categoryMetrics.pending_verification ?? categoryMetrics.pending_approval}
            />
            <Metric label="Rejected" value={categoryMetrics.rejected} />
            <Metric label="Overdue" value={categoryMetrics.overdue} />
            <Metric
              label="Completion %"
              value={
                categoryMetrics.completion_rate != null ? `${categoryMetrics.completion_rate}%` : "—"
              }
            />
            {hideLabor ? null : (
              <Metric label="Time on Tasks" value={formatDuration(metrics.time_spent_seconds)} />
            )}
          </Stack>

          {blocking.length && categoryTab === "all" ? (
            <Paper variant="outlined" sx={{ p: 1.5, mb: 2.5, bgcolor: "#fff7ed" }} className="no-print">
              <Typography sx={{ fontWeight: 800, mb: 0.5 }}>
                Before closing the day ({blocking.length})
              </Typography>
              <Stack spacing={0.5}>
                {blocking.slice(0, 12).map((row) => (
                  <Typography key={`${row.responsibility_id}-${row.employee_id}`} variant="body2">
                    {row.role_label || row.role} · {row.employee_name} ·{" "}
                    {friendlyStatusLabel(row.status)}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          ) : null}

          <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
            Assignments
          </Typography>
          <Stack spacing={1} sx={{ mb: 2.5 }}>
            {filteredAssignments.length ? (
              filteredAssignments.map((row) => {
                const open = openKeys.has(row.assignment_key);
                return (
                  <Paper key={row.assignment_key} variant="outlined" sx={{ p: 1.25 }}>
                    <Stack direction="row" alignItems="center" spacing={1}>
                      <IconButton size="small" className="no-print" onClick={() => toggle(row.assignment_key)}>
                        {open ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 800 }}>
                          {row.role_label || row.role}
                          {row.execution_mode === "shared" ? " · Shared" : row.shared ? " · Group" : ""}
                          {row.has_manual_completion ? (
                            <Chip size="small" label="Manual entry" sx={{ ml: 1 }} color="secondary" />
                          ) : null}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {(row.assigned_employees || []).join(" + ")} · {row.timing_label || "Anytime"}
                        </Typography>
                      </Box>
                      <StatusChip status={row.status} />
                    </Stack>
                    <Collapse in={open} className="print-expand">
                      {(row.shared_checklist_items || []).length ? (
                        <Box sx={{ mt: 1, mb: 1, pl: { xs: 1, sm: 5 } }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, display: "block", mb: 0.5 }}>
                            Shared checklist
                          </Typography>
                          {(row.shared_checklist_items || []).map((it) => (
                            <Typography
                              key={it.id || it.task_code}
                              variant="caption"
                              display="block"
                              color="text.secondary"
                            >
                              {it.task_name || it.task_code}: {friendlyStatusLabel(it.status)}
                              {it.completed_by_name ? ` · ${it.completed_by_name}` : ""}
                              {it.completed_at ? ` · ${formatEtWall(it.completed_at)}` : ""}
                            </Typography>
                          ))}
                        </Box>
                      ) : null}
                      <Table size="small" sx={{ mt: 1 }}>
                        <TableHead>
                          <TableRow>
                            <TableCell>Employee</TableCell>
                            <TableCell>Status</TableCell>
                            <TableCell>Start</TableCell>
                            <TableCell>Completed</TableCell>
                            {hideLabor ? null : <TableCell>Duration</TableCell>}
                            <TableCell>Source</TableCell>
                            <TableCell className="no-print" />
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(row.contributions || []).map((c) => {
                            const act = c.activity || {};
                            return (
                              <TableRow key={c.responsibility_id}>
                                <TableCell>
                                  {c.employee_name}
                                  {(c.group_items || []).length ? (
                                    <Box sx={{ mt: 0.5 }}>
                                      {(c.group_items || []).map((gi) => (
                                        <Typography
                                          key={gi.id}
                                          variant="caption"
                                          display="block"
                                          color="text.secondary"
                                        >
                                          {gi.role_label || gi.role}:{" "}
                                          {friendlyStatusLabel(gi.display_status || gi.status)}
                                        </Typography>
                                      ))}
                                    </Box>
                                  ) : null}
                                </TableCell>
                                <TableCell>
                                  <StatusChip status={c.status} />
                                </TableCell>
                                <TableCell>{formatEtWall(act.started_at)}</TableCell>
                                <TableCell>{formatEtWall(act.ended_at)}</TableCell>
                                {hideLabor ? null : (
                                  <TableCell>
                                    {formatDuration(
                                      c.group_duration_seconds ?? act.duration_seconds
                                    )}
                                  </TableCell>
                                )}
                                <TableCell>
                                  <Typography variant="caption">
                                    {act.completion_source_label ||
                                      (act.is_manual_completion
                                        ? "Recorded by Supervisor"
                                        : act.id
                                          ? "Completed via PIN"
                                          : "—")}
                                  </Typography>
                                </TableCell>
                                <TableCell align="right" className="no-print">
                                  <Stack spacing={0.5} alignItems="flex-end">
                                    {!readOnly && c.status === "pending_approval" && act.id ? (
                                      <Stack direction="row" spacing={0.5}>
                                        <Button size="small" disabled={busy} onClick={() => approve(act.id)}>
                                          Verify
                                        </Button>
                                        <Button
                                          size="small"
                                          color="warning"
                                          disabled={busy}
                                          onClick={() => setRejectId(act.id)}
                                        >
                                          Needs correction
                                        </Button>
                                      </Stack>
                                    ) : null}
                                    {canManual && (c.can_record_manual || ["pending", "overdue", "rejected"].includes(c.status)) ? (
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        disabled={busy}
                                        onClick={() => openManual(row, c, "manual")}
                                      >
                                        Record Completion
                                      </Button>
                                    ) : null}
                                    {canManual && c.can_correct && act.id ? (
                                      <Button
                                        size="small"
                                        disabled={busy}
                                        onClick={() => openManual(row, c, "correct")}
                                      >
                                        Correct Record
                                      </Button>
                                    ) : null}
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </Collapse>
                  </Paper>
                );
              })
            ) : (
              <Typography variant="body2" color="text.secondary">
                No cleaning tasks assigned for this date{categoryTab !== "all" ? " in this category" : ""}.
              </Typography>
            )}
          </Stack>

          {(data?.checklists || []).length ? (
            <>
              <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
                Checklists
              </Typography>
              <Stack spacing={1} sx={{ mb: 2.5 }}>
                {(data.checklists || []).map((cl) => (
                  <Paper key={`${cl.checklist_id}-${cl.business_date}`} variant="outlined" sx={{ p: 1.25 }}>
                    <Typography sx={{ fontWeight: 800 }}>
                      {cl.checklist_name} · {friendlyStatusLabel(cl.status)}
                      {cl.completion_pct != null ? ` · ${cl.completion_pct}%` : ""}
                    </Typography>
                    {(cl.groups || []).map((g) => (
                      <Box key={`g-${g.group_id || g.group_name}`} sx={{ mt: 0.75 }}>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          {g.group_name}: {g.required_done}/{g.required_total}
                        </Typography>
                        {(g.items || []).map((item) => (
                          <Typography
                            key={item.task_code}
                            variant="caption"
                            display="block"
                            color="text.secondary"
                            sx={{ pl: 1 }}
                          >
                            {item.task_label}: {friendlyStatusLabel(item.status)}
                          </Typography>
                        ))}
                      </Box>
                    ))}
                  </Paper>
                ))}
              </Stack>
            </>
          ) : null}

          <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
            Activity log
          </Typography>
          <Paper variant="outlined" sx={{ overflow: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Employee</TableCell>
                  <TableCell>Task</TableCell>
                  <TableCell>Start</TableCell>
                  <TableCell>End</TableCell>
                  {hideLabor ? null : <TableCell>Duration</TableCell>}
                  <TableCell>Source</TableCell>
                  <TableCell>Input</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Verified by</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(data?.activity_log || []).length ? (
                  (data.activity_log || [])
                    .filter(
                      (row) =>
                        categoryTab === "all" || (row.category_code || "intra_day") === categoryTab
                    )
                    .map((row) => (
                      <TableRow key={row.id}>
                        <TableCell>{row.employee_name}</TableCell>
                        <TableCell>
                          {row.role_label || row.role}
                          {row.is_manual_completion ? (
                            <Chip size="small" label="Manual" sx={{ ml: 1 }} />
                          ) : null}
                        </TableCell>
                        <TableCell>{formatEtWall(row.started_at)}</TableCell>
                        <TableCell>{formatEtWall(row.ended_at)}</TableCell>
                        {hideLabor ? null : (
                          <TableCell>{formatDuration(row.duration_seconds)}</TableCell>
                        )}
                        <TableCell>
                          <Typography variant="caption">
                            {row.completion_source_label || "Completed via PIN"}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption">
                            {formatCompletionInput(row.completion_input) ||
                              row.manual_reason ||
                              "—"}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <StatusChip status={row.display_status || row.status} />
                        </TableCell>
                        <TableCell>{row.supervisor_name || "—"}</TableCell>
                      </TableRow>
                    ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={hideLabor ? 8 : 9}>
                      <Typography variant="body2" color="text.secondary">
                        No task activity for this date.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>

          {rejectId ? (
            <Paper variant="outlined" sx={{ p: 2, mt: 2 }} className="no-print">
              <Typography sx={{ fontWeight: 700, mb: 1 }}>Correction reason</Typography>
              <TextField
                fullWidth
                size="small"
                multiline
                minRows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <Button variant="contained" color="warning" disabled={busy} onClick={reject}>
                  Mark needs correction
                </Button>
                <Button disabled={busy} onClick={() => setRejectId(null)}>
                  Cancel
                </Button>
              </Stack>
            </Paper>
          ) : null}
        </>
      )}

      {canManage ? (
        <TaskManageDialog open={manageOpen} onClose={() => setManageOpen(false)} />
      ) : null}
      {canManual ? (
        <TaskManualCompletionDialog
          open={manualOpen}
          mode={manualMode}
          assignment={manualTarget.assignment}
          contribution={manualTarget.contribution}
          busy={busy}
          onClose={() => setManualOpen(false)}
          onSubmit={submitManual}
        />
      ) : null}
    </Box>
  );
}
