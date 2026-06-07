import { useMemo } from "react";
import { Chip, Stack, Typography } from "@mui/material";
import {
  addDaysYmd,
  businessTodayYmd,
  formatDateShortLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../../utils/businessTime";
import PlanningDatePicker from "./PlanningDatePicker";

function presetRange(preset, weekStartsOn = 0) {
  const today = businessTodayYmd();
  const tomorrow = addDaysYmd(today, 1);
  const thisWeekStart = weekStartFromDate(today, weekStartsOn);
  const thisWeekEnd = weekEndFromStart(thisWeekStart);
  const nextWeekStart = addDaysYmd(thisWeekStart, 7);
  const nextWeekEnd = weekEndFromStart(nextWeekStart);

  switch (preset) {
    case "today":
      return { start: today, end: today };
    case "tomorrow":
      return { start: tomorrow, end: tomorrow };
    case "this_week":
      return { start: thisWeekStart, end: thisWeekEnd };
    case "next_week":
      return { start: nextWeekStart, end: nextWeekEnd };
    default:
      return null;
  }
}

export default function PlanningDateRangePicker({
  start,
  end,
  onChange,
  weekStartsOn = 0,
  startLabel = "From",
  endLabel = "To",
}) {
  const presets = useMemo(
    () => [
      { id: "today", label: "Today" },
      { id: "tomorrow", label: "Tomorrow" },
      { id: "this_week", label: "This week" },
      { id: "next_week", label: "Next week" },
    ],
    [],
  );

  const applyPreset = (id) => {
    const r = presetRange(id, weekStartsOn);
    if (r) onChange?.(r);
  };

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
        {presets.map((p) => (
          <Chip
            key={p.id}
            label={p.label}
            clickable
            onClick={() => applyPreset(p.id)}
            sx={{ minHeight: 36, fontWeight: 600 }}
          />
        ))}
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <PlanningDatePicker label={startLabel} value={start} onChange={(v) => onChange?.({ start: v, end })} />
        <PlanningDatePicker label={endLabel} value={end} onChange={(v) => onChange?.({ start, end: v })} />
      </Stack>
      {start && end ? (
        <Typography variant="caption" color="text.secondary">
          {formatDateShortLabel(start)} – {formatDateShortLabel(end)}
        </Typography>
      ) : null}
    </Stack>
  );
}
