import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  createMaintenanceTaskDefinition,
  getEmployees,
  getMaintenanceTaskDefinitions,
  getMaintenanceWeekdayAssignments,
  putMaintenanceWeekdayAssignments,
  reorderMaintenanceTaskDefinitions,
  setMaintenanceTaskDefinitionActive,
  updateMaintenanceTaskDefinition,
} from "../api";
import { copyWeekdayAssigneeToAll, reorderIds } from "../utils/maintenanceTaskListHelpers";

const emptyForm = {
  id: null,
  name: "",
  description: "",
  category: "Closing",
  frequency: "daily",
  days_of_week: [],
  is_required: true,
  require_note_if_incomplete: false,
  is_active: true,
  display_order: 0,
};

const SUGGESTED = ["Opening", "During Shift", "Closing", "Cleaning", "Safety", "Equipment"];

export default function MaintenanceTaskSettingsPage() {
  const [definitions, setDefinitions] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [defs, week, people] = await Promise.all([
        getMaintenanceTaskDefinitions({ include_inactive: 1 }),
        getMaintenanceWeekdayAssignments().catch(() => ({ data: { assignments: [] } })),
        getEmployees().catch(() => ({ data: [] })),
      ]);
      setDefinitions(defs.data?.definitions || []);
      setAssignments(week.data?.assignments || []);
      const raw = people.data?.employees || people.data || [];
      setEmployees(Array.isArray(raw) ? raw : []);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load task settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setForm({ ...emptyForm, display_order: (definitions.length + 1) * 10 });
    setOpen(true);
  };

  const openEdit = (row) => {
    setForm({
      id: row.id,
      name: row.name || "",
      description: row.description || "",
      category: row.category || "",
      frequency: row.frequency || "daily",
      days_of_week: row.days_of_week || [],
      is_required: !!row.is_required,
      require_note_if_incomplete: !!row.require_note_if_incomplete,
      is_active: !!row.is_active,
      display_order: row.display_order || 0,
    });
    setOpen(true);
  };

  const save = async () => {
    setError("");
    try {
      if (form.id) {
        await updateMaintenanceTaskDefinition(form);
      } else {
        await createMaintenanceTaskDefinition(form);
      }
      setOpen(false);
      setMessage("Task saved.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save task");
    }
  };

  const saveAssignments = async () => {
    setError("");
    try {
      const res = await putMaintenanceWeekdayAssignments(
        assignments.map((a) => ({
          weekday: a.weekday,
          employee_id: a.employee_id || null,
        })),
      );
      setAssignments(res.data?.assignments || assignments);
      setMessage("Weekday assignments saved.");
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save assignments");
    }
  };

  const setAssignmentEmployee = (weekday, employeeId) => {
    setAssignments((prev) => {
      const base =
        prev.length > 0
          ? prev
          : [6, 0, 1, 2, 3, 4, 5].map((w, i) => ({
              weekday: w,
              label: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][i],
              employee_id: null,
            }));
      return base.map((row) =>
        Number(row.weekday) === Number(weekday)
          ? { ...row, employee_id: employeeId === "" ? null : Number(employeeId) }
          : row,
      );
    });
  };

  const copyMondayToAllDays = () => {
    setAssignments((prev) => {
      const base =
        prev.length > 0
          ? prev
          : [6, 0, 1, 2, 3, 4, 5].map((w, i) => ({
              weekday: w,
              label: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][i],
              employee_id: null,
            }));
      return copyWeekdayAssigneeToAll(base, 0);
    });
  };

  const assignmentRows =
    assignments.length > 0
      ? assignments
      : [
          { weekday: 6, label: "Sunday", employee_id: null },
          { weekday: 0, label: "Monday", employee_id: null },
          { weekday: 1, label: "Tuesday", employee_id: null },
          { weekday: 2, label: "Wednesday", employee_id: null },
          { weekday: 3, label: "Thursday", employee_id: null },
          { weekday: 4, label: "Friday", employee_id: null },
          { weekday: 5, label: "Saturday", employee_id: null },
        ];
  const unassignedDays = assignmentRows.filter((r) => r.employee_id == null);

  const toggleActive = async (row) => {
    try {
      await setMaintenanceTaskDefinitionActive(row.id, !row.is_active);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update active state");
    }
  };

  const move = async (index, direction) => {
    const ids = definitions.map((d) => d.id);
    const next = reorderIds(ids, index, index + direction);
    if (next.join(",") === ids.join(",")) return;
    try {
      const res = await reorderMaintenanceTaskDefinitions(next);
      setDefinitions(res.data?.definitions || []);
      setMessage("Order updated.");
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to reorder");
    }
  };

  const employeeLabel = (emp) =>
    emp.display_name ||
    emp.name ||
    [emp.first_name, emp.last_name].filter(Boolean).join(" ") ||
    emp.username ||
    `Employee ${emp.id}`;

  return (
    <Box sx={{ p: { xs: 1.5, md: 2 }, maxWidth: 900, mx: "auto", width: "100%", overflowX: "hidden" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" fontWeight={800}>
            Maintenance Tasks
          </Typography>
          <Typography color="text.secondary">
            Daily checklist template and weekday assignee
          </Typography>
        </Box>
        <Button variant="contained" onClick={openCreate} sx={{ textTransform: "none" }}>
          Add task
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {message ? (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}

      <Box sx={{ mb: 3, p: 2, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <Typography fontWeight={800} sx={{ mb: 0.5 }}>
          Weekday assignment
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          One employee per day. Empty days have no floor checklist. Assignments are always
          authoritative on the PIN End-of-Day Checklist tile.
        </Typography>
        {unassignedDays.length ? (
          <Alert severity="warning" sx={{ mb: 1.5 }}>
            {unassignedDays.length === 1
              ? `No employee assigned for ${unassignedDays[0].label}.`
              : `No employee assigned for: ${unassignedDays.map((d) => d.label).join(", ")}.`}
          </Alert>
        ) : null}
        <Stack spacing={1.25}>
          {assignmentRows.map((row) => (
            <Stack
              key={row.weekday}
              direction={{ xs: "column", sm: "row" }}
              spacing={1}
              alignItems={{ sm: "center" }}
            >
              <Typography sx={{ minWidth: 110, fontWeight: 700 }}>{row.label}</Typography>
              <FormControl size="small" fullWidth>
                <InputLabel>Employee</InputLabel>
                <Select
                  label="Employee"
                  value={row.employee_id == null ? "" : String(row.employee_id)}
                  onChange={(e) => setAssignmentEmployee(row.weekday, e.target.value)}
                >
                  <MenuItem value="">None</MenuItem>
                  {employees.map((emp) => (
                    <MenuItem key={emp.id} value={String(emp.id)}>
                      {employeeLabel(emp)}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {!row.employee_id ? (
                <Typography variant="caption" color="warning.main" sx={{ minWidth: 160 }}>
                  No employee assigned for {row.label}.
                </Typography>
              ) : null}
            </Stack>
          ))}
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1.5 }}>
          <Button variant="outlined" onClick={copyMondayToAllDays} sx={{ textTransform: "none" }}>
            Copy Monday to All Days
          </Button>
          <Button
            variant="contained"
            onClick={saveAssignments}
            disabled={loading}
            sx={{ textTransform: "none" }}
          >
            Save weekday assignments
          </Button>
        </Stack>
      </Box>

      <Typography fontWeight={800} sx={{ mb: 1 }}>
        Checklist template
      </Typography>
      <Stack spacing={1.25}>
        {definitions.map((row, index) => (
          <Box
            key={row.id}
            sx={{
              p: 1.5,
              borderRadius: 2,
              border: "1px solid",
              borderColor: "divider",
              bgcolor: row.is_active ? "background.paper" : "action.hover",
              opacity: row.is_active ? 1 : 0.75,
            }}
          >
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between">
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="caption" color="text.secondary" fontWeight={700}>
                  {row.category || "General"}
                </Typography>
                <Typography fontWeight={700}>{row.name}</Typography>
                {row.description ? (
                  <Typography variant="body2" sx={{ mt: 0.5 }} color="text.secondary">
                    {row.description}
                  </Typography>
                ) : null}
              </Box>
              <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                <Button size="small" disabled={index === 0 || loading} onClick={() => move(index, -1)}>
                  Up
                </Button>
                <Button
                  size="small"
                  disabled={index === definitions.length - 1 || loading}
                  onClick={() => move(index, 1)}
                >
                  Down
                </Button>
                <Button size="small" onClick={() => openEdit(row)} sx={{ textTransform: "none" }}>
                  Edit
                </Button>
                <Button
                  size="small"
                  color={row.is_active ? "warning" : "success"}
                  onClick={() => toggleActive(row)}
                  sx={{ textTransform: "none" }}
                >
                  {row.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              </Stack>
            </Stack>
          </Box>
        ))}
        {!definitions.length && !loading ? (
          <Typography color="text.secondary">No tasks configured yet.</Typography>
        ) : null}
      </Stack>

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{form.id ? "Edit task" : "Add task"}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <TextField
              label="Category"
              fullWidth
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              helperText={`Examples: ${SUGGESTED.join(", ")}`}
            />
            <TextField
              label="Heading"
              fullWidth
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <TextField
              label="Description"
              fullWidth
              multiline
              minRows={2}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={!!form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button variant="contained" onClick={save} sx={{ textTransform: "none" }}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
