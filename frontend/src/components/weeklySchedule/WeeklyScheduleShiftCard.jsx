import { Box, Chip, IconButton, Paper, Stack, Typography } from "@mui/material";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const ROLE_STYLES = {
  folder: {
    accent: VEEWASH_DASHBOARD.primaryBlue,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
    label: "Folder",
  },
  operator: {
    accent: VEEWASH_DASHBOARD.teal,
    bg: VEEWASH_DASHBOARD.tealLight,
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Operator",
  },
};

export default function WeeklyScheduleShiftCard({
  entry,
  onEdit,
  onDelete,
  onDuplicate,
  onDragStart,
  onDragEnd,
  dragging,
}) {
  const role = ROLE_STYLES[entry.role] || ROLE_STYLES.folder;
  const hours = Number(entry.hours || 0);

  return (
    <Paper
      elevation={0}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={() => onEdit?.(entry)}
      sx={{
        p: 1,
        mb: 0.75,
        borderRadius: 2,
        cursor: "grab",
        border: `1px solid ${role.border}`,
        bgcolor: role.bg,
        opacity: dragging ? 0.45 : 1,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        transition: "box-shadow 0.15s ease, border-color 0.15s ease",
        "&:hover": {
          borderColor: role.accent,
          boxShadow: "0 4px 14px rgba(0, 151, 178, 0.12)",
        },
      }}
    >
      <Stack direction="row" alignItems="flex-start" spacing={0.5}>
        <DragIndicatorIcon sx={{ fontSize: 16, color: "text.disabled", mt: 0.25 }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ color: role.accent }}>
            {formatTime12(entry.start_time)} – {formatTime12(entry.end_time)}
          </Typography>
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.25 }}>
            <Chip
              size="small"
              label={role.label}
              sx={{
                height: 18,
                fontSize: "0.65rem",
                fontWeight: 700,
                bgcolor: "#fff",
                color: role.accent,
                border: `1px solid ${role.border}`,
              }}
            />
            <Typography variant="caption" color="text.secondary">
              {hours.toFixed(1)}h
            </Typography>
          </Stack>
        </Box>
        <Stack direction="row" spacing={0}>
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
        </Stack>
      </Stack>
    </Paper>
  );
}
