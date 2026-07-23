import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import {
  getMaintenanceTaskDefinitions,
  getMaintenanceTaskListDetail,
  getMaintenanceTaskListMeta,
  getMaintenanceTaskListReports,
} from "../api";
import {
  formatDateShort,
  formatTimeEt,
  isCompletedStatus,
  statusLabel,
} from "../utils/maintenanceTaskListHelpers";

function StatusChip({ status }) {
  const color = isCompletedStatus(status)
    ? "success"
    : status === "in_progress"
      ? "warning"
      : "default";
  return <Chip size="small" color={color} label={statusLabel(status)} />;
}

export default function MaintenanceTaskListReportsPage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  const [taskDate, setTaskDate] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [status, setStatus] = useState("");
  const [completed, setCompleted] = useState("");
  const [definitionId, setDefinitionId] = useState("");
  const [definitions, setDefinitions] = useState([]);
  const [rows, setRows] = useState([]);
  const [dateDisplay, setDateDisplay] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const meta = await getMaintenanceTaskListMeta();
        setTaskDate(meta.data?.today || "");
        setDateDisplay(meta.data?.today_display || "");
      } catch {
        /* ignore */
      }
      try {
        const defs = await getMaintenanceTaskDefinitions({ include_inactive: 1 });
        setDefinitions(defs.data?.definitions || []);
      } catch {
        setDefinitions([]);
      }
    })();
  }, []);

  const load = useCallback(async () => {
    if (!taskDate) return;
    setLoading(true);
    setError("");
    try {
      const res = await getMaintenanceTaskListReports({
        task_date: taskDate,
        ...(employeeId ? { employee_id: employeeId } : {}),
        ...(status ? { status } : {}),
        ...(completed ? { completed } : {}),
        ...(definitionId ? { definition_id: definitionId } : {}),
      });
      setRows(res.data?.rows || []);
      setDateDisplay(res.data?.task_date_display || dateDisplay);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load reports");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [taskDate, employeeId, status, completed, definitionId, dateDisplay]);

  useEffect(() => {
    load();
  }, [load]);

  const employees = useMemo(() => {
    const map = new Map();
    rows.forEach((r) => {
      if (r.employee_id != null) map.set(r.employee_id, r.employee_name);
    });
    return [...map.entries()].map(([id, name]) => ({ id, name }));
  }, [rows]);

  const openDetail = async (row) => {
    if (!row?.id) {
      setError("This employee has not started a list for this date.");
      return;
    }
    setLoading(true);
    try {
      const res = await getMaintenanceTaskListDetail(row.id);
      setDetail(res.data?.list || null);
      setDetailOpen(true);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load detail");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2 }, maxWidth: 1200, mx: "auto", width: "100%", overflowX: "hidden" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5 }}>
        Maintenance Task List
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {dateDisplay || "Review employee maintenance checklists"}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={1.5}
        sx={{ mb: 2, flexWrap: "wrap" }}
      >
        <TextField
          type="date"
          label="Date"
          size="small"
          InputLabelProps={{ shrink: true }}
          value={taskDate}
          onChange={(e) => setTaskDate(e.target.value)}
          sx={{ minWidth: 160 }}
        />
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Employee</InputLabel>
          <Select
            label="Employee"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            {employees.map((e) => (
              <MenuItem key={e.id} value={String(e.id)}>
                {e.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Status</InputLabel>
          <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
            <MenuItem value="in_progress">In Progress</MenuItem>
            <MenuItem value="not_started">Not Started</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Completed</InputLabel>
          <Select
            label="Completed"
            value={completed}
            onChange={(e) => setCompleted(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="complete">Complete</MenuItem>
            <MenuItem value="incomplete">Incomplete</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Task</InputLabel>
          <Select
            label="Task"
            value={definitionId}
            onChange={(e) => setDefinitionId(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            {definitions.map((d) => (
              <MenuItem key={d.id} value={String(d.id)}>
                {d.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button variant="outlined" onClick={load} disabled={loading} sx={{ textTransform: "none" }}>
          Refresh
        </Button>
      </Stack>

      {isMobile ? (
        <Stack spacing={1.25}>
          {rows.map((row) => (
            <Card key={`${row.employee_id}-${row.id || "ns"}`} variant="outlined">
              <CardActionArea onClick={() => openDetail(row)}>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography fontWeight={700}>{row.employee_name}</Typography>
                    <StatusChip status={row.status} />
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    {formatDateShort(row.task_date)} · {row.completed_label}
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    Missing: {row.missing || "—"}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Completed: {formatTimeEt(row.submitted_at)}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          ))}
          {!rows.length && !loading ? (
            <Typography color="text.secondary">No rows for this filter.</Typography>
          ) : null}
        </Stack>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Employee</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Completed</TableCell>
                <TableCell>Missing</TableCell>
                <TableCell>Completed at</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={`${row.employee_id}-${row.id || "ns"}`}
                  hover
                  sx={{ cursor: "pointer" }}
                  onClick={() => openDetail(row)}
                >
                  <TableCell>{formatDateShort(row.task_date)}</TableCell>
                  <TableCell>{row.employee_name}</TableCell>
                  <TableCell>
                    <StatusChip status={row.status} />
                  </TableCell>
                  <TableCell>{row.completed_label}</TableCell>
                  <TableCell>{row.missing || "—"}</TableCell>
                  <TableCell>{formatTimeEt(row.submitted_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} fullWidth maxWidth="sm" fullScreen={isMobile}>
        <DialogTitle>Maintenance Task List</DialogTitle>
        <DialogContent dividers>
          {detail ? (
            <Stack spacing={1.5}>
              <Typography>
                <strong>{detail.employee_name}</strong> · {detail.task_date}
              </Typography>
              <Typography variant="body2">Status: {statusLabel(detail.status)}</Typography>
              {(detail.items || []).map((item) => (
                <Box key={item.id} sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "action.hover" }}>
                  <Typography fontWeight={700}>
                    {item.completed ? "✓" : "○"} {item.task_name_snapshot}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {item.completed
                      ? `Completed ${formatTimeEt(item.completed_at)}`
                      : "Incomplete"}
                  </Typography>
                  {item.note ? (
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      Note: {item.note}
                    </Typography>
                  ) : null}
                </Box>
              ))}
              {(detail.events || []).length ? (
                <Box>
                  <Typography fontWeight={700} sx={{ mb: 0.5 }}>
                    History
                  </Typography>
                  {(detail.events || []).map((ev) => (
                    <Typography key={ev.id} variant="caption" display="block" color="text.secondary">
                      {formatTimeEt(ev.created_at)} · {ev.action}
                      {ev.remarks ? ` — ${ev.remarks}` : ""}
                    </Typography>
                  ))}
                </Box>
              ) : null}
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailOpen(false)} sx={{ textTransform: "none" }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
