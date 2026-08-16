import { Box, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const TONES = {
  workload: {
    color: VEEWASH_DASHBOARD.wfCharcoal,
    border: VEEWASH_DASHBOARD.wfBorder,
    bg: "#fff",
  },
  completed: {
    color: VEEWASH_DASHBOARD.tealDark,
    border: VEEWASH_DASHBOARD.tealBorder,
    bg: "#fff",
  },
  pending: {
    color: VEEWASH_DASHBOARD.pending,
    border: VEEWASH_DASHBOARD.pendingBorder,
    bg: "#fff",
  },
  review: {
    color: "#b91c1c",
    border: "rgba(185, 28, 28, 0.35)",
    bg: "#fff",
  },
  hd: {
    color: VEEWASH_DASHBOARD.hdTeal,
    border: VEEWASH_DASHBOARD.hdBorder,
    bg: "#fff",
  },
  specialty: {
    color: "#334155",
    border: "#e5e7eb",
    bg: "#fff",
  },
};

export default function TodayTapCard({
  label,
  value,
  sub,
  onClick,
  tone = "specialty",
  warn = false,
}) {
  const palette = TONES[tone] || TONES.specialty;
  const color = warn && tone === "review" ? palette.color : warn ? "#b91c1c" : palette.color;
  const border = warn ? (tone === "review" ? palette.border : "rgba(185, 28, 28, 0.35)") : palette.border;
  const bg = warn && tone === "review" ? "#fef2f2" : palette.bg;

  return (
    <Box
      component={onClick ? "button" : "div"}
      type={onClick ? "button" : undefined}
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        px: 1,
        py: 0.85,
        minHeight: 56,
        borderRadius: 1.5,
        border: "1px solid",
        borderColor: border,
        bgcolor: bg,
        cursor: onClick ? "pointer" : "default",
        appearance: "none",
        fontFamily: "inherit",
        WebkitTapHighlightColor: "transparent",
        "&:hover": onClick
          ? { borderColor: color, boxShadow: "0 1px 6px rgba(15, 23, 42, 0.08)" }
          : undefined,
      }}
    >
      <Typography
        sx={{
          fontSize: { xs: 20, sm: 22 },
          fontWeight: 800,
          lineHeight: 1.05,
          letterSpacing: -0.3,
          color,
        }}
      >
        {value}
      </Typography>
      <Typography
        sx={{
          mt: 0.35,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.6,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {label}
      </Typography>
      {sub ? (
        <Typography sx={{ mt: 0.15, fontSize: 11, color: "#94a3b8", fontWeight: 600 }}>
          {sub}
        </Typography>
      ) : null}
    </Box>
  );
}
