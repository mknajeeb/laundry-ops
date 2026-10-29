import React, { useEffect, useMemo, useState } from "react";
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
  IconButton,
  InputLabel,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import ShiftScheduleTimeFields from "../datetime/ShiftScheduleTimeFields";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import {
  entryBreakBreakdown,
  entryBreakSlots,
  entryRoleAssignments,
  makeBreakSlot,
  scheduleRoleCatalog,
  scheduleRoleLabel,
  validateBreakSlots,
} from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND } from "./weeklyScheduleTimeBlocks";
import WeeklyScheduleBreakFields from "./WeeklyScheduleBreakFields";
import {
  TASK_TIMING,
  TASK_TIMING_OPTIONS,
  scheduleEmployeeName,
  taskMemberIds,
  taskTimingIssues,
} from "./weeklyScheduleTaskTiming";

const NO_TASKS = [];

let rowSeq = 0;
function makeRow(partial = {}) {
  rowSeq += 1;
  return {
    id: rowSeq,
    role: "",
    fullShift: true,
    start: "",
    end: "",
    remarks: "",
    timingMode: TASK_TIMING.ANYTIME,
    taskStart: "08:00",
    memberIds: [],
    ...partial,
  };
}

function rowsFromEntry(entry) {
  return entryRoleAssignments(entry).map((a) =>
    makeRow({
      role: a.role,
      savedRole: a.role,
      fullShift: a.full_shift !== false,
      start: a.full_shift !== false ? "" : a.start_time || "",
      end: a.full_shift !== false ? "" : a.end_time || "",
      remarks: a.remarks || "",
    }),
  );
}

function roleOptions(catalog, { timed, keep = [] }) {
  // Activity groups (agroup_*) appear as untimed assignable tasks with a clear label.
  const keepSet = new Set(keep.filter(Boolean));
  return catalog
    .filter((role) => {
      const matchesKind = timed ? role.uses_time_slots !== false : role.uses_time_slots === false;
      return (matchesKind && role.active !== false) || keepSet.has(role.code);
    })
    .map((role) => {
      const isGroup = String(role.code || "").startsWith("agroup_");
      let label = role.name || role.code;
      if (isGroup) label = `Group: ${label}`;
      if (role.active === false) label = `${label} (inactive)`;
      return {
        value: role.code,
        label,
        remarksEnabled: Boolean(role.remarks_enabled),
      };
    });
}

