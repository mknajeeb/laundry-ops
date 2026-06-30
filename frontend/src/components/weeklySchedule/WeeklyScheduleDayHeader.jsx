import { Box, Typography } from "@mui/material";
import { ROLE_ORDER, ROLE_STYLES } from "./weeklyScheduleRoles";

function roleCountLines(summary) {
  return ROLE_ORDER.map((key) => ({
    key,
    label: ROLE_STYLES[key]?.label || key,
    count: Number(summary?.[key] || 0),
  })).filter((line) => line.count > 0);
}

export default function WeeklyScheduleDayHeader({ dayLabel, summary, daysOnly = false, compact = false }) {
  const people = Number(summary?.people || 0);
  const hours = Number(summary?.hours || 0);
  const hoursLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  const roleLines = roleCountLines(summary);

  if (compact) {
    const roleText = roleLines.map(({ label, count }) => `${label}:${count}`).join(" ");
    const parts = [`${people} emp`];
    if (!daysOnly) parts.push(`${hoursLabel}h`);
    if (roleText) parts.push(roleText);
    return (
      <Box sx={{ px: 0.75, py: 0.55 }}>
        <Typography
          variant="caption"
          sx={{ display: "block", fontWeight: 800, letterSpacing: "0.08em", fontSize: "0.68rem", lineHeight: 1.2 }}
        >
          {dayLabel.toUpperCase()}
        </Typography>
        <Typography variant="caption" sx={{ display: "block", color: "text.secondary", fontWeight: 600, lineHeight: 1.25 }}>
          {parts.join(" · ")}
        </Typography>
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
        <Box sx={{ mt: 0.5 }}>
          {roleLines.map(({ key, label, count }) => (
            <Typography
              key={key}
              variant="body2"
              sx={{
                fontWeight: 600,
                fontSize: "0.78rem",
                lineHeight: 1.35,
                color: (ROLE_STYLES[key] || ROLE_STYLES.fold).accent,
              }}
            >
              {label}: {count}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
