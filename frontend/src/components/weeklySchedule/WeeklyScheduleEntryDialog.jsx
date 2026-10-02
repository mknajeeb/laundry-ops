import React, { useEffect, useMemo, useState } from "react";
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
  IconButton,
  InputLabel,
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
import { entryRoleAssignments, scheduleRoleCatalog, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND } from "./weeklyScheduleTimeBlocks";

let rowSeq = 0;
function makeRow(partial = {}) {
  rowSeq += 1;
  return { id: rowSeq, role: "", fullShift: true, start: "", end: "", remarks: "", ...partial };
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
  const keepSet = new Set(keep.filter(Boolean));
  return catalog
    .filter((role) => {
      const matchesKind = timed ? role.uses_time_slots !== false : role.uses_time_slots === false;
      return (matchesKind && role.active !== false) || keepSet.has(role.code);
    })
    .map((role) => ({
      value: role.code,
      label: role.active === false ? `${role.name} (inactive)` : role.name,
      remarksEnabled: Boolean(role.remarks_enabled),
    }));
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
  scheduleEndTimeEnabled = true,
  shiftCategoryChoices = null,
  categoryLabel = (value) => value,
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
  const [breakMinutes, setBreakMinutes] = useState(0);
  const [respRole, setRespRole] = useState("");
  const [respRemarks, setRespRemarks] = useState("");

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
      setDayOfWeek(responsibility.day_of_week);
      setRespRole(responsibility.role);
      setRespRemarks(responsibility.remarks || "");
      return;
    }
    if (entry) {
      setKind(ASSIGNMENT_KIND.SHIFT);
      setUserId(entry.user_id);
      setDayOfWeek(entry.day_of_week);
      setRows(rowsFromEntry(entry));
      setStartTime(entry.start_time || "09:00");
      setEndTime(entry.end_time || "16:00");
      setBreakMinutes(entry.break_minutes || 0);
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
    setBreakMinutes(0);
    setRespRole(kindForRole === ASSIGNMENT_KIND.RESPONSIBILITY && defaultRole ? defaultRole : untimedOptions[0]?.value || "");
    setRespRemarks("");
  }, [open, entry, responsibility, defaultUserId, defaultDay, defaultKind, defaultRole, defaultStartTime, defaultEndTime]); // eslint-disable-line react-hooks/exhaustive-deps

  const isShift = kind === ASSIGNMENT_KIND.SHIFT;
  const canSplit = scheduleEndTimeEnabled;

  const updateRow = (id, patch) => setRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  const removeRow = (id) => setRows((prev) => prev.filter((row) => row.id !== id));

  const canSave = useMemo(() => {
    if (!userId) return false;
    if (!isShift) return Boolean(respRole);
    if (!startTime || (scheduleEndTimeEnabled && !endTime)) return false;
    return rows.every((row) => row.role && (row.fullShift || !canSplit || (row.start && row.end)));
  }, [userId, isShift, respRole, startTime, endTime, rows, scheduleEndTimeEnabled, canSplit]);

  const handleSubmit = () => {
    if (!canSave) return;
    if (!isShift) {
      onSave({
        kind: ASSIGNMENT_KIND.RESPONSIBILITY,
        user_id: Number(userId),
        day_of_week: Number(dayOfWeek),
        role: respRole,
        remarks: respRemarks.trim() || null,
      });
      return;
    }
    onSave({
      kind: ASSIGNMENT_KIND.SHIFT,
      user_id: Number(userId),
      day_of_week: Number(dayOfWeek),
      ...(!isEdit && category ? { employer_affiliation: category } : {}),
      start_time: startTime,
      ...(scheduleEndTimeEnabled
        ? { end_time: endTime, break_minutes: breakMinutes }
        : { end_time: startTime, break_minutes: 0 }),
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
    });
  };

  const showEmployeePicker = Array.isArray(employees) && !isEdit;
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
              onChange={(_, next) => next && setKind(next)}
              sx={{ "& .MuiToggleButton-root": { textTransform: "none", fontWeight: 700, px: 1.5 } }}
            >
              <ToggleButton value={ASSIGNMENT_KIND.SHIFT}>Shift (timed roles)</ToggleButton>
              <ToggleButton value={ASSIGNMENT_KIND.RESPONSIBILITY}>Task (no times)</ToggleButton>
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
                breakMinutes={breakMinutes}
                onStartChange={setStartTime}
                onEndChange={setEndTime}
                onBreakChange={scheduleEndTimeEnabled ? setBreakMinutes : undefined}
                endTimeEnabled={scheduleEndTimeEnabled}
                overnightEnabled
              />
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
            </>
          ) : (
            <>
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
              <Typography variant="caption" color="text.secondary">
                {scheduleRoleLabel(respRole) || "This task"} is assigned to the employee for the whole day. Tasks have
                no start or end time, add no scheduled hours, and create no attendance window. They can sit alongside
                a shift.
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
