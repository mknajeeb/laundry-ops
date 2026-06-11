import { Chip, Stack } from "@mui/material";
import { RUSH_FILTERS } from "../../utils/shiftMonitorHelpers";

export default function RushFilterChips({ value, onChange, sx, disabled = false }) {
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={sx}>
      {RUSH_FILTERS.map(({ id, label }) => (
        <Chip
          key={id}
          size="small"
          label={label}
          color={value === id ? "primary" : "default"}
          variant={value === id ? "filled" : "outlined"}
          disabled={disabled}
          onClick={() => !disabled && onChange(id)}
        />
      ))}
    </Stack>
  );
}
