import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
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
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { DAY_LABELS, DISPLAY_DAY_ORDER, formatDayDate } from "./weeklyScheduleDates";
import { formatBreakSlot, makeBreakSlot, scheduleRoleCatalog, scheduleRoleLabel, validateBreakSlots } from "./weeklyScheduleRoles";
import { routineAssignmentOptions } from "../tasks/routineAssignmentOptions";
import { TASK_TIMING, TASK_TIMING_OPTIONS } from "./weeklyScheduleTaskTiming";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { useI18n } from "../../i18n/I18nContext";
import {
  breakSummary,
  breakTargets,
  slotMinutes,
  suggestedBreakSlot,
  taskAssignmentConflicts,
  taskAssignmentPayload,
  unscheduledAssignmentPairs,
} from "./weeklyScheduleBreakAssignment";

const NO_DAYS = [];

function taskOptions() {
  return routineAssignmentOptions(scheduleRoleCatalog()).map((option) => ({
    ...option,
    label: option.group ? option.label : option.label || scheduleRoleLabel(option.value),
  }));
}

function dayButtonLabel(weekStart, dow) {
  return weekStart ? formatDayDate(weekStart, dow).replace(/, \d{4}$/, "") : "";
}

function BreakDraftEditor({ entry, draft, error, saving, onChange, onCancel, onSave }) {
  const summary = breakSummary({ break_slots: draft.slots, unscheduled_break_minutes: draft.unscheduled });
  return (
    <Stack spacing={1} sx={{ mt: 0.75 }}>
      {draft.slots.map((slot) => (
        <Stack key={slot.id} direction="row" spacing={1} alignItems="center">
          <PlanningTimePicker
            label="Start"
            value={slot.start_time}
            onChange={(value) =>
              onChange({
                ...draft,
                slots: draft.slots.map((item) => (item.id === slot.id ? { ...item, start_time: value } : item)),
              })
            }
          />
          <PlanningTimePicker
            label="End"
            value={slot.end_time}
            onChange={(value) =>
              onChange({
                ...draft,
                slots: draft.slots.map((item) => (item.id === slot.id ? { ...item, end_time: value } : item)),
              })
            }
          />
          <Typography variant="caption" sx={{ fontWeight: 700, width: 52 }}>
            {slotMinutes(slot) ? `${slotMinutes(slot)} min` : ""}
          </Typography>
        </Stack>
      ))}
      <TextField
        label="Break without a time (min)"
        type="number"
        size="small"
        inputProps={{ min: 0, step: 5 }}
        value={draft.unscheduled}
        onChange={(event) => onChange({ ...draft, unscheduled: Math.max(0, Number(event.target.value) || 0) })}
        sx={{ maxWidth: 220 }}
      />
      <Typography variant="caption" color="text.secondary">
        {`Duration ${summary.totalMinutes} min. Planned breaks change scheduled hours only.`}
      </Typography>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Stack direction="row" spacing={1}>
        <Button size="small" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button size="small" variant="contained" disabled={saving} onClick={() => onSave(entry, draft)}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </Stack>
    </Stack>
  );
}

