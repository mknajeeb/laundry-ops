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
import { DAY_LABELS, DISPLAY_DAY_ORDER, formatDayDate } from "./weeklyScheduleDates";
import { scheduleRoleCatalog, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { routineAssignmentOptions } from "../tasks/routineAssignmentOptions";
import { TASK_TIMING, TASK_TIMING_OPTIONS } from "./weeklyScheduleTaskTiming";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import { useI18n } from "../../i18n/I18nContext";

const NO_DAYS = [];

function taskOptions() {
  return routineAssignmentOptions(scheduleRoleCatalog()).map((option) => ({
    ...option,
    label: option.group ? option.label : option.label || scheduleRoleLabel(option.value),
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
  const { t } = useI18n();
  const options = useMemo(() => taskOptions(), [open]);
  const [days, setDays] = useState([]);
  const [task, setTask] = useState(null);
  const [people, setPeople] = useState([]);
  const [timingMode, setTimingMode] = useState(TASK_TIMING.ANYTIME);
  const [taskStart, setTaskStart] = useState("");
  const [remarks, setRemarks] = useState("");

  useEffect(() => {
    if (!open) return;
    setDays(defaultDays.length ? defaultDays.map(Number) : []);
    setTask(null);
    setPeople([]);
    setTimingMode(TASK_TIMING.ANYTIME);
    setTaskStart("");
    setRemarks("");
    // Reset only when the dialog opens. defaultDays is read at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const isGroup = Boolean(task?.group);
  const names = people.map((person) => person.display_name || `User #${person.user_id}`);
  const canSave = days.length > 0 && task && people.length > 0 && (timingMode !== TASK_TIMING.SPECIFIC || taskStart);

  const toggleDay = (dow) => {
    setDays((current) => (current.includes(dow) ? current.filter((day) => day !== dow) : [...current, dow].sort()));
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("weeklySchedule.assignTasks")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t("weeklySchedule.assignHelp")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.5}>
            {DISPLAY_DAY_ORDER.map((dow) => {
              const label = DAY_LABELS[dow];
              return (
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
              );
            })}
          </Stack>
          <Autocomplete
            options={options}
            value={task}
            onChange={(_, value) => setTask(value)}
            getOptionLabel={(option) => option.label || ""}
            isOptionEqualToValue={(option, value) => option.value === value.value}
            renderInput={(params) => <TextField {...params} label={t("weeklySchedule.taskOrGroup")} size="small" />}
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
            renderInput={(params) => <TextField {...params} label={t("weeklySchedule.employees")} size="small" />}
          />
          {names.length ? (
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {t("weeklySchedule.assigned", { names: names.join(", ") })}
            </Typography>
          ) : null}
          <FormControl size="small" fullWidth>
            <InputLabel>{t("weeklySchedule.timing")}</InputLabel>
            <Select label={t("weeklySchedule.timing")} value={timingMode} onChange={(e) => setTimingMode(e.target.value)}>
              {TASK_TIMING_OPTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {t(`weeklySchedule.timing.${option.value}`)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {timingMode === TASK_TIMING.SPECIFIC ? (
            <PlanningTimePicker label={t("weeklySchedule.startTime")} value={taskStart} onChange={setTaskStart} />
          ) : null}
          {isGroup && people.length >= 2 ? (
            <Typography variant="caption" color="text.secondary">
              {t("weeklySchedule.sharedActivity")}
            </Typography>
          ) : isGroup ? (
            <Typography variant="caption" color="text.secondary">
              {t("weeklySchedule.selectTwo")}
            </Typography>
          ) : null}
          <TextField
            size="small"
            fullWidth
            multiline
            minRows={2}
            label={t("weeklySchedule.instructions")}
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            inputProps={{ maxLength: 255 }}
          />
          <Typography variant="caption" color="text.secondary">
            {days.length
              ? `${days.length === 1 ? t("weeklySchedule.assignmentCountOne") : t("weeklySchedule.assignmentCountMany", { count: days.length })} `
              : `${t("weeklySchedule.selectDate")} `}
            {isGroup && people.length >= 2
              ? `${t("weeklySchedule.sharedExecution")} `
              : `${t("weeklySchedule.eachEmployee")} `}
            {t("weeklySchedule.noHours")}
          </Typography>
          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("weeklySchedule.cancel")}</Button>
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
              execution_mode: isGroup && people.length >= 2 ? "shared" : "individual",
            })
          }
        >
          {saving ? t("weeklySchedule.assigning") : t("weeklySchedule.assign")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
