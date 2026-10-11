import { useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
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
  Typography,
} from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/DeleteOutline";
import {
  createScanChronologyLocalSession,
  deleteScanChronologyLocalSession,
  updateScanChronologyLocalSession,
} from "../api";
import { formatDateTime } from "../utils/foldingFormat";
import { formatIsoEtWall } from "../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

function timeOnly(iso) {
  if (!iso) return "—";
  const formatted = formatDateTime(iso) || "";
  const m = formatted.match(/\d{1,2}:\d{2}\s?[AP]M/i);
  return m ? m[0] : formatted || "—";
}

/** "HH:MM" ET wall for a time input. */
function etInputTime(iso) {
  const wall = formatIsoEtWall(iso);
  return /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(wall) ? wall.slice(11, 16) : "";
}

function fmt(value, digits = 2) {
  const n = Number(value);
  return value == null || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

export function ScanSessionCell({ row, sessionsById }) {
  const session = row.local_session_id ? sessionsById.get(row.local_session_id) : null;
  if (!session) {
    return (
      <Chip
        size="small"
        label="Unassigned"
        sx={{ bgcolor: "#fff7ed", color: "#c2410c", fontWeight: 700, height: 22 }}
      />
    );
  }
  return (
    <Typography variant="body2" sx={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
      {timeOnly(session.start_et)}–{timeOnly(session.end_et)}
    </Typography>
  );
}

const EMPTY_FORM = { id: null, employee: "", role: "", start: "", end: "" };

export default function ScanChronologyLocalSessions({
  dateEt,
  stage,
  localSessions,
  employeeOptions,
  defaultEmployee,
  onChanged,
}) {
  const sessions = localSessions?.sessions || [];
  const roles = localSessions?.roles || [];
  const roleLabel = useMemo(
    () => Object.fromEntries(roles.map((r) => [r.id, r.label])),
    [roles],
  );
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const openNew = () => {
    setError("");
    setForm({ ...EMPTY_FORM, employee: defaultEmployee || "", role: stage });
  };

  const openEdit = (s) => {
    setError("");
    setForm({
      id: s.id,
      employee: s.employee || "",
      role: s.role || stage,
      start: etInputTime(s.start_et),
      end: etInputTime(s.end_et),
    });
  };

  const save = async () => {
    if (!form) return;
    if (!form.employee.trim() || !form.start || !form.end) {
      setError("Employee, start and end are required.");
      return;
    }
    const body = {
      employee: form.employee.trim(),
      role: form.role,
      start_et: `${dateEt}T${form.start}`,
      end_et: `${dateEt}T${form.end}`,
    };
    setSaving(true);
    setError("");
    try {
      if (form.id) await updateScanChronologyLocalSession(form.id, body);
      else await createScanChronologyLocalSession(body);
      setForm(null);
      onChanged?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not save session");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (s) => {
    const label = `${s.employee} ${timeOnly(s.start_et)}–${timeOnly(s.end_et)}`;
    if (!window.confirm(`Delete session for ${label}?`)) return;
    try {
      await deleteScanChronologyLocalSession(s.id);
      onChanged?.();
    } catch (e) {
      window.alert(e?.response?.data?.error || e?.message || "Could not delete session");
    }
  };

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="subtitle2" fontWeight={800}>
          Sessions
        </Typography>
        <Button size="small" variant="outlined" onClick={openNew}>
          Add session
        </Button>
      </Stack>
      {sessions.length === 0 ? (
        <Alert severity="info" sx={{ py: 0 }}>
          No sessions for {dateEt}. Scans stay Unassigned until a session covers them.
        </Alert>
      ) : (
        <TableContainer
          component={Paper}
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
        >
          <Table size="small" sx={{ minWidth: 640 }}>
            <TableHead>
              <TableRow
                sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}
              >
                <TableCell>Employee</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Start</TableCell>
                <TableCell>End</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell align="right">Scans</TableCell>
                <TableCell align="right">Scans/Hour</TableCell>
                <TableCell align="right">Edit/Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.map((s) => (
                <TableRow key={s.id} hover>
                  <TableCell>{s.employee}</TableCell>
                  <TableCell>{roleLabel[s.role] || s.role}</TableCell>
                  <TableCell>{timeOnly(s.start_et)}</TableCell>
                  <TableCell>{timeOnly(s.end_et)}</TableCell>
                  <TableCell align="right">{fmt(s.hours)}</TableCell>
                  <TableCell align="right">{s.scans ?? 0}</TableCell>
                  <TableCell align="right">{fmt(s.scans_per_hour)}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <IconButton size="small" aria-label="Edit session" onClick={() => openEdit(s)}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                    <IconButton size="small" aria-label="Delete session" onClick={() => remove(s)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={Boolean(form)} onClose={() => !saving && setForm(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ pb: 1 }}>
          {form?.id ? "Edit session" : "Add session"} · {dateEt} (ET)
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error ? <Alert severity="error">{error}</Alert> : null}
            <Autocomplete
              freeSolo
              options={employeeOptions || []}
              value={form?.employee || ""}
              onInputChange={(_, value) => setForm((f) => (f ? { ...f, employee: value || "" } : f))}
              renderInput={(params) => <TextField {...params} size="small" label="Employee" />}
            />
            <FormControl size="small">
              <InputLabel>Role</InputLabel>
              <Select
                label="Role"
                value={form?.role || stage}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              >
                {roles.map((r) => (
                  <MenuItem key={r.id} value={r.id}>
                    {r.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                type="time"
                label="Start (ET)"
                value={form?.start || ""}
                onChange={(e) => setForm((f) => ({ ...f, start: e.target.value }))}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
              <TextField
                size="small"
                type="time"
                label="End (ET)"
                value={form?.end || ""}
                onChange={(e) => setForm((f) => ({ ...f, end: e.target.value }))}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Used only for Scan Chronology hours and productivity. Payroll and attendance are not changed.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForm(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
