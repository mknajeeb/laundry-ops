import { Box, Button, Typography, useTheme } from "@mui/material";
import { alpha } from "@mui/material/styles";
import ArrowBackIosNewIcon from "@mui/icons-material/ArrowBackIosNew";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import { useI18n } from "../i18n/I18nContext";
import { OPS_MOBILE } from "./tokens";

/**
 * Compact ops top bar: Back / title / identity / Lock.
 * Back and Lock stay distinct actions.
 */
export default function OpsTopBar({
  identity = "",
  title = "",
  logoSrc = null,
  onLock,
  lockLabel = "Lock",
  onBack = null,
  backLabel = "PIN",
  right = null,
  sticky = true,
}) {
  const { t } = useI18n();
  const theme = useTheme();
  const accent = theme.palette.primary.main || OPS_MOBILE.navy;
  const resolvedLock = !lockLabel || lockLabel === "Lock" ? t("mobileOps.lock") : lockLabel;
  const resolvedBack = !backLabel || backLabel === "PIN" ? t("tasks.pin.backToPin") : backLabel;
  return (
    <Box
      sx={{
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
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1,
        minHeight: 40,
        width: "100%",
      }}
    >
      {onBack ? (
        <Button
          onClick={onBack}
          startIcon={<ArrowBackIosNewIcon sx={{ fontSize: 16 }} />}
          aria-label={resolvedBack}
          sx={{
            flexShrink: 0,
            minHeight: 40,
            minWidth: 40,
            px: 1,
            borderRadius: `${OPS_MOBILE.radius.button}px`,
            textTransform: "none",
            fontWeight: 700,
            fontSize: "0.85rem",
            color: accent,
            bgcolor: alpha(accent, 0.08),
          }}
        >
          {resolvedBack}
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
              fontWeight: 700,
              fontSize: "0.8rem",
              color: theme.palette.text.primary,
              lineHeight: 1.2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              textAlign: title || onBack ? "right" : "left",
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
          aria-label={resolvedLock}
          sx={{
            flexShrink: 0,
            minHeight: 40,
            minWidth: 40,
            px: 1,
            borderRadius: `${OPS_MOBILE.radius.button}px`,
            textTransform: "none",
            fontWeight: 700,
            fontSize: "0.85rem",
            color: accent,
            bgcolor: alpha(accent, 0.08),
            "&:hover": { bgcolor: alpha(accent, 0.14) },
          }}
        >
          {resolvedLock}
        </Button>
      ) : null}
    </Box>
    {title ? (
      <Typography
        component="h1"
        sx={{
          fontWeight: 800,
          fontSize: "1.05rem",
          lineHeight: 1.25,
          color: accent,
          mt: 0.25,
        }}
      >
        {title}
      </Typography>
    ) : null}
    </Box>
  );
}
