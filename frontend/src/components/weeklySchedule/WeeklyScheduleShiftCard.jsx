import { Box, Chip, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { parseEntryRoles, primaryRoleStyle, ROLE_STYLES } from "./weeklyScheduleRoles";

export default function WeeklyScheduleShiftCard({
  entry,
  onEdit,
  onDelete,
  onDuplicate,
  onDragStart,
  onDragEnd,
  dragging,
  muted = false,
  showRoleLabels = true,
  showBreakMinutes = true,
}) {
  const roles = parseEntryRoles(entry);
  const primary = primaryRoleStyle(entry);
  const hours = Number(entry.hours || 0);
  const breakMin = Number(entry.break_minutes || 0);

  return (
    <Paper
      elevation={0}
      draggable={!muted}
      onDragStart={(e) => {
        if (muted) return;
        e.dataTransfer.setData("text/plain", String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={() => onEdit?.(entry)}
      sx={{
        p: 1,
        mb: 0.75,
        borderRadius: 2.5,
        cursor: muted ? "default" : "grab",
        border: `1px solid ${muted ? "divider" : primary.border}`,
        borderLeft: `4px solid ${muted ? "divider" : primary.accent}`,
        bgcolor: muted ? "action.hover" : primary.bg,
        background: muted ? undefined : primary.gradient || primary.bg,
        opacity: dragging ? 0.45 : muted ? 0.72 : 1,
        boxShadow: muted ? "none" : "0 3px 12px rgba(15, 23, 42, 0.08)",
        transition: "box-shadow 0.15s ease, transform 0.12s ease",
        "&:hover": muted
          ? {}
          : {
              boxShadow: "0 6px 18px rgba(15, 23, 42, 0.1)",
              transform: "translateY(-1px)",
            },
      }}
    >
      <Stack direction="row" alignItems="flex-start" spacing={0.5}>
        <DragIndicatorIcon sx={{ fontSize: 16, color: "text.disabled", mt: 0.25 }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ color: primary.accent, lineHeight: 1.3, fontSize: "0.78rem" }}>
            {formatTime12(entry.start_time)} – {formatTime12(entry.end_time)}
          </Typography>
          <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 0.35 }}>
            {showRoleLabels
              ? roles.map((roleKey) => {
                  const style = ROLE_STYLES[roleKey] || ROLE_STYLES.fold;
                  return (
                    <Chip
                      key={roleKey}
                      size="small"
                      label={style.label}
                      sx={{
                        height: 18,
                        fontSize: "0.62rem",
                        fontWeight: 700,
                        bgcolor: "#fff",
                        color: style.accent,
                        border: `1px solid ${style.border}`,
                      }}
                    />
                  );
                })
              : null}
            <Typography variant="caption" color="text.secondary" fontWeight={600}>
              {hours.toFixed(1)}h
              {showBreakMinutes && breakMin > 0 ? ` (−${breakMin}m break)` : ""}
            </Typography>
          </Stack>
        </Box>
        <Stack direction="row" spacing={0}>
          <Tooltip title="Duplicate shift">
            <IconButton
              size="small"
              aria-label="Duplicate shift"
              onClick={(e) => {
                e.stopPropagation();
                onDuplicate?.(entry);
              }}
            >
              <ContentCopyOutlinedIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete shift">
            <IconButton
              size="small"
              aria-label="Delete shift"
              onClick={(e) => {
                e.stopPropagation();
                onDelete?.(entry);
              }}
            >
              <DeleteOutlineIcon sx={{ fontSize: 15 }} />
            </IconButton>
          </Tooltip>
        </Stack>
      </Stack>
    </Paper>
  );
}
