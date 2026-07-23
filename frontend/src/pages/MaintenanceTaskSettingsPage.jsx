import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
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
  getMaintenanceTaskDefinitions,
  reorderMaintenanceTaskDefinitions,
  setMaintenanceTaskDefinitionActive,
  updateMaintenanceTaskDefinition,
} from "../api";
import { MTL_FREQUENCIES, MTL_WEEKDAYS, reorderIds } from "../utils/maintenanceTaskListHelpers";

const emptyForm = {
  id: null,
  name: "",
  description: "",
  frequency: "daily",
  days_of_week: [],
  is_required: true,
  require_note_if_incomplete: true,
  is_active: true,
  display_order: 0,
};

export default function MaintenanceTaskSettingsPage() {
  const [definitions, setDefinitions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getMaintenanceTaskDefinitions({ include_inactive: 1 });
      setDefinitions(res.data?.definitions || []);
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

  return (
    <Box sx={{ p: { xs: 1.5, md: 2 }, maxWidth: 900, mx: "auto", width: "100%", overflowX: "hidden" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h5" fontWeight={800}>
            Maintenance Task Settings
          </Typography>
          <Typography color="text.secondary">
            Configure daily, weekly, and as-needed maintenance tasks
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
                <Typography fontWeight={700}>{row.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {MTL_FREQUENCIES.find((f) => f.value === row.frequency)?.label || row.frequency}
                  {row.is_required ? " · Required" : " · Optional"}
                  {!row.is_active ? " · Inactive" : ""}
                </Typography>
                {row.description ? (
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
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
              label="Name"
              fullWidth
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <TextField
              label="Instructions / description"
              fullWidth
              multiline
              minRows={2}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
            <FormControl fullWidth>
              <InputLabel>Frequency</InputLabel>
              <Select
                label="Frequency"
                value={form.frequency}
                onChange={(e) => setForm((f) => ({ ...f, frequency: e.target.value }))}
              >
                {MTL_FREQUENCIES.map((f) => (
                  <MenuItem key={f.value} value={f.value}>
                    {f.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {form.frequency === "weekly" ? (
              <Box>
                <Typography variant="body2" sx={{ mb: 0.5 }}>
                  Days of week
                </Typography>
                <Stack direction="row" flexWrap="wrap" useFlexGap spacing={0.5}>
                  {MTL_WEEKDAYS.map((d) => (
                    <FormControlLabel
                      key={d.value}
                      control={
                        <Checkbox
                          checked={(form.days_of_week || []).includes(d.value)}
                          onChange={(e) => {
                            const set = new Set(form.days_of_week || []);
                            if (e.target.checked) set.add(d.value);
                            else set.delete(d.value);
                            setForm((f) => ({ ...f, days_of_week: [...set].sort((a, b) => a - b) }));
                          }}
                        />
                      }
                      label={d.label}
                    />
                  ))}
                </Stack>
              </Box>
            ) : null}
            <FormControlLabel
              control={
                <Switch
                  checked={!!form.is_required}
                  onChange={(e) => setForm((f) => ({ ...f, is_required: e.target.checked }))}
                />
              }
              label="Required"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={!!form.require_note_if_incomplete}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, require_note_if_incomplete: e.target.checked }))
                  }
                />
              }
              label="Require a note when left incomplete"
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
