import { Box, Chip, IconButton, Stack, Typography } from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { BALANCE_BADGE, formatTime12, SCHEDULE_THEME } from "../../payroll/scheduleTheme";

export default function RosterBoardCompactCard({
  entry,
  weekStats,
  onEdit,
  onRemove,
  onDuplicate,
  onAbsent,
  onReplace,
  compact,
}) {
  const balance = weekStats?.balance_label;
  const balanceStyle = balance ? BALANCE_BADGE[balance] : null;
  const ot = weekStats?.overtime_risk;
  const gaps = entry.profile_gaps || entry.warnings || [];
  const safeLabel =
    balance === "Overtime Risk" ? "OT Risk" : balance === "Heavy" ? "Heavy" : balance === "Underused" ? "Underused" : "Safe";

  return (
    <Box
      sx={{
        p: compact ? 1 : 1.25,
        borderRadius: 2,
        bgcolor: "#fff",
        border: "1px solid",
        borderColor: entry.publish_status === "draft" ? "warning.light" : "divider",
        boxShadow: "0 1px 4px rgba(15,23,42,0.06)",
        "&:hover": { borderColor: SCHEDULE_THEME.accent },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={0.5}>
        <Box sx={{ flex: 1, minWidth: 0 }} onClick={() => onEdit?.(entry)} role="button" tabIndex={0}>
          <Typography variant="body2" fontWeight={800} noWrap>
            {entry.worker_name || "Worker"}
          </Typography>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.25 }}>
            {entry.role_name ? (
              <Chip size="small" label={entry.role_name} sx={{ height: 22, fontSize: "0.7rem", fontWeight: 600 }} />
            ) : null}
            {entry.work_stream_name ? (
              <Chip
                size="small"
                variant="outlined"
                label={entry.work_stream_name}
                sx={{ height: 22, fontSize: "0.7rem" }}
              />
            ) : null}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {formatTime12(entry.start_time)}–{formatTime12(entry.end_time)} · {Number(entry.scheduled_hours || 0).toFixed(1)}h
          </Typography>
          {weekStats ? (
            <Typography variant="caption" fontWeight={600} color={ot ? "error.main" : "text.secondary"}>
              Weekly: {weekStats.scheduled_hours.toFixed(0)}h · {safeLabel}
            </Typography>
          ) : null}
          <Stack direction="row" spacing={0.25} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
            {entry.publish_status === "draft" ? (
              <Chip size="small" color="warning" variant="outlined" label="Draft" sx={{ height: 20 }} />
            ) : (
              <Chip size="small" color="success" variant="outlined" label="Published" sx={{ height: 20 }} />
            )}
            {ot ? <Chip size="small" color="error" icon={<WarningAmberIcon />} label="OT" sx={{ height: 20 }} /> : null}
            {balanceStyle && balance !== "Balanced" ? (
              <Chip size="small" color={balanceStyle.color} label={balance} sx={{ height: 20 }} />
            ) : null}
            {(gaps || []).slice(0, 1).map((g) => (
              <Chip key={g} size="small" color="warning" variant="outlined" label={g} sx={{ height: 20, maxWidth: 120 }} />
            ))}
          </Stack>
        </Box>
        <Stack direction="row" spacing={0}>
          <IconButton size="small" onClick={() => onEdit?.(entry)} aria-label="Edit">
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
          {onDuplicate ? (
            <IconButton size="small" onClick={() => onDuplicate(entry)} aria-label="Duplicate">
              <ContentCopyIcon fontSize="small" />
            </IconButton>
          ) : null}
          <IconButton size="small" onClick={() => onRemove?.(entry.id)} aria-label="Remove">
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Stack>
      {!compact ? (
        <Stack direction="row" spacing={0.5} sx={{ mt: 0.75 }}>
          <IconButton size="small" onClick={() => onAbsent?.(entry)}>
            <PersonOffOutlinedIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" title="Find replacement" onClick={() => onReplace?.(entry)}>
            <SwapHorizOutlinedIcon fontSize="small" />
          </IconButton>
        </Stack>
      ) : null}
    </Box>
  );
}