export function BreakAssignmentPanel({ people, days, entries, weekStart, saving, onSaveBreak }) {
  const targets = useMemo(() => breakTargets({ people, days, entries }), [people, days, entries]);
  const [draft, setDraft] = useState(null);
  const [draftError, setDraftError] = useState("");
  const [pendingRemoveId, setPendingRemoveId] = useState(null);
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    setDraft(null);
    setDraftError("");
    setPendingRemoveId(null);
  }, [people, days]);

  if (!people.length || !days.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        Select at least one date and one employee to see breaks.
      </Typography>
    );
  }

  const commit = async (entry, patch) => {
    setSavingId(entry.id);
    setDraftError("");
    const ok = await onSaveBreak(entry, patch);
    setSavingId(null);
    if (ok) {
      setDraft(null);
      setPendingRemoveId(null);
    }
  };

  const saveDraft = (entry, next) => {
    const validation = validateBreakSlots(entry.start_time, entry.end_time, next.slots);
    if (validation) {
      setDraftError(validation);
      return;
    }
    commit(entry, {
      break_slots: next.slots.map((slot) => ({ start_time: slot.start_time, end_time: slot.end_time })),
      unscheduled_break_minutes: Math.max(0, Math.round(Number(next.unscheduled || 0))),
    });
  };

  return (
    <Stack spacing={1}>
      <Typography variant="caption" color="text.secondary">
        Each employee and date is listed on its own. A change applies only to the shift you edit.
      </Typography>
      {targets.map((target) => (
        <Box key={target.key} data-break-target={target.key} sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1 }}>
          <Typography sx={{ fontWeight: 800, fontSize: "0.85rem" }}>
            {`${target.name} · ${DAY_LABELS[target.day]}`}
            {weekStart ? ` ${dayButtonLabel(weekStart, target.day)}` : ""}
          </Typography>
          {target.shifts.length ? (
            target.shifts.map((entry) => {
              const summary = breakSummary(entry);
              const editing = draft?.entryId === entry.id;
              const shiftLabel = `${formatTime12(entry.start_time)}–${formatTime12(entry.end_time)}`;
              return (
                <Box key={entry.id} data-break-shift={entry.id} sx={{ mt: 0.75 }}>
                  <Typography variant="caption" sx={{ fontWeight: 700 }}>
                    {`Shift ${shiftLabel}`}
                  </Typography>
                  {editing ? (
                    <BreakDraftEditor
                      entry={entry}
                      draft={draft}
                      error={draftError}
                      saving={saving || savingId === entry.id}
                      onChange={setDraft}
                      onCancel={() => {
                        setDraft(null);
                        setDraftError("");
                      }}
                      onSave={saveDraft}
                    />
                  ) : summary.hasBreak ? (
                    <Stack spacing={0.25} sx={{ mt: 0.25 }}>
                      {summary.slots.map((slot, index) => (
                        <Typography key={`${slot.start_time}-${index}`} sx={{ fontSize: "0.8rem", fontWeight: 700 }}>
                          {`${formatBreakSlot(slot)} · ${slotMinutes(slot)} min`}
                        </Typography>
                      ))}
                      {summary.unscheduled ? (
                        <Typography sx={{ fontSize: "0.8rem" }}>{`Not scheduled · ${summary.unscheduled} min`}</Typography>
                      ) : null}
                      <Stack direction="row" spacing={1}>
                        <Button
                          size="small"
                          disabled={saving}
                          onClick={() => {
                            setPendingRemoveId(null);
                            setDraftError("");
                            setDraft({
                              entryId: entry.id,
                              slots: summary.slots.map((slot) =>
                                makeBreakSlot({ start_time: slot.start_time, end_time: slot.end_time }),
                              ),
                              unscheduled: summary.unscheduled,
                            });
                          }}
                        >
                          Edit
                        </Button>
                        {pendingRemoveId === entry.id ? (
                          <>
                            <Button
                              size="small"
                              color="error"
                              disabled={saving || savingId === entry.id}
                              onClick={() => commit(entry, { break_slots: [], unscheduled_break_minutes: 0 })}
                            >
                              {savingId === entry.id ? "Removing…" : "Remove"}
                            </Button>
                            <Button size="small" onClick={() => setPendingRemoveId(null)}>
                              Cancel
                            </Button>
                          </>
                        ) : (
                          <Button size="small" color="error" disabled={saving} onClick={() => setPendingRemoveId(entry.id)}>
                            Remove
                          </Button>
                        )}
                      </Stack>
                    </Stack>
                  ) : (
                    <Button
                      size="small"
                      disabled={saving}
                      onClick={() => {
                        setPendingRemoveId(null);
                        setDraftError("");
                        setDraft({ entryId: entry.id, slots: [suggestedBreakSlot(entry)], unscheduled: 0 });
                      }}
                      sx={{ mt: 0.25 }}
                    >
                      Add Break
                    </Button>
                  )}
                </Box>
              );
            })
          ) : (
            <Alert severity="warning" data-break-needs-shift sx={{ mt: 0.75 }}>
              A scheduled break needs a shift. This employee is not scheduled on this date.
            </Alert>
          )}
        </Box>
      ))}
    </Stack>
  );
}

