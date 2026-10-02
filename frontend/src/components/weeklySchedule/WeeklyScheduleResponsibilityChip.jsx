import { Box, Typography } from "@mui/material";
import { roleStyle, scheduleRoleLabel } from "./weeklyScheduleRoles";

/** Task (assigned by day, no time slots) — no hours, no clock-in window. */
export default function WeeklyScheduleResponsibilityChip({ item, onClick }) {
  const style = roleStyle(item.role);
  return (
    <Box
      data-shift-card
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.(item);
      }}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick(item);
        }
      }}
      sx={{
        px: 0.75,
        py: 0.3,
        mb: 0.35,
        borderRadius: 1.25,
        border: `1px dashed ${style.border}`,
        bgcolor: style.chipBg,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <Typography variant="caption" sx={{ display: "block", fontSize: "0.66rem", fontWeight: 800, color: style.accent, lineHeight: 1.25 }}>
        {scheduleRoleLabel(item.role)}
        <Typography component="span" sx={{ ml: 0.5, fontSize: "0.6rem", fontWeight: 600, color: "text.secondary" }}>
          task
        </Typography>
      </Typography>
      {item.remarks ? (
        <Typography variant="caption" sx={{ display: "block", fontSize: "0.62rem", color: "text.secondary", lineHeight: 1.25, wordBreak: "break-word" }}>
          {item.remarks}
        </Typography>
      ) : null}
    </Box>
  );
}
