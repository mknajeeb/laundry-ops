import { Chip } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";

const TONES = {
  default: { fg: OPS_MOBILE.navy, bg: alpha(OPS_MOBILE.navy, 0.08) },
  success: { fg: OPS_MOBILE.success, bg: alpha(OPS_MOBILE.success, 0.12) },
  warning: { fg: "#b45309", bg: alpha("#b45309", 0.12) },
  danger: { fg: OPS_MOBILE.danger, bg: alpha(OPS_MOBILE.danger, 0.12) },
  info: { fg: OPS_MOBILE.blue, bg: alpha(OPS_MOBILE.blue, 0.12) },
};

/** Compact status chip for actionable existing data (not decorative badges). */
export default function OpsStatusChip({ label, tone = "default", sx = {}, ...rest }) {
  const t = TONES[tone] || TONES.default;
  return (
    <Chip
      size="small"
      label={label}
      sx={{
        fontWeight: 800,
        height: 28,
        color: t.fg,
        bgcolor: t.bg,
        "& .MuiChip-label": { px: 1.25 },
        ...sx,
      }}
      {...rest}
    />
  );
}
