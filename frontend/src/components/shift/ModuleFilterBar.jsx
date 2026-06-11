import { Box, Stack, Typography } from "@mui/material";
import RushFilterChips from "./RushFilterChips";
import { SERVICE_FILTERS } from "../../utils/shiftMonitorHelpers";

function ServiceFilterChips({ value, onChange, disabled }) {
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
      {SERVICE_FILTERS.map((f) => (
        <Box
          key={f.id}
          component="button"
          type="button"
          disabled={disabled}
          onClick={() => onChange(f.id)}
          sx={{
            border: "1px solid",
            borderColor: value === f.id ? "primary.main" : "divider",
            bgcolor: value === f.id ? "primary.main" : "background.paper",
            color: value === f.id ? "primary.contrastText" : "text.primary",
            borderRadius: 999,
            px: 1.25,
            py: 0.35,
            fontSize: 12,
            fontWeight: 700,
            cursor: disabled ? "not-allowed" : "pointer",
            opacity: disabled ? 0.5 : 1,
          }}
        >
          {f.label}
        </Box>
      ))}
    </Stack>
  );
}

export default function ModuleFilterBar({
  rushFilter,
  serviceFilter,
  onRushChange,
  onServiceChange,
  disabled = false,
}) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }} flexWrap="wrap">
      <Box>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
          Rush
        </Typography>
        <RushFilterChips value={rushFilter} onChange={onRushChange} disabled={disabled} />
      </Box>
      <Box>
        <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
          Service
        </Typography>
        <ServiceFilterChips value={serviceFilter} onChange={onServiceChange} disabled={disabled} />
      </Box>
    </Stack>
  );
}
