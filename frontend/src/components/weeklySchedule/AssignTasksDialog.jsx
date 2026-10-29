import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { DAY_LABELS, formatDayDate } from "./weeklyScheduleDates";
import { scheduleRoleCatalog, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { TASK_TIMING, TASK_TIMING_OPTIONS } from "./weeklyScheduleTaskTiming";
import PlanningTimePicker from "../datetime/PlanningTimePicker";

const NO_DAYS = [];

function taskOptions() {
  return scheduleRoleCatalog()
    .filter((role) => role.uses_time_slots === false && role.active !== false)
    .map((role) => ({
      value: role.code,
      label: String(role.code || "").startsWith("agroup_")
        ? `Group: ${role.name || scheduleRoleLabel(role.code)}`
        : role.name || scheduleRoleLabel(role.code),
      group: String(role.code || "").startsWith("agroup_"),
    }));
}

/**
 * Assign one task or activity group to the selected employees on one or more days.
 * Each day is its own pairing. Shared execution uses one assignment group for that day.
 */
export default function AssignTasksDialog({
  open,
  onClose,
  onAssign,
  saving = false,
  error = "",
  weekStart,
  employees = [],
  defaultDays = NO_DAYS,
}) {
  const options = useMemo(() => taskOptions(), [open]);
  const [days, setDays] = useState([]);
  const [task, setTask] = useState(null);
  const [people, setPeople] = useState([]);
  const [timingMode, setTimingMode] = useState(TASK_TIMING.ANYTIME);
  const [taskStart, setTaskStart] = useState("");
  const [remarks, setRemarks] = useState("");
  const [executionMode, setExecutionMode] = useState("individual");

  useEffect(() => {
    if (!open) return;
    setDays(defaultDays.length ? defaultDays.map(Number) : []);
    setTask(null);
    setPeople([]);
    setTimingMode(TASK_TIMING.ANYTIME);
    setTaskStart("");
    setRemarks("");
    setExecutionMode("individual");
    // Reset only when the dialog opens. defaultDays is read at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const isGroup = Boolean(task?.group);
  const canShare = isGroup && people.length >= 2;
  const names = people.map((person) => person.display_name || `User #${person.user_id}`);
  const canSave = days.length > 0 && task && people.length > 0 && (timingMode !== TASK_TIMING.SPECIFIC || taskStart);

  const toggleDay = (dow) => {
    setDays((current) => (current.includes(dow) ? current.filter((day) => day !== dow) : [...current, dow].sort()));
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Assign Tasks</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Choose the dates, the task or activity group, and the employees. Pairings are saved on those dates only.
            The activity group definition stays the same.
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.5}>
            {DAY_LABELS.map((label, dow) => (
              <Button
                key={label}
                size="small"
                variant={days.includes(dow) ? "contained" : "outlined"}
                onClick={() => toggleDay(dow)}
                aria-pressed={days.includes(dow)}
                sx={{ fontWeight: 700, minWidth: 76, flexDirection: "column", lineHeight: 1.05, py: 0.5 }}
              >
                {label}
                <Typography component="span" sx={{ display: "block", fontSize: "0.65rem", fontWeight: 600 }}>
                  {weekStart ? formatDayDate(weekStart, dow).replace(/, \d{4}$/, "") : ""}
                </Typography>
              </Button>
            ))}
          </Stack>
          <Autocomplete
            options={options}
            value={task}
            onChange={(_, value) => setTask(value)}
            getOptionLabel={(option) => option.label || ""}
            isOptionEqualToValue={(option, value) => option.value === value.value}
            renderInput={(params) => <TextField {...params} label="Task or activity group" size="small" />}
          />
          <Autocomplete
            multiple
            options={employees}
            value={people}
            onChange={(_, value) => setPeople(value)}
            getOptionLabel={(option) => option.display_name || `User #${option.user_id}`}
            isOptionEqualToValue={(option, value) => Number(option.user_id) === Number(value.user_id)}
            renderOption={(props, option, { selected }) => (
              <li {...props}>
                <Checkbox size="small" checked={selected} sx={{ mr: 1 }} />
                {option.display_name || `User #${option.user_id}`}
              </li>
            )}
            renderInput={(params) => <TextField {...params} label="Employees" size="small" />}
          />
          {names.length ? (
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {`Assigned: ${names.join(", ")}`}
            </Typography>
          ) : null}
          <FormControl size="small" fullWidth>
            <InputLabel>Timing</InputLabel>
            <Select label="Timing" value={timingMode} onChange={(e) => setTimingMode(e.target.value)}>
              {TASK_TIMING_OPTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {timingMode === TASK_TIMING.SPECIFIC ? (
            <PlanningTimePicker label="Start time" value={taskStart} onChange={setTaskStart} />
          ) : null}
          {canShare ? (
            <FormControl size="small" fullWidth>
              <InputLabel>Execution mode</InputLabel>
              <Select label="Execution mode" value={executionMode} onChange={(e) => setExecutionMode(e.target.value)}>
                <MenuItem value="individual">Individual — separate checklists</MenuItem>
                <MenuItem value="shared">Shared — one checklist, separate timers</MenuItem>
              </Select>
            </FormControl>
          ) : isGroup ? (
            <Typography variant="caption" color="text.secondary">
              Select two or more employees to choose Shared or Individual execution.
            </Typography>
          ) : null}
          <TextField
            size="small"
            fullWidth
            multiline
            minRows={2}
            label="Instructions"
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            inputProps={{ maxLength: 255 }}
          />
          <Typography variant="caption" color="text.secondary">
            {days.length
              ? `This creates ${days.length} assignment${days.length === 1 ? "" : "s"}, one per selected date. `
              : "Select at least one date. "}
            {canShare && executionMode === "shared"
              ? "Shared execution is one assignment for the group that day, not a copy for each person. "
              : "Each selected employee receives the task. "}
            Task assignments do not add scheduled hours.
          </Typography>
          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!canSave || saving}
          onClick={() =>
            onAssign({
              days_of_week: days,
              role: task.value,
              user_ids: people.map((person) => Number(person.user_id)),
              timing_mode: timingMode,
              start_time: timingMode === TASK_TIMING.SPECIFIC ? taskStart : null,
              remarks: remarks.trim() || null,
              execution_mode: canShare && executionMode === "shared" ? "shared" : "individual",
            })
          }
        >
          {saving ? "Assigning…" : "Assign"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
