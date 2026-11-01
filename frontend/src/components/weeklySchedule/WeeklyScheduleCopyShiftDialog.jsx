import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { entryBreakLines, scheduleRoleInfo } from "./weeklyScheduleRoles";
import { taskTimingLabel } from "./weeklyScheduleTaskTiming";

const DAY_INDEXES = [0, 1, 2, 3, 4, 5, 6];

function roleName(code) {
  return scheduleRoleInfo(code)?.name || code;
}

function assignmentLine(assignment) {
  const name = roleName(assignment.role);
  const range =
    assignment.full_shift || !assignment.start_time
      ? "Whole shift"
      : `${formatTime12(assignment.start_time)}–${formatTime12(assignment.end_time)}`;
  return [name, range, assignment.remarks].filter(Boolean).join(" · ");
}

function taskLine(task) {
  const timing = task.timing_label || taskTimingLabel(task) || "Anytime";
  const shared = task.shared || (task.execution_mode === "shared" && (task.user_ids || []).length > 1);
  return [roleName(task.role), timing, task.remarks, shared ? "Shared activity" : ""].filter(Boolean).join(" · ");
}

function targetKey(userId, day) {
  return `${userId}:${day}`;
}

export default function WeeklyScheduleCopyShiftDialog({
  open,
  entry,
  employeeName,
  responsibilities = [],
  employees = [],
  onClose,
  onPreview,
  onCopy,
  inline = false,
}) {
  const [selectedEmployees, setSelectedEmployees] = useState([]);
  const [days, setDays] = useState([]);
  const [conflictMode, setConflictMode] = useState("skip");
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [resolutions, setResolutions] = useState({});
  const [selectedRoles, setSelectedRoles] = useState(null);
  const [activityModes, setActivityModes] = useState({});
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);
  const [previewNonce, setPreviewNonce] = useState(0);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    if (!open) return;
    setSelectedEmployees([]);
    setDays([]);
    setConflictMode("skip");
    setConfirmReplace(false);
    setResolutions({});
    setSelectedRoles(null);
    setActivityModes({});
    setPreview(null);
    setPreviewError("");
    setResult(null);
    setSaveError("");
  }, [open, entry?.id]);

  const previewRef = useRef(onPreview);
  previewRef.current = onPreview;

  const sourceTasks = useMemo(() => {
    if (!entry) return [];
    return (responsibilities || []).filter(
      (item) => Number(item.user_id) === Number(entry.user_id) && Number(item.day_of_week) === Number(entry.day_of_week),
    );
  }, [entry, responsibilities]);

  const source = preview?.source;
  const assignments = source?.assignments || entry?.assignments || [];
  const breaks = entry ? entryBreakLines(entry) : [];
  const taskRows = source?.tasks?.length ? source.tasks : sourceTasks;
  const taskRoleKey = selectedRoles
    ? `chosen:${[...selectedRoles].sort().join(",")}`
    : source?.tasks
      ? `auto:${source.tasks
          .filter((task) => task.selected_by_default)
          .map((task) => task.role)
          .sort()
          .join(",")}`
      : "auto";
  const activityModeKey = JSON.stringify(activityModes);

  const requestBody = (extra = {}) => {
    const body = {
      user_ids: selectedEmployees.map((employee) => Number(employee.user_id)),
      days_of_week: days,
      conflict_mode: conflictMode,
      resolutions: Object.entries(resolutions).map(([key, action]) => {
        const [userId, day] = key.split(":");
        return { user_id: Number(userId), day_of_week: Number(day), action };
      }),
      ...extra,
    };
    if (selectedRoles) {
      body.task_roles = selectedRoles;
    } else if (source?.tasks) {
      body.task_roles = source.tasks.filter((task) => task.selected_by_default).map((task) => task.role);
    }
    const modes = Object.entries(activityModes).map(([role, mode]) => ({ role, mode }));
    if (modes.length) body.activity_modes = modes;
    return body;
  };

  useEffect(() => {
    if (!open || !entry?.id || !selectedEmployees.length || !days.length) {
      setPreview(null);
      setPreviewError("");
      return undefined;
    }
    let cancelled = false;
    const handle = setTimeout(async () => {
      setPreviewing(true);
      setPreviewError("");
      try {
        const data = await previewRef.current(requestBody());
        if (!cancelled) setPreview(data);
      } catch (error) {
        if (!cancelled) {
          setPreview(null);
          setPreviewError(error?.response?.data?.error || "Could not preview this copy.");
        }
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [open, entry?.id, selectedEmployees, days, conflictMode, resolutions, taskRoleKey, activityModeKey, previewNonce]);

  const counts = preview?.counts || { create: 0, replace: 0, skip: 0, needs_resolution: 0 };
  const needsReplaceConfirm = conflictMode === "replace" && counts.replace > 0;
  const unresolved = (preview?.targets || []).filter((target) => target.action === "needs_resolution");
  const canCopy =
    Boolean(selectedEmployees.length && days.length && preview && !previewing && !previewError) &&
    counts.needs_resolution === 0 &&
    counts.create + counts.replace > 0 &&
    (!needsReplaceConfirm || confirmReplace);

  const toggleDay = (day) => {
    setDays((current) => (current.includes(day) ? current.filter((value) => value !== day) : [...current, day].sort()));
  };

  const setResolution = (target, action) => {
    setResolutions((current) => ({ ...current, [targetKey(target.user_id, target.day_of_week)]: action }));
  };

  const handleCopy = async () => {
    if (!canCopy) return;
    setSaving(true);
    setSaveError("");
    try {
      const copy = await onCopy(requestBody({ confirm_replace: confirmReplace }));
      setResult(copy);
      setPreviewNonce((value) => value + 1);
    } catch (error) {
      setSaveError(error?.response?.data?.error || "Could not copy this shift.");
    } finally {
      setSaving(false);
    }
  };

  const skipped = (preview?.targets || []).filter((target) => target.action === "skip" && target.reason !== "Source shift");

  const taskChecked = (task) => {
    if (selectedRoles) return selectedRoles.includes(task.role);
    if (task.selected_by_default !== undefined) return Boolean(task.selected_by_default);
    return true;
  };

  const toggleTask = (role) => {
    const current = taskRows.filter((task) => taskChecked(task)).map((task) => task.role);
    setSelectedRoles(current.includes(role) ? current.filter((item) => item !== role) : [...current, role]);
  };

  const sharedActivities = (preview?.activities || []).filter((activity) =>
    taskRows.some((task) => task.role === activity.role && taskChecked(task)),
  );

  const dialogBody = (
    <>
      <DialogTitle sx={{ fontWeight: 800, pb: 0.5 }}>Copy shift</DialogTitle>
      <DialogContent>
        <Stack spacing={1.75} sx={{ mt: 0.5 }}>
          <Box>
            <Typography variant="overline" sx={{ fontWeight: 800, letterSpacing: "0.06em" }}>
              Source shift
            </Typography>
            <Typography variant="body2" fontWeight={700}>
              {employeeName || source?.employee_name || "Employee"} · {DAY_LABELS[entry?.day_of_week] || source?.day_label}
            </Typography>
            <Typography variant="body2">
              {entry ? `${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}` : ""}
            </Typography>
            {breaks.length ? (
              <Typography variant="body2" color="text.secondary">
                {breaks.join(" · ")}
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary">
                No scheduled break
              </Typography>
            )}
            {assignments.length ? (
              <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                {assignments.map((assignment, index) => (
                  <Typography key={`${assignment.role}-${index}`} variant="body2">
                    {assignmentLine(assignment)}
                  </Typography>
                ))}
              </Stack>
            ) : null}
            <Box sx={{ mt: 0.75 }}>
              <Typography variant="subtitle2" fontWeight={800}>
                Tasks to copy
              </Typography>
              {taskRows.length ? (
                <Stack spacing={0.25} sx={{ mt: 0.25 }}>
                  {taskRows.map((task) => (
                    <Box key={task.id || task.role}>
                      <FormControlLabel
                        sx={{ alignItems: "flex-start", ml: 0 }}
                        control={
                          <Checkbox
                            size="small"
                            checked={taskChecked(task)}
                            onChange={() => toggleTask(task.role)}
                          />
                        }
                        label={<Typography variant="body2">{taskLine(task)}</Typography>}
                      />
                      {task.selection_note ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ pl: 4 }}>
                          {task.selection_note}
                        </Typography>
                      ) : null}
                      {(task.checklist_items || []).map((item) => (
                        <Typography
                          key={item.task_code || item.group_item_id}
                          variant="caption"
                          color="text.secondary"
                          display="block"
                          sx={{ pl: 4 }}
                        >
                          {item.task_name}: {item.responsibility_label || "Anyone on Team"}
                        </Typography>
                      ))}
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No tasks on this day
                </Typography>
              )}
            </Box>
            {sharedActivities.map((activity) => (
              <Box key={activity.role}>
                <Typography variant="subtitle2" fontWeight={800}>
                  {activity.label}
                </Typography>
                <RadioGroup
                  value={activityModes[activity.role] || activity.mode || "independent"}
                  onChange={(event) =>
                    setActivityModes((current) => ({ ...current, [activity.role]: event.target.value }))
                  }
                >
                  <FormControlLabel
                    value="join"
                    disabled={!activity.join_available}
                    control={<Radio size="small" />}
                    label="Join existing activity"
                  />
                  <FormControlLabel value="independent" control={<Radio size="small" />} label="Separate assignment" />
                </RadioGroup>
                <Typography variant="caption" color="text.secondary">
                  {activity.note}
                </Typography>
              </Box>
            ))}
          </Box>

          <Autocomplete
            multiple
            size="small"
            options={employees}
            value={selectedEmployees}
            onChange={(_event, value) => setSelectedEmployees(value)}
            getOptionLabel={(employee) => employee.display_name || `User #${employee.user_id}`}
            isOptionEqualToValue={(left, right) => Number(left.user_id) === Number(right.user_id)}
            renderInput={(params) => <TextField {...params} label="Assign to" placeholder="Search employees" />}
            renderTags={(value, getTagProps) =>
              value.map((employee, index) => (
                <Chip
                  {...getTagProps({ index })}
                  key={employee.user_id}
                  size="small"
                  label={employee.display_name || `User #${employee.user_id}`}
                />
              ))
            }
          />

          <Box>
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography variant="subtitle2" fontWeight={800}>
                Days
              </Typography>
              <Stack direction="row" spacing={0.5}>
                <Button size="small" onClick={() => setDays([...DAY_INDEXES])}>
                  Select all
                </Button>
                <Button size="small" onClick={() => setDays([])}>
                  Clear all
                </Button>
              </Stack>
            </Stack>
            <Stack direction="row" useFlexGap flexWrap="wrap" spacing={0.5} sx={{ mt: 0.5 }}>
              {DAY_LABELS.map((label, day) => (
                <Chip
                  key={label}
                  label={label}
                  size="small"
                  color={days.includes(day) ? "primary" : "default"}
                  variant={days.includes(day) ? "filled" : "outlined"}
                  onClick={() => toggleDay(day)}
                />
              ))}
            </Stack>
          </Box>

          <Box>
            <Typography variant="subtitle2" fontWeight={800}>
              If a shift already exists
            </Typography>
            <RadioGroup
              value={conflictMode}
              onChange={(event) => {
                setConflictMode(event.target.value);
                setConfirmReplace(false);
              }}
            >
              <FormControlLabel value="skip" control={<Radio size="small" />} label="Skip existing shifts" />
              <FormControlLabel value="replace" control={<Radio size="small" />} label="Replace existing shifts" />
            </RadioGroup>
            {needsReplaceConfirm ? (
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={confirmReplace}
                    onChange={(event) => setConfirmReplace(event.target.checked)}
                  />
                }
                label="Replace the existing shifts on the selected employee days."
              />
            ) : null}
          </Box>

          {previewError ? <Alert severity="error">{previewError}</Alert> : null}
          {saveError ? <Alert severity="error">{saveError}</Alert> : null}
          {result?.message ? <Alert severity="success">{result.message}</Alert> : null}
          {result?.skipped_targets?.length ? (
            <Alert severity="info">
              {result.skipped_targets.map((target) => `${target.employee_name} · ${target.day_label}: ${target.reason}`).join(" ")}
            </Alert>
          ) : null}

          {selectedEmployees.length && days.length ? (
            <Box>
              <Typography variant="body2" fontWeight={700}>
                {previewing && !preview
                  ? "Checking the schedule…"
                  : preview
                    ? `${counts.create} to create, ${counts.replace} to replace, ${counts.skip} to skip.`
                    : ""}
              </Typography>
              {skipped.map((target) => (
                <Typography key={targetKey(target.user_id, target.day_of_week)} variant="caption" color="text.secondary" display="block">
                  {target.employee_name} · {target.day_label}: {target.reason}
                </Typography>
              ))}
              {unresolved.map((target) => (
                <Box key={targetKey(target.user_id, target.day_of_week)} sx={{ mt: 0.75 }}>
                  <Typography variant="body2" fontWeight={700}>
                    {target.employee_name} · {target.day_label}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {target.reason}
                  </Typography>
                  <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
                    {(target.choices || []).map((choice) => (
                      <Chip
                        key={choice}
                        size="small"
                        label={
                          choice === "skip"
                            ? "Skip"
                            : choice === "copy_schedule_only"
                              ? "Copy and update scheduled names"
                              : "Copy without checklist change"
                        }
                        color={resolutions[targetKey(target.user_id, target.day_of_week)] === choice ? "primary" : "default"}
                        variant={resolutions[targetKey(target.user_id, target.day_of_week)] === choice ? "filled" : "outlined"}
                        onClick={() => setResolution(target, choice)}
                      />
                    ))}
                  </Stack>
                </Box>
              ))}
              {(preview?.targets || [])
                .flatMap((target) => target.notes || [])
                .filter((note, index, all) => all.indexOf(note) === index)
                .map((note) => (
                  <Typography key={note} variant="caption" color="text.secondary" display="block">
                    {note}
                  </Typography>
                ))}
            </Box>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          Close
        </Button>
        <Button variant="contained" onClick={handleCopy} disabled={!canCopy || saving}>
          {saving ? "Copying…" : "Copy shifts"}
        </Button>
      </DialogActions>
    </>
  );

  if (inline) {
    return (
      <Box data-testid="copy-shift-dialog" sx={{ maxWidth: 560, bgcolor: "background.paper" }}>
        {dialogBody}
      </Box>
    );
  }

  return (
    <Dialog
      open={open}
      onClose={saving ? undefined : onClose}
      maxWidth="sm"
      fullWidth
      data-testid="copy-shift-dialog"
      slotProps={{ root: { sx: { zIndex: (theme) => theme.zIndex.tooltip + 10 } } }}
    >
      {dialogBody}
    </Dialog>
  );
}
