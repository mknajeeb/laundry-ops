import { Box, Chip, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { parseEntryRoles, primaryRoleStyle, ROLE_STYLES } from "./weeklyScheduleRoles";

export default function WeeklyScheduleShiftCard({
  entry,
  onEdit,
  onDelete,
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
  const breakSuffix = showBreakMinutes && breakMin > 0 ? ` · −${breakMin}m` : "";

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
        px: 0.5,
        py: 0.35,
        mb: 0.35,
        borderRadius: 1.25,
        cursor: muted ? "default" : "grab",
        border: `1px solid ${muted ? "#e8ecf0" : primary.border}`,
        borderLeft: `3px solid ${muted ? "#cbd5e1" : primary.accent}`,
        bgcolor: muted ? "#f8fafc" : primary.bg,
        opacity: dragging ? 0.45 : muted ? 0.72 : 1,
        boxShadow: "none",
        transition: "border-color 0.12s ease, background-color 0.12s ease",
        "&:hover": muted
          ? {}
          : {
              bgcolor: "#fafbfc",
              borderColor: primary.accent,
              "& .shift-card-actions": { opacity: 1 },
            },
      }}
    >
      <Stack direction="row" alignItems="center" spacing={0.35} sx={{ minWidth: 0 }}>
        <DragIndicatorIcon sx={{ fontSize: 14, color: "text.disabled", flexShrink: 0 }} />
        <Box sx={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 0.5, flexWrap: "nowrap" }}>
          <Typography
            variant="caption"
            fontWeight={700}
            noWrap
            sx={{ color: "text.primary", fontSize: "0.7rem", lineHeight: 1.2, flexShrink: 0 }}
          >
            {formatTime12(entry.start_time)}–{formatTime12(entry.end_time)}
          </Typography>
          <Typography
            variant="caption"
            noWrap
            sx={{ color: "text.secondary", fontSize: "0.68rem", fontWeight: 600, flexShrink: 0 }}
          >
            {hours.toFixed(1)}h{breakSuffix}
          </Typography>
          {showRoleLabels ? (
            <Stack direction="row" spacing={0.35} sx={{ flexShrink: 0, ml: "auto" }}>
              {roles.map((roleKey) => {
                const style = ROLE_STYLES[roleKey] || ROLE_STYLES.fold;
                return (
                  <Chip
                    key={roleKey}
                    size="small"
                    label={style.label}
                    sx={{
                      height: 18,
                      flexShrink: 0,
                      "& .MuiChip-label": {
                        px: 0.6,
                        fontSize: "0.62rem",
                        fontWeight: 700,
                        lineHeight: 1,
                        whiteSpace: "nowrap",
                        overflow: "visible",
                      },
                      bgcolor: style.chipBg,
                      color: style.accent,
                      border: `1px solid ${style.border}`,
                    }}
                  />
                );
              })}
            </Stack>
          ) : null}
        </Box>
        {onDelete ? (
          <Tooltip title="Delete shift">
            <IconButton
              size="small"
              aria-label="Delete shift"
              className="shift-card-actions"
              onClick={(e) => {
                e.stopPropagation();
                onDelete?.(entry);
              }}
              sx={{
                p: 0.25,
                opacity: 0.55,
                flexShrink: 0,
                "&:hover": { opacity: 1 },
              }}
            >
              <DeleteOutlineIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
        ) : null}
      </Stack>
    </Paper>
  );
}
