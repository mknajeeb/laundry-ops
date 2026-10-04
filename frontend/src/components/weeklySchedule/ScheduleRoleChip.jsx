import { Chip } from "@mui/material";
import { formatRoleHoursValue, roleCompactLabel, roleStyle, UNALLOCATED_BREAK_NOTE } from "./weeklyScheduleRoles";

/**
 * Role chip; with `count` it reads "Fold: 3 people · 21.5 hrs" (distinct employees and net hours), or
 * "… 22 gross hrs" while a break without a time on a multi-role shift is not allocated to a role.
 */
export default function ScheduleRoleChip({ roleKey, count = null, hours = null, unallocatedBreakHours = 0, sx = {} }) {
  const style = roleStyle(roleKey);
  const label = roleCompactLabel(roleKey);
  const pending = hours != null && Number(unallocatedBreakHours || 0) > 0.0001;
  let text = label;
  if (count != null) {
    const people = `${count} ${Number(count) === 1 ? "person" : "people"}`;
    text = hours != null ? `${label}: ${people} · ${formatRoleHoursValue(hours, unallocatedBreakHours)} hrs` : `${label}: ${people}`;
  }

  return (
    <Chip
      size="small"
      label={text}
      title={pending ? UNALLOCATED_BREAK_NOTE : undefined}
      data-role-chip={roleKey}
      data-role-hours-gross={pending ? "true" : undefined}
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
