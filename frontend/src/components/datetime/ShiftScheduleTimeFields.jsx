import { useMemo } from "react";
import { Alert, Stack, TextField, Typography } from "@mui/material";
import PlanningTimePicker from "./PlanningTimePicker";
import { formatTime12 } from "./scheduleTimeUi";
import { computeScheduledHours } from "../../payroll/schedulePlanner";
import { validateScheduleTimes } from "../../payroll/scheduleTimeValidation";

export default function ShiftScheduleTimeFields({
  startTime,
  endTime,
  breakMinutes = 0,
  onStartChange,
  onEndChange,
  onBreakChange,
  maxShiftHours,
  overnightEnabled = false,
  validationContext,
  endTimeEnabled = true,
}) {
  const grossHours = useMemo(() => {
    const st = computeScheduledHours(startTime, endTime, 0);
    return st;
  }, [startTime, endTime]);

  const netHours = useMemo(
    () => computeScheduledHours(startTime, endTime, breakMinutes),
    [startTime, endTime, breakMinutes],
  );

  const { errors, warnings } = useMemo(() => {
    if (!validationContext) return { errors: [], warnings: [] };
    return validateScheduleTimes({
      startTime,
      endTime,
      breakMinutes,
      maxShiftHours,
      overnightEnabled,
      ...validationContext,
    });
  }, [startTime, endTime, breakMinutes, maxShiftHours, overnightEnabled, validationContext]);

  const hoursLine =
    endTimeEnabled && startTime && endTime ? (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        {formatTime12(startTime)} – {formatTime12(endTime)} ={" "}
        <strong>{grossHours.toFixed(1)}</strong> scheduled hour{grossHours === 1 ? "" : "s"}
        {Number(breakMinutes) > 0 ? (
          <>
            <br />
            {grossHours.toFixed(1)} gross hours ·{" "}
            <strong>{netHours.toFixed(1)}</strong> payable after {breakMinutes} min break
          </>
        ) : null}
      </Typography>
    ) : null;

  return (
    <Stack spacing={1.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <PlanningTimePicker label="Start" value={startTime} onChange={onStartChange} />
        {endTimeEnabled ? (
          <PlanningTimePicker label="End" value={endTime} onChange={onEndChange} />
        ) : null}
      </Stack>
      {endTimeEnabled && onBreakChange ? (
        <TextField
          label="Break (minutes)"
          type="number"
          size="small"
          inputProps={{ min: 0, step: 5 }}
          value={breakMinutes ?? 0}
          onChange={(e) => onBreakChange(Number(e.target.value) || 0)}
          sx={{ maxWidth: 160 }}
        />
      ) : null}
      {!endTimeEnabled ? (
        <Typography variant="body2" color="text.secondary">
          Start time only — this shift counts as one scheduled day (hours are not calculated).
        </Typography>
      ) : null}
      {hoursLine}
      {errors.map((msg) => (
        <Alert key={msg} severity="error" sx={{ py: 0.25 }}>
          {msg}
        </Alert>
      ))}
      {warnings.map((msg) => (
        <Alert key={msg} severity="warning" sx={{ py: 0.25 }}>
          {msg}
        </Alert>
      ))}
    </Stack>
  );
}
