import { Box, Button, CircularProgress, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";

/**
 * Large icon + label card for the PIN / ops action launcher.
 * Icons are secondary; label stays large and readable (Spanish-safe wrapping).
 */
export default function OpsLauncherTile({
  label,
  helper = "",
  icon: Icon,
  color = OPS_MOBILE.blue,
  busy = false,
  disabled = false,
  disabledHelper = "",
  onClick,
  "aria-label": ariaLabel,
}) {
  return (
    <Button
      fullWidth
      disabled={disabled || busy}
      onClick={onClick}
      aria-label={ariaLabel || label}
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 0.75,
        minHeight: { xs: OPS_MOBILE.tileMinHeight, sm: 132 },
        px: 1.25,
        py: 1.5,
        borderRadius: `${OPS_MOBILE.radius.tile}px`,
        textTransform: "none",
        color: OPS_MOBILE.navy,
        bgcolor: alpha(color, 0.08),
        border: "none",
        boxShadow: `0 1px 0 ${alpha(OPS_MOBILE.navy, 0.04)}`,
        "&:hover": {
          bgcolor: alpha(color, 0.14),
        },
        "&.Mui-disabled": {
          opacity: 0.55,
        },
      }}
    >
      <Box
        sx={{
          width: 52,
          height: 52,
          borderRadius: "14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: alpha(color, 0.16),
          color,
          flexShrink: 0,
        }}
      >
        {busy ? (
          <CircularProgress size={26} sx={{ color }} />
        ) : Icon ? (
          <Icon sx={{ fontSize: 30 }} />
        ) : null}
      </Box>
      <Typography
        component="span"
        sx={{
          fontWeight: 800,
          fontSize: { xs: "1rem", sm: OPS_MOBILE.type.tileLabel },
          lineHeight: 1.2,
          textAlign: "center",
          letterSpacing: "-0.01em",
          wordBreak: "break-word",
          hyphens: "auto",
          maxWidth: "100%",
        }}
      >
        {label}
      </Typography>
      {helper && !disabled ? (
        <Typography
          component="span"
          sx={{
            fontWeight: 650,
            fontSize: "0.72rem",
            lineHeight: 1.25,
            textAlign: "center",
            color: OPS_MOBILE.muted,
            maxWidth: "100%",
            px: 0.25,
          }}
        >
          {helper}
        </Typography>
      ) : null}
      {disabled && disabledHelper ? (
        <Typography
          component="span"
          sx={{
            fontWeight: 700,
            fontSize: "0.72rem",
            lineHeight: 1.25,
            textAlign: "center",
            color: OPS_MOBILE.muted,
            maxWidth: "100%",
            px: 0.25,
          }}
        >
          {disabledHelper}
        </Typography>
      ) : null}
    </Button>
  );
}
