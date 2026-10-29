import { useEffect, useState } from "react";
import {
  Alert,
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
  TextField,
  Typography,
} from "@mui/material";
import { DAY_LABELS, formatDayDate } from "./weeklyScheduleDates";
import { scheduleEmployeeName, taskGroupLabel } from "./weeklyScheduleTaskTiming";
import { scheduleRoleLabel } from "./weeklyScheduleRoles";
import { isSharedAssignment, unscheduledNames } from "./weeklyScheduleTaskMove";

const LOCKED = new Set(["in_progress", "completed", "approved", "pending_approval", "rejected"]);

export default function TaskMoveDialog({
  open,
  item,
  weekStart,
  employees = [],
  employeesById = {},
  scheduleEntries = [],
  initialDay = null,
  initialUserId = null,
  saving = false,
  error = "",
  onClose,
  onConfirm,
}) {
  const shared = isSharedAssignment(item);
  const [day, setDay] = useState(0);
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmUnscheduled, setConfirmUnscheduled] = useState(false);

  useEffect(() => {
    if (!open || !item) return;
    setDay(initialDay == null ? Number(item.day_of_week) : Number(initialDay));
    setUserId(initialUserId == null ? Number(item.user_id) : Number(initialUserId));
    setReason("");
    setConfirmUnscheduled(false);
  }, [open, item, initialDay, initialUserId]);

  if (!item) return null;
  const locked = LOCKED.has(item.activity_status);
  const targetUsers = shared ? item.user_ids || [] : [Number(userId)];
  const missing = unscheduledNames(scheduleEntries, targetUsers, day, (id) => scheduleEmployeeName(employeesById, id));
  const people = taskGroupLabel(item, employeesById);
  const unchanged = shared
    ? Number(day) === Number(item.day_of_week)
    : Number(day) === Number(item.day_of_week) && Number(userId) === Number(item.user_id);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{shared ? "Move shared assignment" : "Move task"}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 800 }}>
            {scheduleRoleLabel(item.role)}
            {people ? ` · ${people}` : ""}
          </Typography>
          {shared ? (
            <Alert severity="info">
              This moves the whole shared assignment. Participants stay together. Use Edit Participants on the card to change who is assigned.
            </Alert>
          ) : (
            <FormControl size="small" fullWidth>
              <InputLabel>Employee</InputLabel>
              <Select label="Employee" value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
                {employees.map((employee) => (
                  <MenuItem key={employee.user_id} value={Number(employee.user_id)}>
                    {employee.display_name || `User #${employee.user_id}`}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <FormControl size="small" fullWidth>
            <InputLabel>Day</InputLabel>
            <Select label="Day" value={day} onChange={(e) => setDay(Number(e.target.value))}>
              {DAY_LABELS.map((label, dow) => (
                <MenuItem key={label} value={dow}>
                  {`${label}${weekStart ? ` · ${formatDayDate(weekStart, dow)}` : ""}`}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {missing.length ? (
            <Alert severity="warning">
              {`${missing.join(", ")} is not scheduled on that day. The task still adds no labor hours.`}
            </Alert>
          ) : null}
          {locked ? (
            <>
              <Alert severity="warning">
                This assignment has already started or been completed. Moving it needs a correction reason. Timers and verification history are kept.
              </Alert>
              <TextField
                size="small"
                fullWidth
                label="Correction reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                inputProps={{ maxLength: 255 }}
              />
            </>
          ) : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={saving || unchanged || (locked && reason.trim().length < 3)}
          onClick={() => {
            if (missing.length && !confirmUnscheduled) {
              setConfirmUnscheduled(true);
              return;
            }
            onConfirm({
              day_of_week: day,
              user_id: shared ? undefined : Number(userId),
              confirm_unscheduled: missing.length > 0,
              confirm_active_change: locked,
              correction_reason: reason.trim() || undefined,
            });
          }}
        >
          {missing.length && !confirmUnscheduled ? "Move anyway" : saving ? "Moving…" : "Move"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