export default function WeeklyScheduleEntryDialog({
  open,
  onClose,
  onSave,
  onDelete,
  saving,
  error = "",
  entry,
  responsibility = null,
  defaultUserId,
  defaultDay,
  defaultKind = ASSIGNMENT_KIND.SHIFT,
  defaultRole = null,
  defaultStartTime = null,
  defaultEndTime = null,
  employees = null,
  taskEmployees = null,
  scheduleEntries = [],
  employeesById = {},
  scheduleEndTimeEnabled = true,
  shiftCategoryChoices = null,
  categoryLabel = (value) => value,
  dailyResponsibilities = NO_TASKS,
}) {
  const isEdit = Boolean(entry?.id || responsibility?.id);
  const catalog = scheduleRoleCatalog();
  const [kind, setKind] = useState(ASSIGNMENT_KIND.SHIFT);
  const [userId, setUserId] = useState(defaultUserId || "");
  const [category, setCategory] = useState("");
  const categoryChoices = useMemo(
    () => (shiftCategoryChoices && userId ? shiftCategoryChoices(userId) : []),
    [shiftCategoryChoices, userId],
  );
  useEffect(() => {
    setCategory(categoryChoices[0] || "");
  }, [categoryChoices]);
  const [dayOfWeek, setDayOfWeek] = useState(defaultDay ?? 0);
  const [rows, setRows] = useState([makeRow({ role: "fold" })]);
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("16:00");
  const [breakSlots, setBreakSlots] = useState([]);
  const [unscheduledBreak, setUnscheduledBreak] = useState(0);
  const [respRole, setRespRole] = useState("");
  const [respRemarks, setRespRemarks] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [userIds, setUserIds] = useState([]);
  const [timingMode, setTimingMode] = useState(TASK_TIMING.ANYTIME);
  const [taskStart, setTaskStart] = useState("08:00");
  const [executionMode, setExecutionMode] = useState("individual");
  const [taskRows, setTaskRows] = useState([]);
  const [tasksTouched, setTasksTouched] = useState(false);

  const timedOptions = useMemo(() => roleOptions(catalog, { timed: true }), [catalog]);
  const untimedOptions = useMemo(
    () => roleOptions(catalog, { timed: false, keep: [responsibility?.role] }),
    [catalog, responsibility],
  );
  const savedTimedOptions = useMemo(
    () => roleOptions(catalog, { timed: true, keep: entryRoleAssignments(entry || {}).map((a) => a.role) }),
    [catalog, entry],
  );
  const optionByRole = useMemo(
    () => Object.fromEntries([...savedTimedOptions, ...untimedOptions].map((opt) => [opt.value, opt])),
    [savedTimedOptions, untimedOptions],
  );
  const rowRoleOptions = (row) =>
    row.savedRole ? roleOptions(catalog, { timed: true, keep: [row.savedRole] }) : timedOptions;

  useEffect(() => {
    if (!open) return;
    if (responsibility) {
      setKind(ASSIGNMENT_KIND.RESPONSIBILITY);
      setUserId(responsibility.user_id);
      setUserIds(taskMemberIds(responsibility));
      setDayOfWeek(responsibility.day_of_week);
      setRespRole(responsibility.role);
      setRespRemarks(responsibility.remarks || "");
      setCorrectionReason("");
      setTimingMode(responsibility.timing_mode || TASK_TIMING.ANYTIME);
      setTaskStart(responsibility.start_time || "08:00");
      setExecutionMode(responsibility.execution_mode === "shared" ? "shared" : "individual");
      return;
    }
    if (entry) {
      setKind(ASSIGNMENT_KIND.SHIFT);
      setUserId(entry.user_id);
      setDayOfWeek(entry.day_of_week);
      setRows(rowsFromEntry(entry));
      setStartTime(entry.start_time || "09:00");
      setEndTime(entry.end_time || "16:00");
      const slots = entryBreakSlots(entry);
      setBreakSlots(slots.map((slot) => makeBreakSlot(slot)));
      setUnscheduledBreak(
        entry.unscheduled_break_minutes != null
          ? Number(entry.unscheduled_break_minutes)
          : slots.length
            ? 0
            : Number(entry.break_minutes || 0),
      );
      return;
    }
    const kindForRole = defaultRole
      ? (catalog.find((r) => r.code === defaultRole)?.uses_time_slots === false
        ? ASSIGNMENT_KIND.RESPONSIBILITY
        : ASSIGNMENT_KIND.SHIFT)
      : defaultKind;
    setKind(kindForRole);
    setUserId(defaultUserId || "");
    setDayOfWeek(defaultDay ?? 0);
    const firstTimed = timedOptions.find((opt) => opt.value === "fold")?.value || timedOptions[0]?.value || "";
    setRows([makeRow({ role: kindForRole === ASSIGNMENT_KIND.SHIFT && defaultRole ? defaultRole : firstTimed })]);
    setStartTime(defaultStartTime || "09:00");
    setEndTime(defaultEndTime || "16:00");
    setBreakSlots([]);
    setUnscheduledBreak(0);
    setRespRole(kindForRole === ASSIGNMENT_KIND.RESPONSIBILITY && defaultRole ? defaultRole : untimedOptions[0]?.value || "");
    setRespRemarks("");
    setCorrectionReason("");
    setUserIds(defaultUserId ? [Number(defaultUserId)] : []);
    setTimingMode(TASK_TIMING.ANYTIME);
    setTaskStart(defaultStartTime || "08:00");
    setExecutionMode("individual");
  }, [open, entry, responsibility, defaultUserId, defaultDay, defaultKind, defaultRole, defaultStartTime, defaultEndTime]); // eslint-disable-line react-hooks/exhaustive-deps

  // The day's saved tasks for the chosen employee; reloaded whenever the employee or day changes so a
  // save never replaces another day's tasks with rows typed for this one.
  const savedDayTasks = useMemo(
    () =>
      (dailyResponsibilities || []).filter(
        (item) => Number(item.user_id) === Number(userId) && Number(item.day_of_week) === Number(dayOfWeek),
      ),
    [dailyResponsibilities, userId, dayOfWeek],
  );
  useEffect(() => {
    if (!open) return;
    setTaskRows(
      savedDayTasks.map((item) =>
        makeRow({
          role: item.role,
          savedRole: item.role,
          remarks: item.remarks || "",
          timingMode: item.timing_mode || TASK_TIMING.ANYTIME,
          taskStart: item.start_time || "08:00",
          memberIds: taskMemberIds(item),
        }),
      ),
    );
    setTasksTouched(false);
  }, [open, savedDayTasks]);

  const isShift = kind === ASSIGNMENT_KIND.SHIFT;
  const respIsActivityGroup = String(respRole || "").startsWith("agroup_");
  const canChooseSharedExecution = !isShift && respIsActivityGroup && userIds.length >= 2;
  useEffect(() => {
    if (!canChooseSharedExecution && executionMode === "shared") {
      setExecutionMode("individual");
    }
  }, [canChooseSharedExecution, executionMode]);
  const canSplit = scheduleEndTimeEnabled;
  const taskEmployeeOptions = useMemo(() => {
    const list = Array.isArray(taskEmployees) ? taskEmployees : [];
    const byId = new Map(list.map((employee) => [Number(employee.user_id), employee]));
    for (const id of userIds) {
      if (!byId.has(Number(id))) {
        byId.set(Number(id), employeesById?.[id] || employeesById?.[String(id)] || { user_id: Number(id), display_name: `User #${id}` });
      }
    }
    return [...byId.values()].sort((a, b) =>
      String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, { sensitivity: "base" }),
    );
  }, [taskEmployees, userIds, employeesById]);

  const previewEntries = useMemo(() => {
    const saved = scheduleEntries || [];
    if (!isShift || !userId) return saved;
    const others = saved.filter(
      (entry) => !(Number(entry.user_id) === Number(userId) && Number(entry.day_of_week) === Number(dayOfWeek)),
    );
    const slots = breakSlots.map((slot) => ({ start_time: slot.start_time, end_time: slot.end_time }));
    return [
      ...others,
      {
        user_id: Number(userId),
        day_of_week: Number(dayOfWeek),
        start_time: startTime,
        end_time: endTime,
        break_slots: slots,
        unscheduled_break_minutes: Math.max(0, Math.round(Number(unscheduledBreak || 0))),
      },
    ];
  }, [scheduleEntries, isShift, userId, dayOfWeek, startTime, endTime, breakSlots, unscheduledBreak]);

  const taskPreview = useMemo(() => {
    if (isShift) return { errors: [], warnings: [] };
    return taskTimingIssues(
      {
        user_id: userIds[0],
        user_ids: userIds,
        day_of_week: dayOfWeek,
        timing_mode: timingMode,
        start_time: timingMode === TASK_TIMING.SPECIFIC ? taskStart : null,
      },
      previewEntries,
      employeesById,
    );
  }, [isShift, userIds, dayOfWeek, timingMode, taskStart, previewEntries, employeesById]);

  const updateRow = (id, patch) => setRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  const removeRow = (id) => setRows((prev) => prev.filter((row) => row.id !== id));

  const editTasks = (update) => {
    setTasksTouched(true);
    setTaskRows(update);
  };
  const taskRowOptions = (row) => {
    const taken = new Set(taskRows.filter((other) => other.id !== row.id).map((other) => other.role));
    return roleOptions(catalog, { timed: false, keep: [row.savedRole] }).filter((opt) => !taken.has(opt.value));
  };
  const nextTaskRole = () => {
    const taken = new Set(taskRows.map((row) => row.role));
    return roleOptions(catalog, { timed: false }).find((opt) => !taken.has(opt.value))?.value || "";
  };

  const canSave = useMemo(() => {
    if (isShift) {
      if (!userId) return false;
      if (!startTime || (scheduleEndTimeEnabled && !endTime)) return false;
      if (scheduleEndTimeEnabled && validateBreakSlots(startTime, endTime, breakSlots)) return false;
      if (taskRows.some((row) => !row.role || (row.timingMode === TASK_TIMING.SPECIFIC && !row.taskStart))) return false;
      if (
        taskRows.some(
          (row) =>
            taskTimingIssues(
              {
                user_id: Number(userId),
                user_ids: row.memberIds?.length ? row.memberIds : [Number(userId)],
                day_of_week: dayOfWeek,
                timing_mode: row.timingMode,
                start_time: row.timingMode === TASK_TIMING.SPECIFIC ? row.taskStart : null,
              },
              previewEntries,
              employeesById,
            ).errors.length,
        )
      ) {
        return false;
      }
      if (new Set(taskRows.map((row) => row.role)).size !== taskRows.length) return false;
      return rows.every((row) => row.role && (row.fullShift || !canSplit || (row.start && row.end)));
    }
    if (!userIds.length || !respRole) return false;
    if (timingMode === TASK_TIMING.SPECIFIC && !taskStart) return false;
    return taskPreview.errors.length === 0;
  }, [
    userId,
    userIds,
    isShift,
    respRole,
    timingMode,
    taskStart,
    taskPreview.errors.length,
    startTime,
    endTime,
    breakSlots,
    rows,
    taskRows,
    scheduleEndTimeEnabled,
    canSplit,
    previewEntries,
    employeesById,
    dayOfWeek,
  ]);

  // break_minutes is the total so a server without break slots still deducts the right hours.
  const breakPayload = () => {
    const slots = breakSlots.map((slot) => ({ start_time: slot.start_time, end_time: slot.end_time }));
    const parts = entryBreakBreakdown({ start_time: startTime, end_time: endTime, break_minutes: 0, break_slots: slots });
    const unscheduled = Math.max(0, Math.round(Number(unscheduledBreak || 0)));
    return {
      end_time: endTime,
      break_minutes: parts.timedBreakMinutes + unscheduled,
      break_slots: slots,
      unscheduled_break_minutes: unscheduled,
    };
  };

  const handleSubmit = () => {
    if (!canSave) return;
    if (!isShift) {
      onSave({
        kind: ASSIGNMENT_KIND.RESPONSIBILITY,
        user_id: Number(userIds[0]),
        user_ids: userIds.map(Number),
        day_of_week: Number(dayOfWeek),
        role: respRole,
        remarks: respRemarks.trim() || null,
        timing_mode: timingMode,
        start_time: timingMode === TASK_TIMING.SPECIFIC ? taskStart : null,
        execution_mode: canChooseSharedExecution && executionMode === "shared" ? "shared" : "individual",
        ...(correctionReason.trim()
          ? { confirm_active_change: true, correction_reason: correctionReason.trim() }
          : {}),
      });
      return;
    }
    onSave({
      kind: ASSIGNMENT_KIND.SHIFT,
      user_id: Number(userId),
      day_of_week: Number(dayOfWeek),
      ...(!isEdit && category ? { employer_affiliation: category } : {}),
      start_time: startTime,
      ...(scheduleEndTimeEnabled ? breakPayload() : { end_time: startTime, break_minutes: 0, break_slots: [] }),
      assignments: rows.map((row) => {
        const full = row.fullShift || !canSplit;
        return {
          role: row.role,
          full_shift: full,
          start_time: full ? null : row.start,
          end_time: full ? null : row.end,
          remarks: row.remarks.trim() || null,
        };
      }),
      ...(tasksTouched
        ? {
            tasks: taskRows.map((row) => ({
              role: row.role,
              remarks: row.remarks.trim() || null,
              timing_mode: row.timingMode || TASK_TIMING.ANYTIME,
              start_time: row.timingMode === TASK_TIMING.SPECIFIC ? row.taskStart : null,
            })),
          }
        : {}),
    });
  };

  const showEmployeePicker = Array.isArray(employees) && !isEdit && isShift;
  const assignedNames = userIds
    .map((id) => {
      const fromList = taskEmployeeOptions.find((employee) => Number(employee.user_id) === Number(id));
      return fromList?.display_name || scheduleEmployeeName(employeesById, id);
    })
    .filter(Boolean);
  const title = isShift
    ? (isEdit ? "Edit shift" : "Add shift")
    : (isEdit ? "Edit task" : "Add task");

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {!isEdit && untimedOptions.length ? (
            <ToggleButtonGroup
              size="small"
              exclusive
              value={kind}
              onChange={(_, next) => {
                if (!next) return;
                setKind(next);
                if (next === ASSIGNMENT_KIND.RESPONSIBILITY && userId) {
                  setUserIds((prev) => (prev.length ? prev : [Number(userId)]));
                }
              }}
              sx={{ "& .MuiToggleButton-root": { textTransform: "none", fontWeight: 700, px: 1.5 } }}
            >
              <ToggleButton value={ASSIGNMENT_KIND.SHIFT}>Shift (timed roles)</ToggleButton>
              <ToggleButton value={ASSIGNMENT_KIND.RESPONSIBILITY}>Task</ToggleButton>
            </ToggleButtonGroup>
          ) : null}

          {showEmployeePicker ? (
            <FormControl size="small" fullWidth>
              <InputLabel>Employee</InputLabel>
              <Select label="Employee" value={userId || ""} onChange={(e) => setUserId(e.target.value)}>
                {employees.map((emp) => (
                  <MenuItem key={emp.user_id} value={emp.user_id}>
                    {emp.display_name || `User #${emp.user_id}`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}

          {isShift && !isEdit && categoryChoices.length ? (
            <FormControl size="small" fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                label="Category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                disabled={categoryChoices.length < 2}
              >
                {categoryChoices.map((value) => (
                  <MenuItem key={value} value={value}>
                    {categoryLabel(value)}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}

          {isShift ? (
            <>
              <ShiftScheduleTimeFields
                startTime={startTime}
                endTime={endTime}
                onStartChange={setStartTime}
                onEndChange={setEndTime}
                endTimeEnabled={scheduleEndTimeEnabled}
                overnightEnabled
              />
              {scheduleEndTimeEnabled ? (
                <WeeklyScheduleBreakFields
                  startTime={startTime}
                  endTime={endTime}
                  slots={breakSlots}
                  onSlotsChange={setBreakSlots}
                  unscheduledMinutes={unscheduledBreak}
                  onUnscheduledChange={setUnscheduledBreak}
                />
              ) : null}
              <Box>
                <Typography variant="subtitle2" fontWeight={800}>
                  Roles during this shift
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  {canSplit
                    ? "Turn off “Whole shift” to set the hours an employee spends on a role. Hours and attendance follow the shift times above."
                    : "Each role covers the whole shift."}
                </Typography>
                <Stack spacing={1.25}>
                  {!rows.length ? (
                    <Alert severity="info" sx={{ py: 0 }}>
                      No production role. The shift keeps its times, break, and hours.
                    </Alert>
                  ) : null}
                  {rows.map((row) => {
                    const opt = optionByRole[row.role];
                    const showRemarks = Boolean(opt?.remarksEnabled || row.remarks);
                    return (
                      <Box
                        key={row.id}
                        sx={{ border: "1px solid #e2e8f0", borderRadius: 1.5, p: 1.25, bgcolor: "#fafbfc" }}
                      >
                        <Stack direction="row" spacing={1} alignItems="center">
                          <FormControl size="small" sx={{ flex: 1, minWidth: 0 }}>
                            <InputLabel>Role</InputLabel>
                            <Select
                              label="Role"
                              value={row.role}
                              onChange={(e) => updateRow(row.id, { role: e.target.value })}
                            >
                              {rowRoleOptions(row).map((option) => (
                                <MenuItem key={option.value} value={option.value}>
                                  {option.label}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                          {canSplit ? (
                            <FormControlLabel
                              sx={{ m: 0, flexShrink: 0 }}
                              control={
                                <Switch
                                  size="small"
                                  checked={row.fullShift}
                                  onChange={(e) =>
                                    updateRow(row.id, {
                                      fullShift: e.target.checked,
                                      start: row.start || startTime,
                                      end: row.end || endTime,
                                    })
                                  }
                                />
                              }
                              label={<Typography variant="caption" fontWeight={700}>Whole shift</Typography>}
                            />
                          ) : null}
                          <IconButton
                            size="small"
                            aria-label="Remove role"
                            onClick={() => removeRow(row.id)}
                          >
                            <CloseIcon fontSize="small" />
                          </IconButton>
                        </Stack>
                        {canSplit && !row.fullShift ? (
                          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
                            <PlanningTimePicker
                              label="Role start"
                              value={row.start}
                              onChange={(v) => updateRow(row.id, { start: v })}
                            />
                            <PlanningTimePicker
                              label="Role end"
                              value={row.end}
                              onChange={(v) => updateRow(row.id, { end: v })}
                            />
                          </Stack>
                        ) : null}
                        {showRemarks ? (
                          <TextField
                            size="small"
                            fullWidth
                            label="Remarks"
                            placeholder="e.g. Dryers 1–12"
                            value={row.remarks}
                            onChange={(e) => updateRow(row.id, { remarks: e.target.value })}
                            inputProps={{ maxLength: 255 }}
                            sx={{ mt: 1 }}
                          />
                        ) : null}
                      </Box>
                    );
                  })}
                </Stack>
                <Button
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={() => setRows((prev) => [...prev, makeRow({ role: timedOptions[0]?.value || "" })])}
                  sx={{ mt: 1, fontWeight: 700 }}
                >
                  Add role
                </Button>
              </Box>
              <Box sx={{ border: "1px solid #dbe4ea", borderRadius: 1.5, p: 1.25, bgcolor: "#f8fafc" }}>
                <Typography variant="subtitle2" fontWeight={800}>
                  Tasks / Instructions
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  Tasks for this employee on this day. They add no hours, and they do not change the shift or the break above.
                </Typography>
                <Stack spacing={1}>
                  {taskRows.map((row) => {
                    const options = taskRowOptions(row);
                    const issues = taskTimingIssues(
                      {
                        user_id: Number(userId),
                        user_ids: row.memberIds?.length ? row.memberIds : [Number(userId)],
                        day_of_week: dayOfWeek,
                        timing_mode: row.timingMode,
                        start_time: row.timingMode === TASK_TIMING.SPECIFIC ? row.taskStart : null,
                      },
                      previewEntries,
                      employeesById,
                    );
                    return (
                      <Box key={row.id} sx={{ border: "1px solid #e2e8f0", borderRadius: 1.5, p: 1, bgcolor: "#fff" }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <FormControl size="small" sx={{ flex: 1, minWidth: 0 }}>
                            <InputLabel>Task</InputLabel>
                            <Select
                              label="Task"
                              value={options.some((opt) => opt.value === row.role) ? row.role : ""}
                              onChange={(e) =>
                                editTasks((prev) =>
                                  prev.map((r) => (r.id === row.id ? { ...r, role: e.target.value } : r)),
                                )
                              }
                            >
                              {options.map((option) => (
                                <MenuItem key={option.value} value={option.value}>
                                  {option.label}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                          <IconButton
                            size="small"
                            aria-label="Remove task"
                            onClick={() => editTasks((prev) => prev.filter((r) => r.id !== row.id))}
                          >
                            <CloseIcon fontSize="small" />
                          </IconButton>
                        </Stack>
                        <TextField
                          size="small"
                          fullWidth
                          multiline
                          minRows={1}
                          label="Instructions"
                          placeholder="e.g. Clean lint traps on dryers 1–12"
                          value={row.remarks}
                          onChange={(e) =>
                            editTasks((prev) =>
                              prev.map((r) => (r.id === row.id ? { ...r, remarks: e.target.value } : r)),
                            )
                          }
                          inputProps={{ maxLength: 255 }}
                          sx={{ mt: 1 }}
                        />
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
                          <FormControl size="small" sx={{ flex: 1, minWidth: 0 }}>
                            <InputLabel>Timing</InputLabel>
                            <Select
                              label="Timing"
                              value={row.timingMode || TASK_TIMING.ANYTIME}
                              onChange={(e) =>
                                editTasks((prev) =>
                                  prev.map((r) => (r.id === row.id ? { ...r, timingMode: e.target.value } : r)),
                                )
                              }
                            >
                              {TASK_TIMING_OPTIONS.map((option) => (
                                <MenuItem key={option.value} value={option.value}>
                                  {option.label}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                          {row.timingMode === TASK_TIMING.SPECIFIC ? (
                            <PlanningTimePicker
                              label="Start time"
                              value={row.taskStart}
                              onChange={(value) =>
                                editTasks((prev) => prev.map((r) => (r.id === row.id ? { ...r, taskStart: value } : r)))
                              }
                            />
                          ) : null}
                        </Stack>
                        {(row.memberIds || []).length > 1 ? (
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
                            {`Shared with ${(row.memberIds || [])
                              .filter((id) => Number(id) !== Number(userId))
                              .map((id) => scheduleEmployeeName(employeesById, id))
                              .join(", ")}. Timing applies to the whole group.`}
                          </Typography>
                        ) : null}
                        {issues.errors.map((message) => (
                          <Typography key={message} variant="caption" display="block" sx={{ mt: 0.5, color: "error.main", fontWeight: 700 }}>
                            {message}
                          </Typography>
                        ))}
                        {issues.warnings.map((warning) => (
                          <Typography key={warning} variant="caption" display="block" sx={{ mt: 0.5, color: "#b45309", fontWeight: 700 }}>
                            {warning}
                          </Typography>
                        ))}
                      </Box>
                    );
                  })}
                </Stack>
                <Button
                  size="small"
                  startIcon={<AddIcon />}
                  disabled={!userId || !nextTaskRole()}
                  onClick={() => editTasks((prev) => [...prev, makeRow({ role: nextTaskRole() })])}
                  sx={{ mt: 1, fontWeight: 700 }}
                >
                  Add task
                </Button>
                {!roleOptions(catalog, { timed: false }).length ? (
                  <Typography variant="caption" color="text.secondary" display="block">
                    No tasks are set up yet. Add one under Roles &amp; tasks.
                  </Typography>
                ) : null}
              </Box>
            </>
          ) : (
            <>
              <FormControl size="small" fullWidth>
                <InputLabel>Employees</InputLabel>
                <Select
                  multiple
                  label="Employees"
                  value={userIds}
                  onChange={(e) => {
                    const next = e.target.value;
                    setUserIds((Array.isArray(next) ? next : [next]).map(Number));
                  }}
                  renderValue={(selected) =>
                    (selected || [])
                      .map((id) => {
                        const fromList = taskEmployeeOptions.find((employee) => Number(employee.user_id) === Number(id));
                        return fromList?.display_name || scheduleEmployeeName(employeesById, id);
                      })
                      .join(", ")
                  }
                >
                  {taskEmployeeOptions.map((employee) => (
                    <MenuItem key={employee.user_id} value={Number(employee.user_id)}>
                      <Checkbox size="small" checked={userIds.includes(Number(employee.user_id))} sx={{ p: 0.5, mr: 1 }} />
                      <ListItemText primary={employee.display_name || `User #${employee.user_id}`} />
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                {assignedNames.length
                  ? `Assigned: ${assignedNames.join(", ")}`
                  : "Select every employee on this assignment."}
              </Typography>
              {respIsActivityGroup && userIds.length < 2 ? (
                <Typography variant="caption" color="text.secondary">
                  Select two or more employees to use Shared Execution — one checklist for the group, with a separate timer for each person.
                </Typography>
              ) : null}
              <FormControl size="small" fullWidth>
                <InputLabel>Task</InputLabel>
                <Select label="Task" value={respRole} onChange={(e) => setRespRole(e.target.value)}>
                  {untimedOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
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
              {canChooseSharedExecution ? (
                <FormControl size="small" fullWidth>
                  <InputLabel>Activity execution</InputLabel>
                  <Select
                    label="Activity execution"
                    value={executionMode}
                    onChange={(e) => setExecutionMode(e.target.value)}
                  >
                    <MenuItem value="individual">Individual — each person completes their own checklist</MenuItem>
                    <MenuItem value="shared">Shared Execution — one checklist, separate timers</MenuItem>
                  </Select>
                </FormControl>
              ) : null}
              {["in_progress", "completed", "approved", "pending_approval", "rejected"].includes(responsibility?.activity_status) ? (
                <>
                  <Alert severity="warning">
                    This assignment has already started or been completed. Changing participants, the day, timing, or
                    execution mode needs a correction reason. Activity and verification history stay on the original record.
                  </Alert>
                  <TextField
                    size="small"
                    fullWidth
                    label="Correction reason"
                    value={correctionReason}
                    onChange={(e) => setCorrectionReason(e.target.value)}
                    inputProps={{ maxLength: 255 }}
                  />
                </>
              ) : null}
              <TextField
                size="small"
                fullWidth
                multiline
                minRows={2}
                label="Instructions"
                placeholder="e.g. Clean lint traps on dryers 1–12 before the break"
                value={respRemarks}
                onChange={(e) => setRespRemarks(e.target.value)}
                inputProps={{ maxLength: 255 }}
              />
              {taskPreview.errors.map((message) => (
                <Alert key={message} severity="error">{message}</Alert>
              ))}
              {taskPreview.warnings.map((message) => (
                <Alert key={message} severity="warning">{message}</Alert>
              ))}
              <Typography variant="caption" color="text.secondary">
                {scheduleRoleLabel(respRole) || "This task"} is one assignment for the selected employees. It adds no
                scheduled hours. Anytime keeps the task on the day. The other timing options follow each employee&apos;s
                shift and scheduled break, and they do not move that break.
                {canChooseSharedExecution && executionMode === "shared"
                  ? " Shared execution: one checklist any assignee can check off; each person keeps their own timer."
                  : ""}
              </Typography>
            </>
          )}

          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        {isEdit && onDelete ? (
          <Button color="error" onClick={onDelete} disabled={saving} sx={{ mr: "auto" }}>
            Delete
          </Button>
        ) : null}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!canSave || saving} onClick={handleSubmit}>
          {saving ? "Saving…" : isEdit ? "Save" : "Add"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
