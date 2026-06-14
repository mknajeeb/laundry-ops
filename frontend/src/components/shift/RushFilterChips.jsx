import { Chip, Stack } from "@mui/material";
import { RUSH_FILTERS } from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export default function RushFilterChips({ value, onChange, sx, disabled = false }) {
  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={sx}>
      {RUSH_FILTERS.map(({ id, label }) => {
        const selected = value === id;
        return (
          <Chip
            key={id}
            size="medium"
            label={label}
            disabled={disabled}
            onClick={() => !disabled && onChange(id)}
            sx={{
              fontWeight: 700,
              borderRadius: 2,
              px: 0.5,
              minHeight: 36,
              bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlue : "transparent",
              color: selected ? "#fff" : "text.primary",
              border: "2px solid",
              borderColor: selected ? VEEWASH_DASHBOARD.primaryBlue : "divider",
              "&:hover": {
                bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlueDark : VEEWASH_DASHBOARD.primaryBlueLight,
              },
            }}
            variant={selected ? "filled" : "outlined"}
          />
        );
      })}
    </Stack>
  );
}
