import { Chip, Stack } from "@mui/material";
import { RUSH_FILTERS } from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export default function RushFilterChips({ value, onChange, sx, disabled = false }) {
  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={sx}>
      {RUSH_FILTERS.map(({ id, label }) => {
        const selected = value === id;
        const isRush = id === "rush";
        const selectedBg = isRush ? VEEWASH_DASHBOARD.rushCopper : VEEWASH_DASHBOARD.primaryBlue;
        const selectedBorder = isRush ? VEEWASH_DASHBOARD.rushCopper : VEEWASH_DASHBOARD.primaryBlue;
        const hoverBg = isRush ? "#92400e" : VEEWASH_DASHBOARD.primaryBlueDark;
        const idleHoverBg = isRush ? VEEWASH_DASHBOARD.rushBg : VEEWASH_DASHBOARD.primaryBlueLight;
        return (
          <Chip
            key={id}
            size="small"
            label={label}
            disabled={disabled}
            onClick={() => !disabled && onChange(id)}
            sx={{
              fontWeight: 600,
              borderRadius: 1.5,
              px: 0.5,
              minHeight: 30,
              fontSize: "0.8125rem",
              bgcolor: selected ? selectedBg : "transparent",
              color: selected ? "#fff" : isRush ? VEEWASH_DASHBOARD.rushCopper : "text.primary",
              border: "2px solid",
              borderColor: selected ? selectedBorder : isRush ? VEEWASH_DASHBOARD.rushBorder : "divider",
              "&:hover": {
                bgcolor: selected ? hoverBg : idleHoverBg,
              },
            }}
            variant={selected ? "filled" : "outlined"}
          />
        );
      })}
    </Stack>
  );
}
