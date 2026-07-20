import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import AddIcon from "@mui/icons-material/Add";
import AttachMoneyIcon from "@mui/icons-material/AttachMoney";
import CheckIcon from "@mui/icons-material/Check";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import {
  deletePayrollTimeRecord,
  getPayrollCalendarSettings,
  getPayrollScheduleSettings,
  getPayrollScheduleWorkers,
  getPayrollTimeRecords,
  getTaUsers,
  patchPayrollTimeRecord,
  postApprovePayrollTimeRecord,
  postBulkApprovePayrollTimeRecords,
  postPayrollTimeRecord,
} from "../api";
import {
  formatEasternTimeShort,
  formatHoursDecimal,
} from "../utils/datetimeFormat";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";
import {
  buildWorkerRateMap,
  enrichTimeRecords,
  formatPayrollMoney,
  formatPayrollRate,
} from "../payroll/timeRecordPayroll";
import { PayrollDateField, PayrollDateTimeField } from "./PayrollDateTimeField";
import JobTrackingAdminDialog from "./JobTrackingAdminDialog";
import { useAuth } from "../context/AuthContext";

const CATEGORY_SHORT = {
  w2: "W-2",
  contractor_1099: "1099",
  temp: "Temp",
};

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "completed", label: "Awaiting approval" },
  { value: "pending_approval", label: "Pending approval" },
  { value: "approved", label: "Approved" },
];

function statusLabel(st) {
  if (st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  if (st === "open") return "Open";
  if (st === "completed") return "Awaiting approval";
  return st || "—";
}

function statusColor(st) {
  if (st === "open") return "info";
  if (st === "approved") return "success";
  if (st === "pending_approval" || st === "completed") return "warning";
  return "default";
}

function canApproveRecord(row) {
  return (
    row?.status === "pending_approval" ||
    row?.status === "completed" ||
    (row?.status !== "approved" && row?.status !== "open" && !row?.payroll_hours_approved)
  );
}

function toDatetimeLocal(val) {
  if (!val) return "";
  const s = String(val).trim().replace(" ", "T");
  if (s.length >= 16) return s.slice(0, 16);
  return s;
}

function toApiDateTime(local) {
  if (!local) return "";
  return local.length === 16 ? `${local.replace("T", " ")}:00` : local;
}

const emptyForm = () => ({
  user_id: "",
  clock_in_at: "",
  clock_out_at: "",
  notes: "",
});

function hoursCellSx(level, theme) {
  if (level === "critical") {
    return {
      bgcolor: alpha(theme.palette.error.main, 0.14),
      color: theme.palette.error.dark,
      fontWeight: 700,
    };
  }
  if (level === "warning") {
    return {
      bgcolor: alpha(theme.palette.warning.main, 0.18),
      color: theme.palette.warning.dark,
      fontWeight: 600,
    };
  }
  return { fontVariantNumeric: "tabular-nums" };
}

function SummaryStat({ icon, label, value, valueSx, details = [], gradient }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.75,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
        background: gradient,
      }}
    >
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Box
          sx={{
            width: 40,
            height: 40,
            borderRadius: 1.5,
            display: "grid",
            placeItems: "center",
            bgcolor: "background.paper",
            boxShadow: 1,
            flexShrink: 0,
          }}
        >
          {icon}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: 0.4 }}>
            {label}
          </Typography>
          <Typography variant="h6" sx={{ lineHeight: 1.2, fontWeight: 700, ...valueSx }}>
            {value}
          </Typography>
          {details.map((line) => (
            <Typography key={line} variant="caption" color="text.secondary" display="block">
              {line}
            </Typography>
          ))}
        </Box>
      </Stack>
    </Paper>
  );
}

