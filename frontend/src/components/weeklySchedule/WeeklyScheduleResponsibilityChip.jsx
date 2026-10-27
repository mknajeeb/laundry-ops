import { Box, Typography } from "@mui/material";
import { roleStyle, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { taskGroupLabel, taskTimingIssues, taskTimingLabel } from "./weeklyScheduleTaskTiming";

/** Task on an employee's day. Hours and attendance still come from the shift. */
export default function WeeklyScheduleResponsibilityChip({ item, onClick, employeesById = null, scheduleEntries = [] }) {
  const style = roleStyle(item.role);
  const people = taskGroupLabel(item, employeesById);
  const timing = taskTimingLabel(item);
  const detail = [people, timing].filter(Boolean).join(" · ");
  const warnings = taskTimingIssues(item, scheduleEntries, employeesById || {}).warnings;
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
        {detail ? ` · ${detail}` : ""}
        <Typography component="span" sx={{ ml: 0.5, fontSize: "0.6rem", fontWeight: 600, color: "text.secondary" }}>
          task
        </Typography>
      </Typography>
      {warnings.map((warning) => (
        <Typography key={warning} variant="caption" sx={{ display: "block", fontSize: "0.6rem", color: "#b45309", fontWeight: 700, lineHeight: 1.25 }}>
          {warning}
        </Typography>
      ))}
      {item.remarks ? (
        <Typography variant="caption" sx={{ display: "block", fontSize: "0.62rem", color: "text.secondary", lineHeight: 1.25, wordBreak: "break-word" }}>
          {item.remarks}
        </Typography>
      ) : null}
    </Box>
  );
}
