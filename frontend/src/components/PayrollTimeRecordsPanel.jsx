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
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { getPayrollTimeRecords, getTaUsers, patchSessionPayrollLine } from "../api";
import { formatEasternDateTime } from "../utils/datetimeFormat";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "completed", label: "Completed" },
  { value: "approved", label: "Approved" },
  { value: "needs_correction", label: "Needs correction" },
];

function statusColor(st) {
  if (st === "open") return "info";
  if (st === "approved") return "success";
  if (st === "needs_correction") return "warning";
  return "default";
}

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
  const [detail, setDetail] = useState(null);
  const [noteDraft, setNoteDraft] = useState("");

  useEffect(() => {
    getTaUsers()
      .then((r) => setUsers(r.data?.users || r.data || []))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate;
      if (category !== "all") params.worker_category = category;
      if (status !== "all") params.status = status;
      if (userId) params.user_id = userId;
      const res = await getPayrollTimeRecords(params);
      setRows(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, category, status, userId]);

  useEffect(() => {
    load();
  }, [load]);

  const saveNote = async () => {
    if (!detail?.id) return;
    try {
      await patchSessionPayrollLine(detail.id, { period_adjustment_remarks: noteDraft });
      setDetail(null);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || "Save failed");
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Time Records
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Review clock-in/out and approve hours before creating payout batches.
        </Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
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
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Worker category</InputLabel>
            <Select label="Worker category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Status</InputLabel>
            <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 180 }}>
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
          <Button variant="contained" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Apply filters"}
          </Button>
        </Stack>
      </Paper>

      <Table size="small" component={Paper}>
        <TableHead>
          <TableRow>
            <TableCell>Date</TableCell>
            <TableCell>Worker</TableCell>
            <TableCell>Category</TableCell>
            <TableCell>Clock in</TableCell>
            <TableCell>Clock out</TableCell>
            <TableCell>Break</TableCell>
            <TableCell>Total hours</TableCell>
            <TableCell>Approved hrs</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Notes</TableCell>
            <TableCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} hover>
              <TableCell>{r.work_date}</TableCell>
              <TableCell>{r.worker_name}</TableCell>
              <TableCell>{r.worker_category_label}</TableCell>
              <TableCell>{formatEasternDateTime(r.clock_in_at)}</TableCell>
              <TableCell>{formatEasternDateTime(r.clock_out_at)}</TableCell>
              <TableCell>{Math.round((r.break_seconds || 0) / 60)}m</TableCell>
              <TableCell>{r.total_hours_display}</TableCell>
              <TableCell>{r.approved_hours_display}</TableCell>
              <TableCell>
                <Chip size="small" label={r.status} color={statusColor(r.status)} />
              </TableCell>
              <TableCell sx={{ maxWidth: 120 }} noWrap>
                {r.notes || "—"}
              </TableCell>
              <TableCell>
                <Button size="small" onClick={() => { setDetail(r); setNoteDraft(r.notes || ""); }}>
                  View
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {!rows.length && !loading ? (
            <TableRow>
              <TableCell colSpan={11}>
                <Typography color="text.secondary">No records for these filters.</Typography>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>

      <Dialog open={!!detail} onClose={() => setDetail(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Time record — {detail?.worker_name}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" gutterBottom>
            {detail?.worker_category_label} · {detail?.work_date}
          </Typography>
          <Typography variant="body2">
            Clock in: {formatEasternDateTime(detail?.clock_in_at)}
          </Typography>
          <Typography variant="body2">
            Clock out: {formatEasternDateTime(detail?.clock_out_at)}
          </Typography>
          <Typography variant="body2" sx={{ mt: 1 }}>
            Approved hours: {detail?.approved_hours_display}
          </Typography>
          <TextField
            fullWidth
            multiline
            minRows={3}
            label="Notes / correction"
            sx={{ mt: 2 }}
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetail(null)}>Close</Button>
          <Button variant="contained" onClick={saveNote}>
            Save note
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
