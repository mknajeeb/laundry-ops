import { Chip, Stack } from "@mui/material";
import { SERVICE_FILTERS } from "../../utils/shiftMonitorHelpers";

export default function ServiceFilterChips({ value, onChange, sx, disabled = false }) {
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={sx}>
      {SERVICE_FILTERS.map(({ id, label }) => (
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
