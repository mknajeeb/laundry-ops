import { Box, Button, Chip, IconButton, Stack, Tooltip, Typography, useMediaQuery, useTheme } from "@mui/material";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import OpenInNewOutlinedIcon from "@mui/icons-material/OpenInNewOutlined";
import VisibilityOffOutlinedIcon from "@mui/icons-material/VisibilityOffOutlined";
import {
  employeeWeeklyRoleCounts,
  formatEmployeeWeeklySummary,
} from "./weeklyScheduleRoles";

export default function WeeklyScheduleEmployeeCell({
  employee,
  entries,
  excluded,
  canManageExclusions,
  excludeSaving,
  onExcludeToggle,
  showCost,
  showRates,
  costAllowed,
  daysOnly = false,
  onViewSchedule,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  const roleCounts = employeeWeeklyRoleCounts(employee.user_id, entries);
  const weeklySummary = formatEmployeeWeeklySummary(employee, { daysOnly });

  const rateParts = [];
  if (showRates && employee?.default_hourly_rate) {
    rateParts.push(
      `${Number(employee.default_hourly_rate).toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
      })}/hr`,
    );
  }
  if (showCost && costAllowed) {
    rateParts.push(
      `${Number(employee?.estimated_cost || 0).toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
      })} est.`,
    );
  }

  return (
    <Box
      sx={{
        px: 1.15,
        py: 0.85,
        borderBottom: "1px solid #e2e8f0",
        position: "sticky",
        left: 0,
        zIndex: 2,
        bgcolor: excluded ? "#fafafa" : "#fff",
        boxShadow: excluded ? "none" : "2px 0 8px rgba(15,23,42,0.05)",
        minWidth: 0,
      }}
    >
      <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={0.75}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Tooltip title={employee.display_name} enterDelay={600} disableHoverListener={!isMobile}>
            <Typography
              variant="body2"
              sx={{
                fontWeight: 800,
                lineHeight: 1.35,
                textDecoration: excluded ? "line-through" : "none",
                color: excluded ? "text.secondary" : "text.primary",
                fontSize: "0.875rem",
                wordBreak: isMobile ? "break-word" : "normal",
                overflowWrap: "anywhere",
              }}
            >
              {employee.display_name}
            </Typography>
          </Tooltip>

          {roleCounts.length && !excluded ? (
            <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.45 }}>
              {roleCounts.map(({ key, label, count, style }) => (
                <Chip
                  key={key}
                  size="small"
                  label={`${label} ${count}`}
                  sx={{
                    height: 20,
                    fontSize: "0.68rem",
                    fontWeight: 700,
                    bgcolor: style.chipBg,
                    color: style.accent,
                    border: `1px solid ${style.border}`,
                    "& .MuiChip-label": { px: 0.75 },
                  }}
                />
              ))}
            </Stack>
          ) : null}

          {!excluded ? (
            <Typography
              variant="caption"
              sx={{
                display: "block",
                mt: 0.35,
                fontWeight: 600,
                color: "text.secondary",
                fontSize: "0.75rem",
                lineHeight: 1.3,
              }}
            >
              {weeklySummary}
              {rateParts.length ? ` · ${rateParts.join(" · ")}` : ""}
            </Typography>
          ) : null}

          {excluded ? (
            <Chip
              size="small"
              label="Excluded this week"
              color="default"
              sx={{ mt: 0.5, height: 22, fontSize: "0.68rem", fontWeight: 700 }}
            />
          ) : null}
        </Box>

        {onViewSchedule ? (
          <Tooltip title="Open employee schedule view">
            <IconButton
              size="small"
              aria-label="Open employee schedule view"
              className="weekly-schedule-employee-cell-actions"
              onClick={() => onViewSchedule(employee)}
              sx={{ mt: -0.25, flexShrink: 0 }}
            >
              <OpenInNewOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : null}

        {canManageExclusions ? (
          <Tooltip title={excluded ? "Include in schedule" : "Exclude from this week's schedule"}>
            <IconButton
              size="small"
              aria-label={excluded ? "Include in schedule" : "Exclude from schedule"}
              disabled={excludeSaving}
              onClick={() => onExcludeToggle(employee, !excluded)}
              sx={{ mt: -0.25, flexShrink: 0 }}
            >
              {excluded ? (
                <VisibilityOffOutlinedIcon fontSize="small" />
              ) : (
                <PersonOffOutlinedIcon fontSize="small" />
              )}
            </IconButton>
          </Tooltip>
        ) : null}
      </Stack>

      {excluded && canManageExclusions ? (
        <Button
          size="small"
          variant="contained"
          color="success"
          onClick={() => onExcludeToggle(employee, false)}
          disabled={excludeSaving}
          sx={{ mt: 0.75, fontSize: "0.72rem", textTransform: "none", fontWeight: 700 }}
        >
          Include in schedule
        </Button>
      ) : null}
    </Box>
  );
}
