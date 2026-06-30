import { Chip } from "@mui/material";
import { ROLE_STYLES, roleCompactLabel } from "./weeklyScheduleRoles";

export default function ScheduleRoleChip({ roleKey, count = null, sx = {} }) {
  const style = ROLE_STYLES[roleKey] || ROLE_STYLES.fold;
  const text = count != null ? `${roleCompactLabel(roleKey)} ${count}` : roleCompactLabel(roleKey);

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
