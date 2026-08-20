import { Box, Typography } from "@mui/material";
import { fmtMoney } from "./revenueFormat";

/**
 * Compact operational home row for Revenue / Cash sections.
 */
export default function SectionStatusCard({
  title,
  primary,
  secondary,
  statusLabel,
  statusTone = "neutral",
  onClick,
}) {
  const toneColor =
    statusTone === "ok"
      ? "#0f766e"
      : statusTone === "warn"
        ? "#d97706"
        : "#64748b";

  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        p: 1.5,
        borderRadius: 2,
        border: "1px solid rgba(0,151,178,0.28)",
        bgcolor: "#fff",
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        boxShadow: "0 1px 3px rgba(0,60,80,0.08)",
        minHeight: 72,
        "&:active": { bgcolor: "#F0FAFB" },
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1, alignItems: "baseline" }}>
        <Typography sx={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.55, textTransform: "uppercase", color: "#64748b" }}>
          {title}
        </Typography>
        <Typography sx={{ fontSize: 12, fontWeight: 700, color: toneColor }}>{statusLabel}</Typography>
      </Box>
      <Typography sx={{ mt: 0.35, fontSize: 22, fontWeight: 900, color: "#007a91", letterSpacing: -0.4 }}>
        {primary == null || primary === "" ? "—" : typeof primary === "number" ? fmtMoney(primary) : primary}
      </Typography>
      {secondary ? (
        <Typography sx={{ mt: 0.25, fontSize: 13, fontWeight: 600, color: "#64748b" }}>{secondary}</Typography>
      ) : null}
    </Box>
  );
}
