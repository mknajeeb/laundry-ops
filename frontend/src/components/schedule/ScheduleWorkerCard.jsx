import {
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { BALANCE_BADGE, formatTime12, SCHEDULE_THEME, STATUS_BADGE } from "../../payroll/scheduleTheme";
import { workerProfileUrl } from "../../payroll/schedulePlanner";

export default function ScheduleWorkerCard({ entry, weekStats, onEdit, onRemove, onAbsent, onReplace }) {
  const statusKey = entry.status || "scheduled";
  const status = STATUS_BADGE[statusKey] || { label: statusKey, color: "default" };
  const balance = weekStats?.balance_label;
  const balanceStyle = balance ? BALANCE_BADGE[balance] : null;
  const ot = weekStats?.overtime_risk;
  const perf = entry.performance_preview;
  const warnings = entry.warnings || [];
  const profileUrl = workerProfileUrl(entry.user_id);

  return (
    <Card
      sx={{
        ...SCHEDULE_THEME.card,
        mb: 1.25,
        overflow: "visible",
      }}
    >
      <CardActionArea onClick={() => onEdit(entry)} sx={{ borderRadius: SCHEDULE_THEME.card.borderRadius }}>
        <CardContent sx={{ py: 1.5, px: 1.5, "&:last-child": { pb: 1.5 } }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="subtitle2" fontWeight={700} noWrap>
                {entry.worker_name || "Worker"}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {formatTime12(entry.start_time)} – {formatTime12(entry.end_time)} ·{" "}
                {Number(entry.scheduled_hours || 0).toFixed(1)}h
                {weekStats ? ` · ${weekStats.scheduled_hours.toFixed(1)}h wk` : ""}
                {entry.worker_category_label ? ` · ${entry.worker_category_label}` : ""}
              </Typography>
            </Box>
            <Chip size="small" color={status.color} label={status.label} sx={{ fontWeight: 600, fontSize: "0.7rem" }} />
          </Stack>

          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            {entry.shift_name ? (
              <Chip size="small" label={entry.shift_name} sx={{ bgcolor: SCHEDULE_THEME.accentSoft, fontWeight: 600 }} />
            ) : null}
            {entry.role_name ? <Chip size="small" variant="outlined" label={entry.role_name} /> : null}
            {entry.work_stream_name ? (
              <Chip size="small" variant="outlined" label={entry.work_stream_name} />
            ) : null}
            {entry.publish_status === "draft" ? (
              <Chip size="small" color="warning" variant="outlined" label="Draft" />
            ) : null}
            {ot ? (
              <Chip size="small" color="error" icon={<WarningAmberIcon />} label="OT Risk" />
            ) : null}
            {balanceStyle ? (
              <Chip size="small" color={balanceStyle.color} variant={balanceStyle.variant} label={balance} />
            ) : null}
            {warnings.slice(0, 2).map((w) => (
              <Chip key={w} size="small" color="warning" variant="outlined" label={w} />
            ))}
          </Stack>

          {perf?.available ? (
            <Typography variant="caption" color="success.main" sx={{ mt: 0.75, display: "block" }}>
              Performance: {perf.avg_bags_per_hour != null ? `${perf.avg_bags_per_hour} bags/hr` : "Strong"}
            </Typography>
          ) : (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: "block" }}>
              No performance data yet
            </Typography>
          )}
        </CardContent>
      </CardActionArea>

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 0.5, pb: 0.5 }}>
        {profileUrl ? (
          <Button
            size="small"
            component={RouterLink}
            to={profileUrl}
            target="_blank"
            rel="noopener"
            startIcon={<OpenInNewIcon sx={{ fontSize: 14 }} />}
            sx={{ fontSize: "0.7rem", minWidth: 0 }}
          >
            Worker profile
          </Button>
        ) : (
          <Box />
        )}
        <Stack direction="row" spacing={0.25}>
          <IconButton size="small" aria-label="Edit" onClick={() => onEdit(entry)}>
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" aria-label="Find replacement" title="Find replacement" onClick={() => onReplace(entry)}>
            <SwapHorizOutlinedIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" aria-label="Mark absent" onClick={() => onAbsent(entry)}>
            <PersonOffOutlinedIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" color="error" aria-label="Remove" onClick={() => onRemove(entry.id)}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Stack>
    </Card>
  );
}
