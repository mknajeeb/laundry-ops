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
} from "@mui/material";
import ShiftScheduleTimeFields from "../datetime/ShiftScheduleTimeFields";

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
  const [role, setRole] = useState("folder");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("16:00");
  const [breakMinutes, setBreakMinutes] = useState(0);

  useEffect(() => {
    if (!open) return;
    if (entry) {
      setUserId(entry.user_id);
      setDayOfWeek(entry.day_of_week);
      setRole(entry.role || "folder");
      setStartTime(entry.start_time || "09:00");
      setEndTime(entry.end_time || "16:00");
      setBreakMinutes(entry.break_minutes || 0);
      return;
    }
    setUserId(defaultUserId || "");
    setDayOfWeek(defaultDay ?? 0);
    setRole("folder");
    setStartTime("09:00");
    setEndTime("16:00");
    setBreakMinutes(0);
  }, [open, entry, defaultUserId, defaultDay]);

  const canSave = useMemo(
    () => Boolean(userId) && startTime && endTime,
    [userId, startTime, endTime],
  );

  const handleSubmit = () => {
    if (!canSave) return;
    onSave({
      user_id: Number(userId),
      day_of_week: Number(dayOfWeek),
      role,
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
            <InputLabel>Role</InputLabel>
            <Select label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
              <MenuItem value="folder">Folder</MenuItem>
              <MenuItem value="operator">Operator</MenuItem>
            </Select>
          </FormControl>
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
