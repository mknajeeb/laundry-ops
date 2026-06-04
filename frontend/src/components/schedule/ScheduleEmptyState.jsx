import { Box, Typography } from "@mui/material";
import { SCHEDULE_THEME } from "../../payroll/scheduleTheme";

/** Modern empty-state card for scheduling screens. */
export default function ScheduleEmptyState({ icon: Icon, title, description, action }) {
  return (
    <Box
      sx={{
        ...SCHEDULE_THEME.card,
        py: 4,
        px: 2,
        textAlign: "center",
        mb: 2,
      }}
    >
      {Icon ? <Icon sx={{ fontSize: 40, color: "text.disabled", mb: 1 }} /> : null}
      <Typography variant="subtitle1" fontWeight={700} gutterBottom>
        {title}
      </Typography>
      {description ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: action ? 2 : 0, maxWidth: 360, mx: "auto" }}>
          {description}
        </Typography>
      ) : null}
      {action || null}
    </Box>
  );
}
