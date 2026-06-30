import { Box, Stack, Typography } from "@mui/material";
import { ROLE_ORDER } from "./weeklyScheduleRoles";
import ScheduleRoleChip from "./ScheduleRoleChip";

function roleCountLines(summary) {
  return ROLE_ORDER.map((key) => ({
    key,
    count: Number(summary?.[key] || 0),
  })).filter((line) => line.count > 0);
}

export default function WeeklyScheduleDayHeader({ dayLabel, summary, daysOnly = false, compact = false }) {
  const people = Number(summary?.people || 0);
  const hours = Number(summary?.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  const roleLines = roleCountLines(summary);

  if (compact) {
    const statParts = [`${people} emp`];
    if (!daysOnly) statParts.push(`${hoursLabel} h`);

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
        {roleLines.length ? (
          <Stack direction="row" spacing={0.35} useFlexGap flexWrap="wrap" sx={{ mt: 0.45 }}>
            {roleLines.map(({ key, count }) => (
              <ScheduleRoleChip key={key} roleKey={key} count={count} />
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
          {hoursLabel} Hour{hours === 1 ? "" : "s"}
        </Typography>
      ) : null}
      {roleLines.length ? (
        <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
          {roleLines.map(({ key, count }) => (
            <ScheduleRoleChip key={key} roleKey={key} count={count} />
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}
