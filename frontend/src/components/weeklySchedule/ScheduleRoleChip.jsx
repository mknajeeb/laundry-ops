import { Chip } from "@mui/material";
import { formatHours, roleCompactLabel, roleStyle } from "./weeklyScheduleRoles";

/** Role chip; with `count` it reads "Fold: 3 people · 21.5 hrs" (distinct employees and net hours). */
export default function ScheduleRoleChip({ roleKey, count = null, hours = null, sx = {} }) {
  const style = roleStyle(roleKey);
  const label = roleCompactLabel(roleKey);
  let text = label;
  if (count != null) {
    const people = `${count} ${Number(count) === 1 ? "person" : "people"}`;
    text = hours != null ? `${label}: ${people} · ${formatHours(hours)} hrs` : `${label}: ${people}`;
  }

  return (
    <Chip
      size="small"
      label={text}
      data-role-chip={roleKey}
      sx={{
        height: count != null ? "auto" : 19,
        minHeight: 19,
        maxWidth: "100%",
        fontSize: "0.625rem",
        fontWeight: 700,
        bgcolor: style.chipBg,
        color: style.accent,
        border: `1px solid ${style.border}`,
        "& .MuiChip-label": {
          px: 0.6,
          py: 0,
          whiteSpace: "normal",
          lineHeight: 1.2,
        },
        ...sx,
      }}
    />
  );
}
