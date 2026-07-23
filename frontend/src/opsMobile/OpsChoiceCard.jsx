import { Button, CircularProgress, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";

/**
 * Large selectable choice card (e.g. Operator / Folder).
 * Entire card is the tap target — no radios.
 */
export default function OpsChoiceCard({
  title,
  subtitle = "",
  icon: Icon = null,
  selected = false,
  busy = false,
  disabled = false,
  onClick,
  "aria-label": ariaLabel,
  sx = {},
}) {
  return (
    <Button
      fullWidth
      disabled={disabled || busy}
      onClick={onClick}
      aria-label={ariaLabel || title}
      aria-pressed={selected}
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "center",
        gap: 0.75,
        minHeight: 96,
        px: 2.25,
        py: 2,
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        textTransform: "none",
        textAlign: "left",
        color: OPS_MOBILE.navy,
        bgcolor: selected ? alpha(OPS_MOBILE.cobalt, 0.14) : alpha(OPS_MOBILE.navy, 0.04),
        border: selected ? `2px solid ${OPS_MOBILE.cobalt}` : `2px solid transparent`,
        "&:hover": {
          bgcolor: selected ? alpha(OPS_MOBILE.cobalt, 0.18) : alpha(OPS_MOBILE.navy, 0.07),
        },
        ...sx,
      }}
    >
      {busy ? (
        <CircularProgress size={28} />
      ) : (
        <>
          {Icon ? <Icon sx={{ fontSize: 32, color: OPS_MOBILE.blue, mb: 0.25 }} /> : null}
          <Typography sx={{ fontWeight: 900, fontSize: "1.5rem", lineHeight: 1.15, letterSpacing: "-0.02em" }}>
            {title}
          </Typography>
          {subtitle ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.9rem", color: OPS_MOBILE.muted }}>
              {subtitle}
            </Typography>
          ) : null}
        </>
      )}
    </Button>
  );
}
