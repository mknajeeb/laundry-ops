import { useCallback, useEffect, useState } from "react";
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
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CheckIcon from "@mui/icons-material/Check";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import {
  deletePayrollTimeRecord,
  getPayrollTimeRecords,
  getTaUsers,
  patchPayrollTimeRecord,
  postApprovePayrollTimeRecord,
  postPayrollTimeRecord,
} from "../api";
import {
  formatEasternTimeShort,
  formatHoursDecimal,
} from "../utils/datetimeFormat";

const CATEGORY_SHORT = {
  w2: "W-2",
  contractor_1099: "1099",
  temp: "Temp",
};
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "completed", label: "Completed" },
  { value: "pending_approval", label: "Pending approval" },
  { value: "approved", label: "Approved" },
];

function statusLabel(st) {
  if (st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  if (st === "open") return "Open";
  if (st === "completed") return "Completed";
  return st || "—";
}

function statusColor(st) {
  if (st === "open") return "info";
  if (st === "approved") return "success";
  if (st === "pending_approval") return "warning";
  return "default";
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

export default function PayrollTimeRecordsPanel() {
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const [userId, setUserId] = useState("");
  const [users, setUsers] = useState([]);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState("add");
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getTaUsers()
      .then((r) => setUsers(r.data?.users || r.data || []))
      .catch(() => {});
  }, []);

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
    if (!form.user_id || !form.clock_in_at || !form.clock_out_at) {
      setError("Worker, clock in, and clock out are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const remarks = (form.notes || "").trim() || "Payroll time record update";
      if (editorMode === "add") {
        await postPayrollTimeRecord({
          user_id: Number(form.user_id),
          clock_in_at: toApiDateTime(form.clock_in_at),
          clock_out_at: toApiDateTime(form.clock_out_at),
          remarks,
        });
      } else if (editingId) {
        await patchPayrollTimeRecord(editingId, {
          clock_in_at: toApiDateTime(form.clock_in_at),
          clock_out_at: toApiDateTime(form.clock_out_at),
          remarks: form.notes || "",
        });
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
          <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openAdd}>
            Add record
          </Button>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Review clock-in/out, then click <strong>Approve</strong> on each row before pulling hours into a
          payout batch.
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
          <TextField
            size="small"
            type="date"
            label="Start date"
            InputLabelProps={{ shrink: true }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <TextField
            size="small"
            type="date"
            label="End date"
            InputLabelProps={{ shrink: true }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
          <FormControl size="small">
            <InputLabel>Worker category</InputLabel>
            <Select label="Worker category" value={category} onChange={(e) => setCategory(e.target.value)}>
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

      <TableContainer component={Paper} sx={{ width: "100%", overflowX: "auto" }}>
        <Table size="small" sx={{ minWidth: 720 }}>
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Worker</TableCell>
              <TableCell>Cat.</TableCell>
              <TableCell>In</TableCell>
              <TableCell>Out</TableCell>
              <TableCell align="right">Hrs</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id} hover>
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
                <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                  {formatHoursDecimal(r.approved_hours)}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  <Chip size="small" label={statusLabel(r.status)} color={statusColor(r.status)} />
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                  {r.status === "pending_approval" || r.status === "completed" ? (
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
            {!rows.length && !loading ? (
              <TableRow>
                <TableCell colSpan={8}>
                  <Typography color="text.secondary">No records for these filters.</Typography>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>

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
            <TextField
              fullWidth
              size="small"
              type="datetime-local"
              label="Clock in"
              InputLabelProps={{ shrink: true }}
              value={form.clock_in_at}
              onChange={(e) => setForm((f) => ({ ...f, clock_in_at: e.target.value }))}
            />
            <TextField
              fullWidth
              size="small"
              type="datetime-local"
              label="Clock out"
              InputLabelProps={{ shrink: true }}
              value={form.clock_out_at}
              onChange={(e) => setForm((f) => ({ ...f, clock_out_at: e.target.value }))}
            />
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
    </Stack>
  );
}
