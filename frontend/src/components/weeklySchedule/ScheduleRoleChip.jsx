import { Chip } from "@mui/material";
import { formatRoleHoursLabel, HOUR_TRACKED_ROLES, ROLE_STYLES, roleCompactLabel } from "./weeklyScheduleRoles";

const HOUR_TRACKED = new Set(HOUR_TRACKED_ROLES);

export default function ScheduleRoleChip({ roleKey, count = null, hours = null, sx = {} }) {
  const style = ROLE_STYLES[roleKey] || ROLE_STYLES.fold;
  const label = roleCompactLabel(roleKey);
  let text = label;
  if (count != null && HOUR_TRACKED.has(roleKey) && hours != null && Number(hours) > 0) {
    text = `${label} ${count} · ${formatRoleHoursLabel(hours)}`;
  } else if (count != null) {
    text = `${label} ${count}`;
  }

  return (
    <Chip
      size="small"
      label={text}
      sx={{
        height: 19,
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
