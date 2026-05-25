import { FormControl, InputLabel, MenuItem, Select, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { defaultWeekRange, monthRange, todayRange } from "../../utils/foldingDateRange";

const DATE_FIELD_OPTIONS = [
  { value: "folding_work_date", label: "Folding work date" },
  { value: "date_clean", label: "Cleaning / processing date" },
  { value: "completed_at", label: "Completed date" },
];

export default function FoldingDateRangeFilter({
  preset,
  onPresetChange,
  dateStart,
  dateEnd,
  onDateStartChange,
  onDateEndChange,
  dateField,
  onDateFieldChange,
  showDateField = true,
}) {
  const applyPreset = (p) => {
    onPresetChange(p);
    if (p === "today") {
      const { start, end } = todayRange();
      onDateStartChange(start);
      onDateEndChange(end);
    } else if (p === "month") {
      const { start, end } = monthRange();
      onDateStartChange(start);
      onDateEndChange(end);
    } else if (p === "week") {
      const { start, end } = defaultWeekRange();
      onDateStartChange(start);
      onDateEndChange(end);
    }
  };

  return (
    <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} flexWrap="wrap" useFlexGap>
      <ToggleButtonGroup size="small" exclusive value={preset} onChange={(_, v) => v && applyPreset(v)}>
        <ToggleButton value="today">Today</ToggleButton>
        <ToggleButton value="week">This week</ToggleButton>
        <ToggleButton value="month">This month</ToggleButton>
        <ToggleButton value="custom">Custom range</ToggleButton>
      </ToggleButtonGroup>
      <TextField
        type="date"
        size="small"
        label="Start date"
        value={dateStart}
        onChange={(e) => {
          onPresetChange("custom");
          onDateStartChange(e.target.value);
        }}
        InputLabelProps={{ shrink: true }}
      />
      <TextField
        type="date"
        size="small"
        label="End date"
        value={dateEnd}
        onChange={(e) => {
          onPresetChange("custom");
          onDateEndChange(e.target.value);
        }}
        InputLabelProps={{ shrink: true }}
      />
      {showDateField ? (
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel>Date meaning</InputLabel>
          <Select
            label="Date meaning"
            value={dateField}
            onChange={(e) => onDateFieldChange(e.target.value)}
          >
            {DATE_FIELD_OPTIONS.map((o) => (
              <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
      ) : null}
      {dateStart && dateEnd && dateStart === dateEnd ? (
        <Typography variant="caption" color="text.secondary">Single-day view</Typography>
      ) : null}
    </Stack>
  );
}
