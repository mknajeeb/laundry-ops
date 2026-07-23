import { Button } from "@mui/material";
import { alpha } from "@mui/material/styles";
import ArrowBackIosNewIcon from "@mui/icons-material/ArrowBackIosNew";
import { OPS_MOBILE } from "./tokens";

/** Explicit Back to PIN — does not clear the unlocked employee session. */
export default function OpsBackToPin({ onClick, label = "PIN", sx = {} }) {
  return (
    <Button
      onClick={onClick}
      startIcon={<ArrowBackIosNewIcon sx={{ fontSize: 16 }} />}
      aria-label={`Back to ${label}`}
      sx={{
        minHeight: OPS_MOBILE.touchMin,
        minWidth: OPS_MOBILE.touchMin,
        px: 1.5,
        borderRadius: `${OPS_MOBILE.radius.button}px`,
        textTransform: "none",
        fontWeight: 800,
        color: OPS_MOBILE.navy,
        bgcolor: alpha(OPS_MOBILE.navy, 0.05),
        "&:hover": { bgcolor: alpha(OPS_MOBILE.navy, 0.1) },
        ...sx,
      }}
    >
      {label}
    </Button>
  );
}
