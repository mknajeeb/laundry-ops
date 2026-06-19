import { Box, Button, Chip, IconButton, Stack, Tooltip, Typography, useMediaQuery, useTheme } from "@mui/material";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import VisibilityOffOutlinedIcon from "@mui/icons-material/VisibilityOffOutlined";
import {
  ROLE_STYLES,
  deriveEmployeePrimaryRole,
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
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  const primaryRoleKey = deriveEmployeePrimaryRole(employee.user_id, entries);
  const primaryRoleLabel = primaryRoleKey ? (ROLE_STYLES[primaryRoleKey]?.label || primaryRoleKey) : null;
  const weeklySummary = formatEmployeeWeeklySummary(employee);

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
        px: 1.5,
        py: 1,
        borderBottom: "1px solid #e2e8f0",
        bgcolor: excluded ? "#fafafa" : "#fff",
        position: "sticky",
        left: 0,
        zIndex: 1,
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
                fontSize: "0.9375rem",
                wordBreak: isMobile ? "break-word" : "normal",
                overflowWrap: "anywhere",
              }}
            >
              {employee.display_name}
            </Typography>
          </Tooltip>

          {primaryRoleLabel && !excluded ? (
            <Typography
              variant="caption"
              sx={{
                display: "block",
                mt: 0.25,
                fontWeight: 600,
                color: (ROLE_STYLES[primaryRoleKey] || ROLE_STYLES.fold).accent,
                fontSize: "0.75rem",
                lineHeight: 1.3,
              }}
            >
              {primaryRoleLabel}
            </Typography>
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
