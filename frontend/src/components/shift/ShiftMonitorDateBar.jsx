import { Box, Collapse, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import {
  last30DaysRange,
  last7DaysRange,
  todayRange,
  yesterdayRange,
} from "../../utils/foldingDateRange";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "last7", label: "Last 7 Days" },
  { id: "last30", label: "Last 30 Days" },
  { id: "custom", label: "Custom" },
];

function rangeForPreset(preset) {
  if (preset === "today") return todayRange();
  if (preset === "yesterday") return yesterdayRange();
  if (preset === "last7") return last7DaysRange();
  if (preset === "last30") return last30DaysRange();
  return null;
}

/** Compact segmented date control for Shift Monitor. */
export default function ShiftMonitorDateBar({
  preset,
  onPresetChange,
  dateStart,
  dateEnd,
  onDateStartChange,
  onDateEndChange,
  onApply,
  loading,
}) {
  const handlePreset = (_, value) => {
    if (!value) return;
    onPresetChange(value);
    const range = rangeForPreset(value);
    if (range) {
      onDateStartChange(range.start);
      onDateEndChange(range.end);
      onApply?.({ start: range.start, end: range.end });
    }
  };

  return (
    <Box
      sx={{
        p: 1,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
      }}
    >
      <ToggleButtonGroup
        exclusive
        size="small"
        value={preset}
        onChange={handlePreset}
        sx={{
          flexWrap: "wrap",
          gap: 0.5,
          "& .MuiToggleButtonGroup-grouped": {
            border: "1px solid",
            borderColor: "divider",
            borderRadius: "8px !important",
            mx: 0.25,
            my: 0.25,
            px: 1.25,
            py: 0.5,
            fontSize: "0.8125rem",
            fontWeight: 600,
            textTransform: "none",
            lineHeight: 1.3,
            "&.Mui-selected": {
              bgcolor: VEEWASH_DASHBOARD.primaryBlue,
              color: "#fff",
              borderColor: VEEWASH_DASHBOARD.primaryBlue,
              "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
            },
          },
        }}
      >
        {PRESETS.map(({ id, label }) => (
          <ToggleButton key={id} value={id} disabled={loading}>
            {label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      <Collapse in={preset === "custom"}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1, pt: 1, borderTop: "1px solid", borderColor: "divider" }}>
          <TextField
            type="date"
            size="small"
            label="From"
            value={dateStart}
            onChange={(e) => onDateStartChange(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
          />
          <TextField
            type="date"
            size="small"
            label="To"
            value={dateEnd}
            onChange={(e) => onDateEndChange(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
            Custom ranges use Reporting Mode
          </Typography>
        </Stack>
      </Collapse>
    </Box>
  );
}
