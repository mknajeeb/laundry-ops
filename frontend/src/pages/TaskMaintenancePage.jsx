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
  IconButton,
  Paper,
  Stack,
  Switch,
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
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import {
  deleteTaskTrackingTask,
  getTaskTrackingTasks,
  patchTaskTrackingTask,
  postTaskTrackingTask,
  postTaskTrackingTasksReorder,
} from "../api";

const emptyForm = { name: "", active: true, reason: "" };

export default function TaskMaintenancePage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [editId, setEditId] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getTaskTrackingTasks({ include_inactive: "1", include_usage: "1" });
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditId(null);
    setForm(emptyForm);
    setDialogOpen(true);
  };

  const openEdit = (row) => {
    setEditId(row.id);
    setForm({ name: row.name || "", active: !!row.active, reason: "" });
    setDialogOpen(true);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const body = { name: form.name.trim(), active: form.active, reason: form.reason || undefined };
      if (editId) {
        await patchTaskTrackingTask(editId, body);
      } else {
        await postTaskTrackingTask(body);
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setError("");
    try {
      await deleteTaskTrackingTask(deleteTarget.id);
      setDeleteTarget(null);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const move = async (index, direction) => {
    const next = [...rows];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setRows(next);
    try {
      await postTaskTrackingTasksReorder({ ordered_ids: next.map((r) => r.id) });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Reorder failed");
      await load();
    }
  };

  return (
    <Box sx={{ maxWidth: 960, mx: "auto" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" fontWeight={800}>
            Task Maintenance
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Active tasks appear on the clock screen. Inactive tasks stay in shift history but cannot be selected.
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          Add task
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper variant="outlined" sx={{ borderRadius: 2 }}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={72}>Order</TableCell>
                <TableCell>Task</TableCell>
                <TableCell width={100}>Status</TableCell>
                <TableCell width={140} align="right">
                  Actions
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Typography color="text.secondary">Loading…</Typography>
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Typography color="text.secondary">No tasks yet.</Typography>
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row, idx) => (
                  <TableRow key={row.id} hover>
                    <TableCell>
                      <Stack direction="row" spacing={0.25}>
                        <IconButton size="small" disabled={idx === 0} onClick={() => move(idx, -1)}>
                          <ArrowUpwardIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          disabled={idx === rows.length - 1}
                          onClick={() => move(idx, 1)}
                        >
                          <ArrowDownwardIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    </TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{row.name}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={row.active ? "Active" : "Inactive"}
                        color={row.active ? "success" : "default"}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <IconButton size="small" onClick={() => openEdit(row)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <Tooltip
                        title={
                          row.can_delete === false || (row.usage_count || 0) > 0
                            ? "This task has been used on a shift and cannot be deleted. Deactivate it instead."
                            : "Delete task (only if never used)"
                        }
                      >
                        <span>
                          <IconButton
                            size="small"
                            color="error"
                            disabled={row.can_delete === false || (row.usage_count || 0) > 0}
                            onClick={() => setDeleteTarget(row)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Dialog open={dialogOpen} onClose={() => !busy && setDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{editId ? "Edit task" : "Add task"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="Task name"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              fullWidth
              autoFocus
            />
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Box>
                <Typography variant="body2">Active</Typography>
                <Typography variant="caption" color="text.secondary">
                  Inactive tasks remain visible in Shift Task History.
                </Typography>
              </Box>
              <Switch
                checked={form.active}
                onChange={(e) => setForm((p) => ({ ...p, active: e.target.checked }))}
              />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="contained" onClick={save} disabled={busy || !form.name.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleteTarget} onClose={() => !busy && setDeleteTarget(null)}>
        <DialogTitle>Delete task?</DialogTitle>
        <DialogContent>
          {deleteTarget?.can_delete === false || (deleteTarget?.usage_count || 0) > 0 ? (
            <Alert severity="warning" sx={{ mt: 0.5 }}>
              &ldquo;{deleteTarget?.name}&rdquo; has been used on past shifts and cannot be deleted.
              Deactivate the task to hide it from future check-ins.
            </Alert>
          ) : (
            <Typography variant="body2">
              Delete &ldquo;{deleteTarget?.name}&rdquo;? This is only allowed when the task has never been used.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)} disabled={busy}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={confirmDelete}
            disabled={
              busy || deleteTarget?.can_delete === false || (deleteTarget?.usage_count || 0) > 0
            }
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
