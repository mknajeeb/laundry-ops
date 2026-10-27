import { useCallback, useEffect, useState } from "react";
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
import ManagementHubNav from "../components/management/ManagementHubNav";
import {
  approveManagementTaskDashboard,
  getManagementTaskDashboard,
  rejectManagementTaskDashboard,
} from "../api";
import { businessTodayYmd } from "../utils/businessTime";
import { formatCompletionInput } from "../opsMobile/TaskCompletionInputs";

function Metric({ label, value }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, minWidth: 120, flex: "1 1 120px" }}>
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

function statusChip(status) {
  const color =
    status === "approved"
      ? "success"
      : status === "pending_approval"
        ? "warning"
        : status === "rejected" || status === "overdue"
          ? "error"
          : "default";
  return <Chip size="small" label={status || "—"} color={color} />;
}

/**
 * Management Task Dashboard — cleaning/operational compliance.
 * Shared tasks count once; member contributions nest under each assignment.
 * Rinse viewers receive read_only=true from the API.
 */
export default function ManagementTasksPage() {
  const [date, setDate] = useState(() => businessTodayYmd());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rejectId, setRejectId] = useState(null);
  const [reason, setReason] = useState("");
  const [openKeys, setOpenKeys] = useState(() => new Set());

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

  useEffect(() => {
    load();
  }, [load]);

  const metrics = data?.metrics || {};
  const readOnly = data?.read_only === true;
  const shiftEnd = data?.shift_end || {};
  const blocking = shiftEnd.blocking_close || [];

  const approve = async (id) => {
    if (readOnly) return;
    setBusy(true);
    try {
      await approveManagementTaskDashboard({ activity_id: id });
      await load();
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

  const toggle = (key) => {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2.5 }, maxWidth: 1200, mx: "auto" }}>
      {!readOnly ? <ManagementHubNav /> : null}
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={1}
        sx={{ mb: 2 }}
      >
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            Task Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Operational task compliance by category. Shared tasks count once; verify each
            employee&apos;s contribution separately when verification is required.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          {!readOnly ? (
            <Button component={RouterLink} to="/management/task-management" size="small" variant="outlined">
              Task Management
            </Button>
          ) : null}
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
      {data?.approval_policy_label ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {data.approval_policy_label}
        </Alert>
      ) : null}
      {readOnly ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Rinse read-only view — completion, compliance, and approvals are visible; editing is
          disabled.
        </Alert>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Stack direction="row" flexWrap="wrap" gap={1.25} sx={{ mb: 2.5 }}>
            <Metric label="Assigned" value={metrics.total_assigned} />
            <Metric label="Started" value={metrics.started} />
            <Metric label="Completed" value={metrics.completed} />
            <Metric label="Verified" value={metrics.verified ?? metrics.approved} />
            <Metric
              label="Pending Verification"
              value={metrics.pending_verification ?? metrics.pending_approval}
            />
            <Metric label="Rejected" value={metrics.rejected} />
            <Metric label="Overdue" value={metrics.overdue} />
            <Metric
              label="Completion %"
              value={metrics.completion_rate != null ? `${metrics.completion_rate}%` : "—"}
            />
            <Metric
              label="Verification %"
              value={metrics.verification_rate != null ? `${metrics.verification_rate}%` : "—"}
            />
            <Metric label="Time on Tasks" value={formatDuration(metrics.time_spent_seconds)} />
          </Stack>

          {(data?.category_breakdown || []).length ? (
            <Stack direction="row" flexWrap="wrap" gap={1.25} sx={{ mb: 2.5 }}>
              {(data.category_breakdown || []).map((cat) => (
                <Paper key={cat.category_code} variant="outlined" sx={{ p: 1.25, minWidth: 160 }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {cat.category_name}
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    {cat.completed || 0}/{cat.assigned || 0} done · {cat.pending_verification || 0}{" "}
                    pending verify
                  </Typography>
                </Paper>
              ))}
            </Stack>
          ) : null}

          {blocking.length ? (
            <Paper variant="outlined" sx={{ p: 1.5, mb: 2.5, bgcolor: "#fff7ed" }}>
              <Typography sx={{ fontWeight: 800, mb: 0.5 }}>
                Before closing the day ({blocking.length})
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Incomplete, overdue, rejected, and pending-verification contributions still need
                attention. Completed-but-unverified stay in Pending Verification.
              </Typography>
              <Stack spacing={0.5}>
                {blocking.slice(0, 12).map((row) => (
                  <Typography key={`${row.responsibility_id}-${row.employee_id}`} variant="body2">
                    {row.role_label || row.role} · {row.employee_name} · {row.status}
                  </Typography>
                ))}
                {blocking.length > 12 ? (
                  <Typography variant="caption" color="text.secondary">
                    +{blocking.length - 12} more
                  </Typography>
                ) : null}
              </Stack>
            </Paper>
          ) : (
            <Alert severity="success" sx={{ mb: 2.5 }}>
              No incomplete, overdue, or pending-approval cleaning tasks for this date.
            </Alert>
          )}

          <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
            Assignments
          </Typography>
          <Stack spacing={1} sx={{ mb: 2.5 }}>
            {(data?.shared_assignments || []).length ? (
              (data.shared_assignments || []).map((row) => {
                const open = openKeys.has(row.assignment_key);
                return (
                  <Paper key={row.assignment_key} variant="outlined" sx={{ p: 1.25 }}>
                    <Stack direction="row" alignItems="center" spacing={1}>
                      <IconButton size="small" onClick={() => toggle(row.assignment_key)}>
                        {open ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 800 }}>
                          {row.role_label || row.role}
                          {row.shared ? " (shared)" : ""}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {(row.assigned_employees || []).join(" + ")} · {row.timing_label || "Anytime"}
                        </Typography>
                      </Box>
                      {statusChip(row.status)}
                    </Stack>
                    <Collapse in={open}>
                      <Table size="small" sx={{ mt: 1 }}>
                        <TableHead>
                          <TableRow>
                            <TableCell>Employee</TableCell>
                            <TableCell>Status</TableCell>
                            <TableCell>Duration</TableCell>
                            <TableCell />
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(row.contributions || []).map((c) => (
                            <TableRow key={c.responsibility_id}>
                              <TableCell>{c.employee_name}</TableCell>
                              <TableCell>{statusChip(c.status)}</TableCell>
                              <TableCell>
                                {formatDuration(c.activity?.duration_seconds)}
                              </TableCell>
                              <TableCell align="right">
                                {!readOnly && c.status === "pending_approval" && c.activity?.id ? (
                                  <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                                    <Button size="small" disabled={busy} onClick={() => approve(c.activity.id)}>
                                      Approve
                                    </Button>
                                    <Button
                                      size="small"
                                      color="warning"
                                      disabled={busy}
                                      onClick={() => setRejectId(c.activity.id)}
                                    >
                                      Redo
                                    </Button>
                                  </Stack>
                                ) : null}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </Collapse>
                  </Paper>
                );
              })
            ) : (
              <Typography variant="body2" color="text.secondary">
                No cleaning tasks assigned for this date.
              </Typography>
            )}
          </Stack>

          <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
            Duration by employee / task
          </Typography>
          <Paper variant="outlined" sx={{ overflow: "auto", mb: 2.5 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Employee</TableCell>
                  <TableCell>Task</TableCell>
                  <TableCell>Duration</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(data?.durations || []).length ? (
                  (data.durations || []).map((row) => (
                    <TableRow key={row.activity_id}>
                      <TableCell>{row.employee_name}</TableCell>
                      <TableCell>{row.role_label || row.role}</TableCell>
                      <TableCell>{formatDuration(row.duration_seconds)}</TableCell>
                      <TableCell>
                        {statusChip(row.status)}
                        {row.verified ? (
                          <Chip size="small" label="Verified" color="success" sx={{ ml: 1 }} />
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Typography variant="body2" color="text.secondary">
                        No recorded durations yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>

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
                  <TableCell>Duration</TableCell>
                  <TableCell>Input</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Verified by</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(data?.activity_log || []).length ? (
                  (data.activity_log || []).map((row) => (
                    <TableRow key={row.id}>
                      <TableCell>{row.employee_name}</TableCell>
                      <TableCell>
                        {row.role_label || row.role}
                        {row.category_code ? (
                          <Typography variant="caption" display="block" color="text.secondary">
                            {row.category_code}
                          </Typography>
                        ) : null}
                        {row.verified ? (
                          <Chip size="small" label="Verified" color="success" sx={{ ml: 1 }} />
                        ) : null}
                      </TableCell>
                      <TableCell>{row.started_at || "—"}</TableCell>
                      <TableCell>{row.ended_at || "—"}</TableCell>
                      <TableCell>{formatDuration(row.duration_seconds)}</TableCell>
                      <TableCell>
                        <Typography variant="caption">
                          {formatCompletionInput(row.completion_input) || "—"}
                        </Typography>
                      </TableCell>
                      <TableCell>{row.display_status || row.status}</TableCell>
                      <TableCell>{row.supervisor_name || "—"}</TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={8}>
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
            <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
              <Typography sx={{ fontWeight: 700, mb: 1 }}>Rejection reason</Typography>
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
                  Reject
                </Button>
                <Button disabled={busy} onClick={() => setRejectId(null)}>
                  Cancel
                </Button>
              </Stack>
            </Paper>
          ) : null}
        </>
      )}
    </Box>
  );
}
