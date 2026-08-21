import { useEffect, useMemo, useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import FreeBreakfastOutlinedIcon from "@mui/icons-material/FreeBreakfastOutlined";
import { OPS_MOBILE } from "./tokens";
import { TEAM_ROLE_COLORS } from "./roleColors";
import OpsLockButton from "./OpsLockButton";

function formatBreakStartedAt(iso, localeTag) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(localeTag, { hour: "numeric", minute: "2-digit" });
}

/** Live elapsed from authoritative break_started_at (ET wall stored as naive → treat as local wall). */
function formatElapsed(breakStartedAt, nowMs) {
  if (!breakStartedAt) return "—";
  const start = new Date(breakStartedAt);
  if (Number.isNaN(start.getTime())) return "—";
  const sec = Math.max(0, Math.floor((nowMs - start.getTime()) / 1000));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m} min`;
  return `${sec}s`;
}

/**
 * Persistent Break Mode — only Resume Work + Lock for shared-device handoff.
 * Elapsed time is derived from server break_started_at, not a local start.
 */
export default function OpsBreakModeScreen({
  employeeName = "",
  breakStartedAt = null,
  localeTag = "en-US",
  onResume,
  onLock,
  resumeLabel = "Resume Work",
  lockLabel = "Lock",
  title = "On Break",
  startedLabel = "Break started",
  elapsedPrefix = "Break",
  lockHint = "",
  logoSrc = null,
}) {
  const bc = TEAM_ROLE_COLORS.break;
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const startedText = useMemo(
    () => formatBreakStartedAt(breakStartedAt, localeTag),
    [breakStartedAt, localeTag],
  );
  const elapsed = useMemo(
    () => formatElapsed(breakStartedAt, nowMs),
    [breakStartedAt, nowMs],
  );

  return (
    <Box
      sx={{
        width: "100%",
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        p: { xs: 2.25, sm: 3 },
        bgcolor: alpha(bc.bg, 0.92),
        border: `1px solid ${bc.border}`,
        boxShadow: `0 10px 32px -18px ${alpha(OPS_MOBILE.navy, 0.45)}`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <Box
        aria-hidden
        sx={{
          position: "absolute",
          inset: 0,
          bgcolor: alpha(OPS_MOBILE.navy, 0.04),
          pointerEvents: "none",
        }}
      />
      <Stack spacing={{ xs: 2.25, sm: 2.75 }} alignItems="stretch" sx={{ position: "relative" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
            {logoSrc ? (
              <Box
                component="img"
                src={logoSrc}
                alt=""
                sx={{ height: 36, width: "auto", maxWidth: 120, objectFit: "contain" }}
              />
            ) : null}
            <Typography
              sx={{
                fontWeight: 950,
                fontSize: { xs: "1.05rem", sm: "1.15rem" },
                color: OPS_MOBILE.navy,
                letterSpacing: 0.4,
              }}
            >
              {title}
            </Typography>
          </Stack>
        </Stack>

        <Stack spacing={1} alignItems="center" sx={{ py: { xs: 1, sm: 1.5 } }}>
          <Box
            sx={{
              width: 72,
              height: 72,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              bgcolor: alpha(bc.accent, 0.14),
              color: bc.text,
              border: `1px solid ${bc.border}`,
            }}
          >
            <FreeBreakfastOutlinedIcon sx={{ fontSize: 36 }} />
          </Box>
          <Typography
            sx={{
              fontWeight: 900,
              fontSize: { xs: "1.35rem", sm: "1.55rem" },
              color: OPS_MOBILE.navy,
              textAlign: "center",
              lineHeight: 1.2,
            }}
          >
            {employeeName || "—"}
          </Typography>
          {startedText ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.95rem", color: OPS_MOBILE.muted }}>
              {startedLabel} {startedText}
            </Typography>
          ) : null}
          <Typography
            sx={{
              fontWeight: 950,
              fontSize: { xs: "1.75rem", sm: "2.1rem" },
              color: bc.text,
              letterSpacing: -0.5,
            }}
          >
            {elapsedPrefix} · {elapsed}
          </Typography>
        </Stack>

        <Button
          fullWidth
          variant="contained"
          onClick={onResume}
          sx={{
            minHeight: { xs: 64, sm: 68 },
            borderRadius: `${OPS_MOBILE.radius.button}px`,
            textTransform: "none",
            fontWeight: 950,
            fontSize: { xs: "1.15rem", sm: "1.25rem" },
            bgcolor: OPS_MOBILE.blue,
            boxShadow: `0 8px 20px -12px ${alpha(OPS_MOBILE.blue, 0.8)}`,
            "&:hover": { bgcolor: OPS_MOBILE.cobalt },
          }}
        >
          {resumeLabel}
        </Button>

        <Stack spacing={0.75} alignItems="stretch">
          <OpsLockButton onClick={onLock} label={lockLabel} fullWidth />
          {lockHint ? (
            <Typography
              sx={{
                fontWeight: 650,
                fontSize: "0.78rem",
                color: alpha(OPS_MOBILE.navy, 0.55),
                textAlign: "center",
                lineHeight: 1.35,
              }}
            >
              {lockHint}
            </Typography>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}
