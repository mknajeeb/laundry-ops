import React, { useMemo } from "react";
import { Alert, Box, Button, IconButton, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import ScheduleIcon from "@mui/icons-material/Schedule";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import {
  MAX_BREAK_SLOTS,
  entryBreakBreakdown,
  entryShiftInterval,
  formatHoursBreakdown,
  makeBreakSlot,
  validateBreakSlots,
} from "./weeklyScheduleRoles";

function toHm(minutes) {
  const value = ((minutes % 1440) + 1440) % 1440;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

/** A break of `minutes` centred in the shift, on a quarter hour. */
function suggestedSlot(startTime, endTime, minutes) {
  const shift = entryShiftInterval({ start_time: startTime, end_time: endTime });
  if (!shift) return { start_time: "", end_time: "" };
  const length = Math.max(5, Math.min(minutes, shift.end - shift.start));
  const centred = shift.start + Math.floor((shift.end - shift.start - length) / 2);
  const start = Math.max(shift.start, Math.min(shift.end - length, Math.round(centred / 15) * 15));
  return { start_time: toHm(start), end_time: toHm(start + length) };
}

function slotMinutes(slot) {
  const start = parseTimeToMinutes(normalizeTimeHm(slot.start_time));
  const end = parseTimeToMinutes(normalizeTimeHm(slot.end_time));
  if (start == null || end == null || start === end) return 0;
  return end > start ? end - start : end + 1440 - start;
}

/**
 * Planned breaks for one shift: timed breaks plus an optional break without a time ("Not scheduled").
 * "Set time" turns the untimed break into a timed one of the same length, so the deduction is replaced
 * rather than added to. Planned breaks never touch attendance or payroll breaks.
 */
export default function WeeklyScheduleBreakFields({ startTime, endTime, slots, onSlotsChange, unscheduledMinutes, onUnscheduledChange }) {
  const error = useMemo(() => validateBreakSlots(startTime, endTime, slots), [startTime, endTime, slots]);
  const breakdown = useMemo(() => {
    const timed = slots.reduce((sum, slot) => sum + slotMinutes(slot), 0);
    const parts = entryBreakBreakdown({
      start_time: startTime,
      end_time: endTime,
      break_minutes: timed + Math.max(0, Number(unscheduledMinutes || 0)),
      break_slots: slots,
    });
    return {
      gross: parts.grossMinutes / 60,
      breakHours: parts.breakMinutes / 60,
      net: (parts.grossMinutes - parts.breakMinutes) / 60,
    };
  }, [startTime, endTime, slots, unscheduledMinutes]);

  const update = (id, patch) => onSlotsChange(slots.map((slot) => (slot.id === id ? { ...slot, ...patch } : slot)));
  const scheduleUntimed = () => {
    onSlotsChange([...slots, makeBreakSlot(suggestedSlot(startTime, endTime, Number(unscheduledMinutes || 0)))]);
    onUnscheduledChange(0);
  };

  return (
    <Box sx={{ border: "1px solid #dbe4ea", borderRadius: 1.5, p: 1.25, bgcolor: "#f8fafc" }}>
      <Typography variant="subtitle2" fontWeight={800}>
        Planned breaks
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        Breaks with a time are taken out of role coverage for that time. Planned breaks change scheduled hours
        only — not attendance, clock-in, or payroll.
      </Typography>
      <Stack spacing={1}>
        {slots.map((slot, index) => (
          <Stack key={slot.id} direction="row" spacing={1} alignItems="center">
            <Typography variant="caption" fontWeight={700} sx={{ width: 56, flexShrink: 0 }}>
              Break {index + 1}
            </Typography>
            <PlanningTimePicker label="Start" value={slot.start_time} onChange={(v) => update(slot.id, { start_time: v })} />
            <PlanningTimePicker label="End" value={slot.end_time} onChange={(v) => update(slot.id, { end_time: v })} />
            <IconButton size="small" aria-label="Remove break" onClick={() => onSlotsChange(slots.filter((s) => s.id !== slot.id))}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Stack>
        ))}
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            label="Break without a time (min)"
            type="number"
            size="small"
            inputProps={{ min: 0, step: 5 }}
            value={unscheduledMinutes ?? 0}
            onChange={(e) => onUnscheduledChange(Math.max(0, Number(e.target.value) || 0))}
            sx={{ maxWidth: 210 }}
          />
          {Number(unscheduledMinutes) > 0 ? (
            <>
              <Typography variant="caption" color="text.secondary">
                Not scheduled
              </Typography>
              <Button
                size="small"
                startIcon={<ScheduleIcon />}
                onClick={scheduleUntimed}
                disabled={slots.length >= MAX_BREAK_SLOTS || !startTime || !endTime}
                sx={{ fontWeight: 700 }}
              >
                Set time
              </Button>
            </>
          ) : null}
        </Stack>
      </Stack>
      <Button
        size="small"
        startIcon={<AddIcon />}
        disabled={slots.length >= MAX_BREAK_SLOTS || !startTime || !endTime}
        onClick={() => onSlotsChange([...slots, makeBreakSlot(suggestedSlot(startTime, endTime, 30))])}
        sx={{ mt: 1, fontWeight: 700 }}
      >
        Add timed break
      </Button>
      {startTime && endTime ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {formatHoursBreakdown(breakdown)} hours
        </Typography>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ py: 0.25, mt: 1 }}>
          {error}
        </Alert>
      ) : null}
    </Box>
  );
}
