import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
} from "@mui/material";
import { getPayrollScheduleWorkers, listFoldingUsers } from "../../api";
import {
  formatRosterRateInput,
  resolveRosterRateForEmployeeName,
} from "../../utils/dailyShiftRosterRate";
import FoldingUserSelect from "../folding/FoldingUserSelect";

const EMPTY_FORM = {
  employee_name: "",
  role: "folder",
  start_time: "08:00",
  end_time: "16:00",
  break_minutes: 30,
  rate: "",
  notes: "",
};

export default function DailyShiftRosterEntryDialog({
  open,
  onClose,
  onSave,
  initialEntry,
  saving,
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [workers, setWorkers] = useState([]);
  const [foldingOptions, setFoldingOptions] = useState([]);
  const [rateManuallySet, setRateManuallySet] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const [workersRes, foldingRes] = await Promise.all([
          getPayrollScheduleWorkers(),
          listFoldingUsers(),
        ]);
        if (cancelled) return;
        setWorkers(workersRes.data?.items || []);
        setFoldingOptions(foldingRes.data?.user_options || []);
      } catch {
        if (!cancelled) {
          setWorkers([]);
          setFoldingOptions([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setRateManuallySet(false);
    if (initialEntry) {
      setForm({
        employee_name: initialEntry.employee_name || "",
        role: initialEntry.role || "folder",
        start_time: initialEntry.start_time || "08:00",
        end_time: initialEntry.end_time || "16:00",
        break_minutes: initialEntry.break_minutes ?? 0,
        rate: initialEntry.rate ?? "",
        notes: initialEntry.notes || "",
      });
    } else {
      setForm(EMPTY_FORM);
    }
  }, [open, initialEntry]);

  useEffect(() => {
    if (!open || initialEntry || !form.employee_name || rateManuallySet) return;
    const suggested = formatRosterRateInput(
      resolveRosterRateForEmployeeName(workers, form.employee_name, foldingOptions),
    );
    if (!suggested) return;
    setForm((prev) => (prev.rate === suggested ? prev : { ...prev, rate: suggested }));
  }, [open, initialEntry, form.employee_name, rateManuallySet, workers, foldingOptions]);

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleEmployeeChange = (name) => {
    setRateManuallySet(false);
    setForm((prev) => {
      const next = { ...prev, employee_name: name };
      if (!initialEntry) {
        next.rate = formatRosterRateInput(
          resolveRosterRateForEmployeeName(workers, name, foldingOptions),
        );
      }
      return next;
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave?.({
      ...form,
      break_minutes: Number(form.break_minutes) || 0,
      rate: Number(form.rate) || 0,
    });
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <form onSubmit={handleSubmit}>
        <DialogTitle sx={{ fontWeight: 800 }}>
          {initialEntry ? "Edit Roster Entry" : "Add Roster Entry"}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <FoldingUserSelect
              label="Employee"
              value={form.employee_name}
              onChange={handleEmployeeChange}
              allowEmpty={false}
              sx={{ width: "100%" }}
            />
            <TextField
              select
              label="Role"
              value={form.role}
              onChange={(e) => setField("role", e.target.value)}
              fullWidth
              size="small"
            >
              <MenuItem value="folder">Folder</MenuItem>
              <MenuItem value="operator">Operator</MenuItem>
            </TextField>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              <TextField
                label="Start Time"
                type="time"
                value={form.start_time}
                onChange={(e) => setField("start_time", e.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
                size="small"
              />
              <TextField
                label="End Time"
                type="time"
                value={form.end_time}
                onChange={(e) => setField("end_time", e.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
                size="small"
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
              <TextField
                label="Break Minutes"
                type="number"
                inputProps={{ min: 0, step: 1 }}
                value={form.break_minutes}
                onChange={(e) => setField("break_minutes", e.target.value)}
                fullWidth
                size="small"
              />
              <TextField
                label="Rate ($/hr)"
                type="number"
                inputProps={{ min: 0, step: 0.01 }}
                value={form.rate}
                onChange={(e) => {
                  setRateManuallySet(true);
                  setField("rate", e.target.value);
                }}
                fullWidth
                size="small"
              />
            </Stack>
            <TextField
              label="Notes"
              value={form.notes}
              onChange={(e) => setField("notes", e.target.value)}
              fullWidth
              size="small"
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={saving || !form.employee_name}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
