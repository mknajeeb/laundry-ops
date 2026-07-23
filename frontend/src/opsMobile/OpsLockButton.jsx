import { Button } from "@mui/material";
import { alpha } from "@mui/material/styles";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import { OPS_MOBILE } from "./tokens";

/**
 * Clears the unlocked PIN employee session and returns to PIN entry.
 * Must not clock out or mutate attendance / role / checklist / inventory data.
 */
export default function OpsLockButton({ onClick, label = "Lock", fullWidth = false, sx = {} }) {
  return (
    <Button
      fullWidth={fullWidth}
      onClick={onClick}
      startIcon={<LockOutlinedIcon />}
      aria-label={label}
      sx={{
        minHeight: fullWidth ? 64 : OPS_MOBILE.touchMin,
        minWidth: OPS_MOBILE.touchMin,
        px: 2,
        borderRadius: `${OPS_MOBILE.radius.button}px`,
        textTransform: "none",
        fontWeight: 800,
        fontSize: fullWidth ? "1.15rem" : "1rem",
        color: OPS_MOBILE.navy,
        bgcolor: alpha(OPS_MOBILE.navy, 0.08),
        "&:hover": { bgcolor: alpha(OPS_MOBILE.navy, 0.12) },
        ...sx,
      }}
    >
      {label}
    </Button>
  );
}
