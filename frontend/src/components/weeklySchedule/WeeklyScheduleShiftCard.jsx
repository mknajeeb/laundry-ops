import { Box, Chip, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { parseEntryRoles, primaryRoleStyle, roleStripeGradient, ROLE_STYLES } from "./weeklyScheduleRoles";

export default function WeeklyScheduleShiftCard({
  entry,
  onEdit,
  onDelete,
  onDuplicate,
  onDragStart,
  onDragEnd,
  dragging,
  duplicating = false,
  muted = false,
  showRoleLabels = true,
  showBreakMinutes = true,
}) {
  const roles = parseEntryRoles(entry);
  const primary = primaryRoleStyle(entry);
  const hours = Number(entry.hours || 0);
  const breakMin = Number(entry.break_minutes || 0);
  const breakSuffix = showBreakMinutes && breakMin > 0 ? ` · −${breakMin}m` : "";
  const stripe = roleStripeGradient(roles);

  return (
    <Paper
      elevation={0}
      data-shift-card
      draggable={!muted}
      onDragStart={(e) => {
        if (muted) return;
        e.stopPropagation();
        e.dataTransfer.setData("text/plain", String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={(e) => {
        e.stopPropagation();
        onEdit?.(entry);
      }}
      sx={{
        position: "relative",
        pl: 1,
        pr: 0.75,
        py: 0.5,
        mb: 0.5,
        borderRadius: 1.5,
        cursor: muted ? "default" : "grab",
        border: `1px solid ${muted ? "#e8ecf0" : primary.border}`,
        bgcolor: muted ? "#f8fafc" : primary.bg,
        opacity: dragging ? 0.45 : muted ? 0.72 : 1,
        boxShadow: "none",
        overflow: "visible",
        transition: "border-color 0.12s ease, background-color 0.12s ease",
        "&:hover": muted
          ? {}
          : {
              bgcolor: primary.hoverBg,
              borderColor: primary.accent,
            },
        "&:active": muted ? {} : { cursor: "grabbing" },
        "&::before": {
          content: '""',
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          borderRadius: "6px 0 0 6px",
          background: muted ? "#cbd5e1" : stripe,
        },
      }}
    >
      <Box>
        <Typography
          variant="caption"
          fontWeight={700}
          sx={{
            color: "text.primary",
            fontSize: "0.72rem",
            lineHeight: 1.25,
            whiteSpace: "nowrap",
            display: "block",
          }}
        >
          {formatTime12(entry.start_time)} – {formatTime12(entry.end_time)}
        </Typography>
        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mt: 0.25, flexWrap: "wrap", rowGap: 0.25 }}>
          <Typography
            variant="caption"
            sx={{
              color: "text.secondary",
              fontSize: "0.68rem",
              fontWeight: 600,
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {hours.toFixed(1)}h{breakSuffix}
          </Typography>
          {showRoleLabels ? (
            <Stack direction="row" spacing={0.35} useFlexGap sx={{ flexWrap: "wrap" }}>
              {roles.map((roleKey) => {
                const style = ROLE_STYLES[roleKey] || ROLE_STYLES.fold;
                return (
                  <Chip
                    key={roleKey}
                    size="small"
                    label={style.label}
                    sx={{
                      height: 18,
                      bgcolor: style.chipBg,
                      color: style.accent,
                      border: `1px solid ${style.border}`,
                      "& .MuiChip-label": {
                        px: 0.6,
                        fontSize: "0.62rem",
                        fontWeight: 700,
                        lineHeight: 1,
                        whiteSpace: "nowrap",
                      },
                    }}
                  />
                );
              })}
            </Stack>
          ) : null}
        </Stack>
      </Box>
      {(onDuplicate || onDelete) && !muted ? (
        <Stack
          direction="row"
          spacing={0}
          justifyContent="flex-end"
          sx={{ mt: -0.1, ml: -0.25, lineHeight: 0 }}
        >
          {onDuplicate ? (
            <Tooltip title="Duplicate shift">
              <span>
                <IconButton
                  size="small"
                  aria-label="Duplicate shift"
                  disabled={duplicating}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDuplicate?.(entry);
                  }}
                  sx={{ p: 0.15, opacity: 0.55, "&:hover": { opacity: 1 } }}
                >
                  <ContentCopyOutlinedIcon sx={{ fontSize: 13 }} />
                </IconButton>
              </span>
            </Tooltip>
          ) : null}
          {onDelete ? (
            <Tooltip title="Delete shift">
              <IconButton
                size="small"
                aria-label="Delete shift"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete?.(entry);
                }}
                sx={{ p: 0.15, opacity: 0.55, "&:hover": { opacity: 1 } }}
              >
                <DeleteOutlineIcon sx={{ fontSize: 13 }} />
              </IconButton>
            </Tooltip>
          ) : null}
        </Stack>
      ) : null}
    </Paper>
  );
}
