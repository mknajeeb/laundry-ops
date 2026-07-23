import { Box, Button, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import ArrowBackIosNewIcon from "@mui/icons-material/ArrowBackIosNew";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import { OPS_MOBILE } from "./tokens";

/**
 * Compact ops top bar: small mark + optional identity + Lock.
 * Back is a separate control (see OpsBackToPin) — never label Back as Lock.
 */
export default function OpsTopBar({
  identity = "",
  logoSrc = null,
  onLock,
  lockLabel = "Lock",
  onBack = null,
  backLabel = "PIN",
  right = null,
  sticky = true,
}) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1,
        minHeight: OPS_MOBILE.touchMin,
        width: "100%",
        ...(sticky
          ? {
              position: "sticky",
              top: 0,
              zIndex: 2,
              bgcolor: alpha("#fff", 0.92),
              backdropFilter: "blur(8px)",
              mx: -0.5,
              px: 0.5,
              py: 0.25,
            }
          : null),
      }}
    >
      {onBack ? (
        <Button
          onClick={onBack}
          startIcon={<ArrowBackIosNewIcon sx={{ fontSize: 16 }} />}
          aria-label={`Back to ${backLabel}`}
          sx={{
            flexShrink: 0,
            minHeight: OPS_MOBILE.touchMin,
            minWidth: OPS_MOBILE.touchMin,
            px: 1.25,
            borderRadius: `${OPS_MOBILE.radius.button}px`,
            textTransform: "none",
            fontWeight: 800,
            color: OPS_MOBILE.navy,
            bgcolor: alpha(OPS_MOBILE.navy, 0.05),
          }}
        >
          {backLabel}
        </Button>
      ) : null}

      {logoSrc ? (
        <Box
          component="img"
          src={logoSrc}
          alt=""
          sx={{ height: 28, width: "auto", maxWidth: 72, objectFit: "contain", flexShrink: 0 }}
        />
      ) : null}

      <Box sx={{ flex: 1, minWidth: 0 }}>
        {identity ? (
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: OPS_MOBILE.type.identity,
              color: OPS_MOBILE.navy,
              lineHeight: 1.2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {identity}
          </Typography>
        ) : null}
      </Box>

      {right}

      {onLock ? (
        <Button
          onClick={onLock}
          startIcon={<LockOutlinedIcon />}
          aria-label={lockLabel}
          sx={{
            flexShrink: 0,
            minHeight: OPS_MOBILE.touchMin,
            minWidth: OPS_MOBILE.touchMin,
            px: 1.75,
            borderRadius: `${OPS_MOBILE.radius.button}px`,
            textTransform: "none",
            fontWeight: 800,
            fontSize: "1rem",
            color: OPS_MOBILE.navy,
            bgcolor: alpha(OPS_MOBILE.navy, 0.06),
            "&:hover": { bgcolor: alpha(OPS_MOBILE.navy, 0.1) },
          }}
        >
          {lockLabel}
        </Button>
      ) : null}
    </Box>
  );
}