export default function PayrollTimeRecordsPanel({
  payPeriodStart = "",
  payPeriodEnd = "",
  linkedCategory = "all",
  onPayPeriodChange,
}) {
  const theme = useTheme();
  const { hasPerm } = useAuth();
  const canJobTrackingAdmin = hasPerm("ta.override");
  const [fromDate, setFromDate] = useState(payPeriodStart || "");
  const [toDate, setToDate] = useState(payPeriodEnd || "");
  const [category, setCategory] = useState(linkedCategory || "all");
  const [status, setStatus] = useState("all");
  const [userId, setUserId] = useState("");
  const [users, setUsers] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [scheduleSettings, setScheduleSettings] = useState(null);
  const [calendarSettings, setCalendarSettings] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState("add");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const [bulkApproving, setBulkApproving] = useState(false);
  const [jobTrackingTarget, setJobTrackingTarget] = useState(null);

  useEffect(() => {
    getTaUsers()
      .then((r) => setUsers(r.data?.users || r.data || []))
      .catch(() => {});
    getPayrollScheduleWorkers()
      .then((r) => setWorkers(r.data?.items || []))
      .catch(() => {});
    getPayrollScheduleSettings()
      .then((r) => setScheduleSettings(r.data || null))
      .catch(() => {});
    getPayrollCalendarSettings()
      .then((r) => setCalendarSettings(r.data || null))
      .catch(() => {});
  }, []);

  const rateMap = useMemo(
    () => buildWorkerRateMap(workers, scheduleSettings, calendarSettings, rows),
    [workers, scheduleSettings, calendarSettings, rows],
  );

  const {
    rows: displayRows,
    totalHours,
    totalCost,
    totalRegularCost,
    totalOtCost,
    summaryHoursLevel,
  } = useMemo(
    () => enrichTimeRecords(rows, rateMap, { userId }),
    [rows, rateMap, userId],
  );

  const summaryHoursSx = useMemo(() => {
    if (summaryHoursLevel === "critical") {
      return { color: theme.palette.error.dark };
    }
    if (summaryHoursLevel === "warning") {
      return { color: theme.palette.warning.dark };
    }
    return undefined;
  }, [summaryHoursLevel, theme]);

  const approvableRows = rows.filter(canApproveRecord);

  useEffect(() => {
    if (payPeriodStart) setFromDate(payPeriodStart);
  }, [payPeriodStart]);

  useEffect(() => {
    if (payPeriodEnd) setToDate(payPeriodEnd);
  }, [payPeriodEnd]);

  useEffect(() => {
    if (linkedCategory && linkedCategory !== "all") setCategory(linkedCategory);
  }, [linkedCategory]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate;
      if (category !== "all") params.worker_category = category;
      if (status !== "all") params.status = status;
      if (userId) params.user_id = userId;
      const res = await getPayrollTimeRecords(params);
      setRows(res.data?.items || []);
      setError("");
    } catch (e) {
      if (e.code === "ERR_NETWORK") {
        setError(
          "Could not reach the server. Check your connection or wait for the API deploy to finish.",
        );
      } else {
        setError(e.response?.data?.error || e.message || "Load failed");
      }
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, category, status, userId]);

  useEffect(() => {
    load();
  }, [load]);

  const openAdd = () => {
    setEditorMode("add");
    setEditingId(null);
    setForm(emptyForm());
    setEditorOpen(true);
  };

  const openEdit = (row) => {
    setEditorMode("edit");
    setEditingId(row.id);
    setForm({
      user_id: String(row.user_id || ""),
      clock_in_at: toDatetimeLocal(row.clock_in_at),
      clock_out_at: toDatetimeLocal(row.clock_out_at),
      notes: row.notes || "",
    });
    setEditorOpen(true);
  };

  const saveEditor = async () => {
    if (!form.user_id || !form.clock_in_at) {
      setError("Worker and clock in are required.");
      return;
    }
    const clockOutApi = form.clock_out_at ? toApiDateTime(form.clock_out_at) : "";
    if (clockOutApi && form.clock_in_at && clockOutApi <= toApiDateTime(form.clock_in_at)) {
      setError("Clock out must be after clock in.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const remarks = (form.notes || "").trim() || "Payroll time record update";
      const payload = {
        clock_in_at: toApiDateTime(form.clock_in_at),
        clock_out_at: clockOutApi,
        remarks: editorMode === "add" ? remarks : form.notes || "",
      };
      if (editorMode === "add") {
        await postPayrollTimeRecord({
          user_id: Number(form.user_id),
          ...payload,
        });
      } else if (editingId) {
        await patchPayrollTimeRecord(editingId, payload);
      }
      setEditorOpen(false);
      await load();
    } catch (e) {
      if (e.response?.data?.error) {
        setError(e.response.data.error);
      } else if (e.code === "ERR_NETWORK") {
        setError(
          "Save blocked by browser (API CORS). Hard-refresh after deploy, or contact support if this persists.",
        );
      } else {
        setError(e.message || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  const approveRecord = async (row) => {
    setError("");
    try {
      await postApprovePayrollTimeRecord(row.id);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Approve failed");
    }
  };

  const bulkApproveVisible = async () => {
    if (!approvableRows.length) return;
    setBulkApproving(true);
    setError("");
    try {
      const res = await postBulkApprovePayrollTimeRecords({
        ids: approvableRows.map((r) => r.id),
      });
      const n = res.data?.approved || 0;
      const skipped = res.data?.skipped || 0;
      if (skipped) {
        setError(`Approved ${n} record(s). ${skipped} could not be approved.`);
      }
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Bulk approve failed");
    } finally {
      setBulkApproving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget?.id) return;
    setSaving(true);
    setError("");
    try {
      await deletePayrollTimeRecord(deleteTarget.id);
      setDeleteTarget(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
          sx={{ mb: 1 }}
        >
          <Typography variant="subtitle1">Time Records</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button
              variant="contained"
              size="small"
              color="success"
              startIcon={<CheckIcon />}
              onClick={bulkApproveVisible}
              disabled={bulkApproving || !approvableRows.length}
            >
              {bulkApproving
                ? "Approving…"
                : `Bulk approve (${approvableRows.length})`}
            </Button>
            <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openAdd}>
              Add record
            </Button>
          </Stack>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Review clock-in/out, then click <strong>Approve</strong>. Approved hours in this date range
          sync into matching payout batches automatically.
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: "repeat(2, 1fr)",
              md: "repeat(3, minmax(140px, 1fr)) auto",
            },
            gap: 1.5,
            alignItems: "end",
          }}
        >
          <FormControl size="small">
            <InputLabel>Worker category</InputLabel>
            <Select
              label="Worker category"
              value={category}
              onChange={(e) => {
                const v = e.target.value;
                setCategory(v);
                onPayPeriodChange?.({ start: fromDate, end: toDate, category: v });
              }}
            >
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small">
            <InputLabel>Status</InputLabel>
            <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small">
            <InputLabel>Worker</InputLabel>
            <Select label="Worker" value={userId} onChange={(e) => setUserId(e.target.value)}>
              <MenuItem value="">All</MenuItem>
              {users.map((u) => (
                <MenuItem key={u.id} value={String(u.id)}>
                  {u.first_name} {u.last_name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button variant="outlined" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Apply filters"}
          </Button>
        </Box>
      </Paper>

      <Paper
        elevation={0}
        sx={{
          p: 2,
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
          background: `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.04)} 0%, ${alpha(theme.palette.background.paper, 1)} 100%)`,
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={2}
          sx={{ mb: 2 }}
        >
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Period summary
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {fromDate && toDate ? `${fromDate} – ${toDate}` : "Set dates to see totals"}
              {userId ? " · filtered to one worker" : ""}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              variant="outlined"
              label=">35h orange"
              sx={{ borderColor: alpha(theme.palette.warning.main, 0.5) }}
            />
            <Chip
              size="small"
              variant="outlined"
              color="error"
              label="≥40h red"
            />
          </Stack>
        </Stack>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 1.5,
            mb: 2,
          }}
        >
          <SummaryStat
            icon={<AccessTimeIcon color="primary" fontSize="small" />}
            label="Total hours"
            value={formatHoursDecimal(totalHours)}
            valueSx={summaryHoursSx}
            details={[
              `${displayRows.length} record${displayRows.length === 1 ? "" : "s"}`,
              summaryHoursLevel === "critical"
                ? "At or above 40h — overtime"
                : summaryHoursLevel === "warning"
                  ? "Above 35h — approaching overtime"
                  : null,
            ].filter(Boolean)}
            gradient={
              summaryHoursLevel === "critical"
                ? `linear-gradient(135deg, ${alpha(theme.palette.error.main, 0.12)} 0%, ${alpha(theme.palette.error.main, 0.03)} 100%)`
                : summaryHoursLevel === "warning"
                  ? `linear-gradient(135deg, ${alpha(theme.palette.warning.main, 0.14)} 0%, ${alpha(theme.palette.warning.main, 0.03)} 100%)`
                  : `linear-gradient(135deg, ${alpha(theme.palette.primary.main, 0.08)} 0%, ${alpha(theme.palette.primary.main, 0.02)} 100%)`
            }
          />
          <SummaryStat
            icon={<AttachMoneyIcon color="success" fontSize="small" />}
            label="Total cost"
            value={formatPayrollMoney(totalCost, { allowZero: true })}
            details={[
              `Regular/Base ${formatPayrollMoney(totalRegularCost, { allowZero: true })}`,
              `OT Premium ${formatPayrollMoney(totalOtCost, { allowZero: true })}`,
              "Same rules for W-2, 1099, and temp",
            ]}
            gradient={`linear-gradient(135deg, ${alpha(theme.palette.success.main, 0.1)} 0%, ${alpha(theme.palette.success.main, 0.02)} 100%)`}
          />
        </Box>

      <TableContainer sx={{ width: "100%", overflowX: "auto", borderRadius: 1.5 }}>
        <Table size="small" sx={{ minWidth: 980 }}>
          <TableHead>
            <TableRow
              sx={{
                "& th": {
                  fontWeight: 700,
                  fontSize: "0.75rem",
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  bgcolor: alpha(theme.palette.primary.main, 0.06),
                  borderBottom: `2px solid ${alpha(theme.palette.primary.main, 0.2)}`,
                  whiteSpace: "nowrap",
                },
              }}
            >
              <TableCell>Date</TableCell>
              <TableCell>Worker</TableCell>
              <TableCell>Cat.</TableCell>
              <TableCell>In</TableCell>
              <TableCell>Out</TableCell>
              <TableCell align="right">Hrs</TableCell>
              <TableCell align="right">Reg rate</TableCell>
              <TableCell align="right">OT rate</TableCell>
              <TableCell align="right">Total</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {displayRows.map((r) => (
              <TableRow
                key={r.id}
                hover
                sx={{
                  "&:nth-of-type(even)": {
                    bgcolor: alpha(theme.palette.action.hover, 0.04),
                  },
                }}
              >
                <TableCell sx={{ whiteSpace: "nowrap" }}>{r.work_date}</TableCell>
                <TableCell
                  sx={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  title={r.worker_name}
                >
                  {r.worker_name}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  {CATEGORY_SHORT[r.worker_category] || r.worker_category_label}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{formatEasternTimeShort(r.clock_in_at)}</TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{formatEasternTimeShort(r.clock_out_at)}</TableCell>
                <TableCell
                  align="right"
                  sx={{
                    whiteSpace: "nowrap",
                    ...hoursCellSx(r.hours_level, theme),
                  }}
                  title={
                    r.hours_level !== "normal"
                      ? `${formatHoursDecimal(r.worker_period_hours)} total for ${r.worker_name} in this period`
                      : undefined
                  }
                >
                  {formatHoursDecimal(r.approved_hours)}
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {formatPayrollRate(r.regular_rate)}
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                  {formatPayrollRate(r.ot_rate)}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{
                    whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums",
                    fontWeight: 600,
                    ...hoursCellSx(r.hours_level, theme),
                  }}
                >
                  {formatPayrollMoney(r.row_total)}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  <Chip size="small" label={statusLabel(r.status)} color={statusColor(r.status)} />
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                  {canApproveRecord(r) ? (
                    <Tooltip title="Approve for payroll">
                      <IconButton
                        size="small"
                        color="success"
                        onClick={() => approveRecord(r)}
                        aria-label="Approve"
                      >
                        <CheckIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  ) : null}
                  <Tooltip title="Edit">
                    <IconButton size="small" onClick={() => openEdit(r)} aria-label="Edit">
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  {canJobTrackingAdmin ? (
                    <Tooltip title="Task tracking / force check-out">
                      <IconButton
                        size="small"
                        onClick={() => setJobTrackingTarget(r)}
                        aria-label="Job tracking controls"
                      >
                        <WorkOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  ) : null}
                  <Tooltip title="Delete">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => setDeleteTarget(r)}
                      aria-label="Delete"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {!displayRows.length && !loading ? (
              <TableRow>
                <TableCell colSpan={11}>
                  <Typography color="text.secondary">No records for these filters.</Typography>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
      </Paper>

      <Dialog open={editorOpen} onClose={() => setEditorOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editorMode === "add" ? "Add time record" : "Edit time record"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <FormControl fullWidth size="small" disabled={editorMode === "edit"}>
              <InputLabel>Worker</InputLabel>
              <Select
                label="Worker"
                value={form.user_id}
                onChange={(e) => setForm((f) => ({ ...f, user_id: e.target.value }))}
              >
                {users.map((u) => (
                  <MenuItem key={u.id} value={String(u.id)}>
                    {u.first_name} {u.last_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <PayrollDateTimeField
              label="Clock in"
              value={form.clock_in_at}
              onChange={(v) => setForm((f) => ({ ...f, clock_in_at: v }))}
            />
            <PayrollDateTimeField
              label="Clock out (optional)"
              value={form.clock_out_at}
              onChange={(v) => setForm((f) => ({ ...f, clock_out_at: v }))}
              clearable
            />
            <Typography variant="caption" color="text.secondary">
              Leave clock out blank to start an open shift — the employee can clock out later from the time clock.
            </Typography>
            <TextField
              fullWidth
              size="small"
              multiline
              minRows={2}
              label="Notes / correction"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditorOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveEditor} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete time record?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Remove {deleteTarget?.worker_name} on {deleteTarget?.work_date}? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete} disabled={saving}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <JobTrackingAdminDialog
        open={!!jobTrackingTarget}
        record={jobTrackingTarget}
        onClose={() => setJobTrackingTarget(null)}
        onSaved={() => {
          load();
        }}
      />
    </Stack>
  );
}
