import { Box, Button, CircularProgress, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";
import OpsStatusChip from "./OpsStatusChip";

/**
 * Large selectable choice card (e.g. Operator / Folder).
 * Entire card is the tap target — no radios.
 */
export default function OpsChoiceCard({
  title,
  subtitle = "",
  icon: Icon = null,
  selected = false,
  current = false,
  busy = false,
  disabled = false,
  onClick,
  "aria-label": ariaLabel,
  sx = {},
}) {
  return (
    <Button
      fullWidth
      disabled={disabled}
      onClick={onClick}
      aria-label={ariaLabel || title}
      aria-pressed={selected || current}
      aria-busy={busy || undefined}
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "center",
        gap: 0.75,
        minHeight: 112,
        px: 2.25,
        py: 2,
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        textTransform: "none",
        textAlign: "left",
        color: OPS_MOBILE.navy,
        bgcolor: selected || current ? alpha(OPS_MOBILE.cobalt, 0.14) : alpha(OPS_MOBILE.navy, 0.04),
        border:
          selected || current
            ? `2px solid ${OPS_MOBILE.cobalt}`
            : `2px solid transparent`,
        "&:hover": {
          bgcolor:
            selected || current
              ? alpha(OPS_MOBILE.cobalt, 0.18)
              : alpha(OPS_MOBILE.navy, 0.07),
        },
        "&.Mui-disabled": {
          opacity: busy ? 1 : 0.5,
        },
        ...sx,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.25, width: "100%" }}>
        {Icon ? <Icon sx={{ fontSize: 32, color: OPS_MOBILE.blue, flexShrink: 0, mt: 0.25 }} /> : null}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: { xs: "1.45rem", sm: "1.6rem" },
              lineHeight: 1.2,
              letterSpacing: "-0.02em",
              whiteSpace: "normal",
              wordBreak: "break-word",
              overflowWrap: "anywhere",
            }}
          >
            {title}
          </Typography>
          {subtitle ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.9rem", color: OPS_MOBILE.muted, mt: 0.5 }}>
              {subtitle}
            </Typography>
          ) : null}
          {current ? (
            <Box sx={{ mt: 1 }}>
              <OpsStatusChip label="Current" tone="success" />
            </Box>
          ) : null}
        </Box>
        {busy ? <CircularProgress size={28} sx={{ flexShrink: 0, mt: 0.5 }} /> : null}
      </Box>
    </Button>
  );
}