/**
 * Assign tasks or edit planned breaks for the selected employees and dates.
 * Tasks keep the existing assignment payload. Breaks update the shift that already exists.
 */
export default function AssignTasksDialog({
  open,
  onClose,
  onAssign,
  onSaveBreak,
  saving = false,
  error = "",
  weekStart,
  employees = [],
  entries = [],
  responsibilities = [],
  defaultDays = NO_DAYS,
  defaultUserIds = [],
  defaultRole = "",
  defaultTiming = "",
  defaultStart = "",
}) {
  const { t } = useI18n();
  const options = useMemo(() => taskOptions(), [open]);
  const [section, setSection] = useState("tasks");
  const [days, setDays] = useState([]);
  const [task, setTask] = useState(null);
  const [people, setPeople] = useState([]);
  const [timingMode, setTimingMode] = useState(TASK_TIMING.ANYTIME);
  const [taskStart, setTaskStart] = useState("");
  const [remarks, setRemarks] = useState("");
  const [confirmUnscheduled, setConfirmUnscheduled] = useState(false);
  const [hideServerWarning, setHideServerWarning] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSection("tasks");
    setDays(defaultDays.length ? defaultDays.map(Number) : []);
    const seededIds = new Set((defaultUserIds || []).map(Number));
    setPeople(employees.filter((person) => seededIds.has(Number(person.user_id))));
    setTask(taskOptions().find((option) => option.value === defaultRole) || null);
    setTimingMode(defaultTiming || TASK_TIMING.ANYTIME);
    setTaskStart(defaultStart || "");
    setRemarks("");
    setConfirmUnscheduled(false);
    setHideServerWarning(false);
    // Reset only when the dialog opens. defaultDays is read at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    setConfirmUnscheduled(false);
    setHideServerWarning(false);
  }, [days, people, task, section]);

  useEffect(() => {
    if (String(error || "").startsWith("unscheduled:")) {
      setConfirmUnscheduled(true);
      setHideServerWarning(false);
    }
  }, [error]);

  const isGroup = Boolean(task?.group);
  const names = people.map((person) => person.display_name || `User #${person.user_id}`);
  const missing = useMemo(
    () => unscheduledAssignmentPairs(entries, people, days),
    [entries, people, days],
  );
  const unscheduledError = String(error || "").startsWith("unscheduled:");
  const conflicts = useMemo(
    () => (section === "tasks" && task ? taskAssignmentConflicts(responsibilities, { role: task.value, people, days }) : []),
    [section, responsibilities, task, people, days],
  );
  const showUnscheduledWarning =
    section === "tasks" && missing.length > 0 && !conflicts.length && (confirmUnscheduled || (unscheduledError && !hideServerWarning));
  const canSave =
    days.length > 0 && task && people.length > 0 && !conflicts.length && (timingMode !== TASK_TIMING.SPECIFIC || taskStart);

  const toggleDay = (dow) => {
    setDays((current) => (current.includes(dow) ? current.filter((day) => day !== dow) : [...current, dow].sort()));
  };

  const assign = () => {
    if (conflicts.length) return;
    if (missing.length && !confirmUnscheduled) {
      setConfirmUnscheduled(true);
      return;
    }
    onAssign(
      taskAssignmentPayload({
        days,
        task,
        people,
        timingMode,
        taskStart,
        remarks,
        entries,
      }).payload,
    );
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth scroll="paper">
      <DialogTitle>{t("weeklySchedule.assignBreaksTasks")}</DialogTitle>
      <DialogContent>
        <Tabs
          value={section}
          onChange={(_, value) => setSection(value)}
          sx={{ minHeight: 36, mb: 1, "& .MuiTab-root": { minHeight: 36, fontWeight: 800, textTransform: "none" } }}
        >
          <Tab value="tasks" label={t("weeklySchedule.tasksTab")} />
          <Tab value="breaks" label={t("weeklySchedule.breaksTab")} />
        </Tabs>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {section === "tasks" ? t("weeklySchedule.assignHelp") : t("weeklySchedule.breakHelp")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.5}>
            {DISPLAY_DAY_ORDER.map((dow) => (
              <Button
                key={DAY_LABELS[dow]}
                size="small"
                variant={days.includes(dow) ? "contained" : "outlined"}
                onClick={() => toggleDay(dow)}
                aria-pressed={days.includes(dow)}
                sx={{ fontWeight: 700, minWidth: 76, flexDirection: "column", lineHeight: 1.05, py: 0.5 }}
              >
                {DAY_LABELS[dow]}
                <Typography component="span" sx={{ display: "block", fontSize: "0.65rem", fontWeight: 600 }}>
                  {dayButtonLabel(weekStart, dow)}
                </Typography>
              </Button>
            ))}
          </Stack>
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
          {section === "tasks" ? (
            <>
              <Autocomplete
                options={options}
                value={task}
                onChange={(_, value) => setTask(value)}
                getOptionLabel={(option) => option.label || ""}
                isOptionEqualToValue={(option, value) => option.value === value.value}
                renderInput={(params) => <TextField {...params} label={t("weeklySchedule.taskOrGroup")} size="small" />}
              />
              <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1, px: 1, py: 0.75 }}>
                <Typography sx={{ fontWeight: 800, fontSize: "0.82rem" }}>
                  {days.length ? days.map((dow) => `${DAY_LABELS[dow]} ${dayButtonLabel(weekStart, dow)}`).join(", ") : t("weeklySchedule.selectDate")}
                </Typography>
                <Typography sx={{ fontSize: "0.8rem" }}>{names.join(", ") || t("weeklySchedule.employees")}</Typography>
                <Typography sx={{ fontSize: "0.8rem" }}>
                  {`${task?.label || t("weeklySchedule.taskOrGroup")} · ${t(`weeklySchedule.timing.${timingMode}`)}${timingMode === TASK_TIMING.SPECIFIC && taskStart ? ` ${taskStart}` : ""}`}
                </Typography>
              </Box>
              {conflicts.length ? (
                <Alert severity="error" data-assignment-conflict>
                  {conflicts.map((hit) => `${hit.name} · ${DAY_LABELS[hit.day]}`).join(", ")}
                  {` ${t("weeklySchedule.planner.willNotReplace")}`}
                </Alert>
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
              {showUnscheduledWarning ? (
                <Alert severity="warning" data-unscheduled-warning>
                  {t("weeklySchedule.unscheduledAssign")}
                  <Box component="ul" sx={{ mb: 0, mt: 0.5, pl: 2 }}>
                    {missing.map((pair) => (
                      <li key={`${pair.userId}:${pair.day}`}>{`${pair.name} · ${DAY_LABELS[pair.day]}`}</li>
                    ))}
                  </Box>
                </Alert>
              ) : null}
            </>
          ) : (
            <BreakAssignmentPanel
              people={people}
              days={days}
              entries={entries}
              weekStart={weekStart}
              saving={saving}
              onSaveBreak={onSaveBreak}
            />
          )}
          {error && !unscheduledError ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        {section === "tasks" && showUnscheduledWarning ? (
          <>
            <Button
              onClick={() => {
                setConfirmUnscheduled(false);
                setHideServerWarning(true);
              }}
            >
              {t("weeklySchedule.cancel")}
            </Button>
            <Button variant="contained" disabled={!canSave || saving} onClick={assign}>
              {saving ? t("weeklySchedule.assigning") : t("weeklySchedule.assignAnyway")}
            </Button>
          </>
        ) : (
          <>
            <Button onClick={onClose}>{t("weeklySchedule.cancel")}</Button>
            {section === "tasks" ? (
              <Button variant="contained" disabled={!canSave || saving} onClick={assign}>
                {saving ? t("weeklySchedule.assigning") : t("weeklySchedule.assign")}
              </Button>
            ) : null}
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
