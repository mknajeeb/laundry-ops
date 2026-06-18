import React, { useEffect, useMemo, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import ShiftScheduleTimeFields from "../datetime/ShiftScheduleTimeFields";
import { parseEntryRoles, WEEKLY_SCHEDULE_ROLES } from "./weeklyScheduleRoles";

export default function WeeklyScheduleEntryDialog({
  open,
  onClose,
  onSave,
  saving,
  entry,
  defaultUserId,
  defaultDay,
}) {
  const isEdit = Boolean(entry?.id);
  const [userId, setUserId] = useState(defaultUserId || "");
  const [dayOfWeek, setDayOfWeek] = useState(defaultDay ?? 0);
  const [roles, setRoles] = useState(["fold"]);
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("16:00");
  const [breakMinutes, setBreakMinutes] = useState(0);

  useEffect(() => {
    if (!open) return;
    if (entry) {
      setUserId(entry.user_id);
      setDayOfWeek(entry.day_of_week);
      setRoles(parseEntryRoles(entry).length ? parseEntryRoles(entry) : ["fold"]);
      setStartTime(entry.start_time || "09:00");
      setEndTime(entry.end_time || "16:00");
      setBreakMinutes(entry.break_minutes || 0);
      return;
    }
    setUserId(defaultUserId || "");
    setDayOfWeek(defaultDay ?? 0);
    setRoles(["fold"]);
    setStartTime("09:00");
    setEndTime("16:00");
    setBreakMinutes(0);
  }, [open, entry, defaultUserId, defaultDay]);

  const canSave = useMemo(
    () => Boolean(userId) && startTime && endTime && roles.length > 0,
    [userId, startTime, endTime, roles],
  );

  const handleSubmit = () => {
    if (!canSave) return;
    onSave({
      user_id: Number(userId),
      day_of_week: Number(dayOfWeek),
      roles,
      start_time: startTime,
      end_time: endTime,
      break_minutes: breakMinutes,
    });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? "Edit shift" : "Add shift"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <FormControl size="small" fullWidth>
            <InputLabel>Roles</InputLabel>
            <Select
              label="Roles"
              multiple
              value={roles}
              onChange={(e) => {
                const next = typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value;
                setRoles(next.length ? next : ["fold"]);
              }}
              renderValue={(selected) =>
                selected
                  .map((r) => WEEKLY_SCHEDULE_ROLES.find((opt) => opt.value === r)?.label || r)
                  .join(", ")
              }
            >
              {WEEKLY_SCHEDULE_ROLES.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Typography variant="caption" color="text.secondary">
            Select one or more roles for this shift (e.g. Wash + Sort + Fold).
          </Typography>
          <ShiftScheduleTimeFields
            startTime={startTime}
            endTime={endTime}
            breakMinutes={breakMinutes}
            onStartChange={setStartTime}
            onEndChange={setEndTime}
            onBreakChange={setBreakMinutes}
            overnightEnabled
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!canSave || saving} onClick={handleSubmit}>
          {saving ? "Saving…" : isEdit ? "Save" : "Add shift"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
