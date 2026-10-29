import { Box, Button, Typography } from "@mui/material";
import { roleStyle, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { taskExecutionLabel, taskGroupLabel, taskTimingIssues, taskTimingLabel } from "./weeklyScheduleTaskTiming";
import { TASK_DRAG_TYPE, taskDragPayload } from "./weeklyScheduleTaskMove";

const STATUS_COLOR = {
  in_progress: "#166534",
  completed: "#0f766e",
  approved: "#0f766e",
  pending_approval: "#b45309",
  rejected: "#b91c1c",
};

/** Task card on an employee's day. Hours and attendance still come from the shift. */
export default function WeeklyScheduleResponsibilityChip({
  item,
  onClick,
  onMove,
  employeesById = null,
  scheduleEntries = [],
  draggable = false,
  dragging = false,
  onDragStart,
  onDragEnd,
  onDropOnCard,
}) {
  const style = roleStyle(item.role);
  const people = taskGroupLabel(item, employeesById);
  const timing = taskTimingLabel(item);
  const execution = taskExecutionLabel(item);
  const detail = [people, execution, timing].filter(Boolean).join(" · ");
  const warnings = taskTimingIssues(item, scheduleEntries, employeesById || {}).warnings;
  const status = item.activity_status_label;
  return (
    <Box
      data-task-card
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) return;
        event.stopPropagation();
        event.dataTransfer.setData(TASK_DRAG_TYPE, taskDragPayload(item));
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(item);
      }}
      onDragEnd={() => onDragEnd?.()}
      onDragOver={(event) => {
        if (!onDropOnCard) return;
        event.preventDefault();
        event.stopPropagation();
      }}
      onDrop={(event) => {
        if (!onDropOnCard) return;
        event.preventDefault();
        event.stopPropagation();
        onDropOnCard(event.dataTransfer.getData(TASK_DRAG_TYPE));
      }}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.(item);
      }}
      onKeyDown={(event) => {
        if (onClick && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onClick(item);
        }
      }}
      sx={{
        px: 0.75,
        py: 0.45,
        mb: 0.45,
        borderRadius: 1.25,
        border: `1px solid ${style.border}`,
        borderLeft: `4px solid ${style.accent}`,
        bgcolor: "#fffdf8",
        cursor: onClick ? "pointer" : "default",
        opacity: dragging ? 0.45 : 1,
        boxShadow: "0 1px 0 rgba(15, 23, 42, 0.04)",
      }}
    >
      <Typography variant="caption" sx={{ display: "block", fontSize: "0.68rem", fontWeight: 800, color: style.accent, lineHeight: 1.3 }}>
        {scheduleRoleLabel(item.role)}
      </Typography>
      {detail ? (
        <Typography variant="caption" sx={{ display: "block", fontSize: "0.64rem", fontWeight: 650, color: "text.primary", lineHeight: 1.3 }}>
          {detail}
        </Typography>
      ) : null}
      {status ? (
        <Typography variant="caption" sx={{ display: "block", fontSize: "0.62rem", fontWeight: 800, color: STATUS_COLOR[item.activity_status] || "text.secondary", lineHeight: 1.25 }}>
          {status}
        </Typography>
      ) : null}
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
      {onMove ? (
        <Button
          size="small"
          className="no-print"
          onClick={(event) => {
            event.stopPropagation();
            onMove(item);
          }}
          sx={{ mt: 0.25, p: 0, minWidth: 0, fontSize: "0.62rem", fontWeight: 800, textTransform: "none" }}
        >
          Edit / Move
        </Button>
      ) : null}
    </Box>
  );
}
