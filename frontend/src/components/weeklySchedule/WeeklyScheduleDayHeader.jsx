import { Box, Stack, Typography } from "@mui/material";
import { formatHours, formatHoursBreakdown, formatUnallocatedBreak, UNALLOCATED_BREAK_NOTE } from "./weeklyScheduleRoles";
import ScheduleRoleChip from "./ScheduleRoleChip";

/** Per role: distinct employees assigned that day and their net hours (from `computeFilteredDaySummaries`). */
function roleCountLines(summary) {
  return (summary?.roles || [])
    .filter((row) => Number(row.employees || 0) > 0)
    .map((row) => ({
      key: row.role,
      count: Number(row.employees),
      hours: Number(row.hours || 0),
      unallocatedBreakHours: Number(row.unallocatedBreakHours || 0),
    }));
}

export default function WeeklyScheduleDayHeader({ dayLabel, summary, daysOnly = false, compact = false, showBreaks = true }) {
  const people = Number(summary?.people || 0);
  const hours = Number(summary?.hours || 0);
  const hoursLabel = formatHours(hours);
  const breakHours = Number(summary?.break_hours || 0);
  const pending = !daysOnly ? Number(summary?.unallocated_break_hours || 0) : 0;
  const roleUnallocated = !daysOnly ? Number(summary?.role_unallocated_break_hours || 0) : 0;
  const breakdown = !daysOnly && showBreaks && breakHours > 0
    ? formatHoursBreakdown({ gross: summary?.gross_hours, breakHours, net: hours })
    : "";
  const hoursKind = pending > 0.0001 ? "gross " : breakdown ? "net " : "";
  const roleLines = roleCountLines(summary);
  const lineSx = { display: "block", color: "#9a3412", fontWeight: 700, fontSize: "0.62rem", lineHeight: 1.25 };
  const breakdownLine = (
    <>
      {breakdown ? (
        <Typography variant="caption" data-day-hours-breakdown sx={lineSx}>
          {breakdown}
        </Typography>
      ) : null}
      {roleUnallocated > 0.0001 ? (
        <Typography variant="caption" data-day-hours-unresolved sx={lineSx}>
          {showBreaks ? `${formatUnallocatedBreak(roleUnallocated)} · ` : ""}
          {UNALLOCATED_BREAK_NOTE}
        </Typography>
      ) : null}
    </>
  );

  if (compact) {
    const statParts = [`${people} emp`];
    if (!daysOnly) statParts.push(`${hoursLabel} ${hoursKind}hrs`);

    return (
      <Box sx={{ px: 0.85, py: 0.65, minWidth: 0 }}>
        <Typography
          variant="caption"
          sx={{
            display: "block",
            fontWeight: 800,
            letterSpacing: "0.1em",
            fontSize: "0.7rem",
            lineHeight: 1.2,
            color: "text.primary",
          }}
        >
          {dayLabel.toUpperCase()}
        </Typography>
        <Typography
          variant="caption"
          sx={{
            display: "block",
            mt: 0.25,
            color: "text.secondary",
            fontWeight: 600,
            fontSize: "0.65rem",
            lineHeight: 1.25,
          }}
        >
          {statParts.join(" · ")}
        </Typography>
        {breakdownLine}
        {roleLines.length ? (
          <Stack direction="row" spacing={0.35} useFlexGap flexWrap="wrap" sx={{ mt: 0.45 }}>
            {roleLines.map(({ key, count, hours: roleHours, unallocatedBreakHours }) => (
              <ScheduleRoleChip
                key={key}
                roleKey={key}
                count={count}
                hours={daysOnly ? null : roleHours}
                unallocatedBreakHours={unallocatedBreakHours}
              />
            ))}
          </Stack>
        ) : null}
      </Box>
    );
  }

  return (
    <Box sx={{ px: 1, py: 1 }}>
      <Typography
        variant="overline"
        sx={{
          display: "block",
          fontWeight: 800,
          letterSpacing: "0.12em",
          color: "text.primary",
          fontSize: "0.72rem",
          lineHeight: 1.2,
        }}
      >
        {dayLabel.toUpperCase()}
      </Typography>
      <Typography
        variant="body2"
        sx={{ mt: 0.5, fontWeight: 700, color: "text.primary", fontSize: "0.8125rem", lineHeight: 1.3 }}
      >
        {people} Employee{people === 1 ? "" : "s"}
      </Typography>
      {!daysOnly ? (
        <Typography
          variant="body2"
          sx={{ fontWeight: 600, color: "text.secondary", fontSize: "0.8125rem", lineHeight: 1.3 }}
        >
          {hoursLabel} {pending > 0.0001 ? "Gross " : breakdown ? "Net " : ""}Hour{hours === 1 ? "" : "s"}
        </Typography>
      ) : null}
      {breakdownLine}
      {roleLines.length ? (
        <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
          {roleLines.map(({ key, count, hours: roleHours, unallocatedBreakHours }) => (
            <ScheduleRoleChip
              key={key}
              roleKey={key}
              count={count}
              hours={daysOnly ? null : roleHours}
              unallocatedBreakHours={unallocatedBreakHours}
            />
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}
