import { Paper, Typography } from "@mui/material";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import { cardSx, deltaTone, formatDeltaBadge } from "./rinsePerfFormat";

export default function KpiCard({ label, value, delta, hint, compact }) {
  return (
    <Paper variant="outlined" sx={cardSx({ p: compact ? 1 : 1.25, height: "100%" })}>
      <Typography
        variant="caption"
        sx={{
          color: VEEWASH_BRAND.inkSoft,
          letterSpacing: 0.3,
          textTransform: "uppercase",
          fontSize: 10,
        }}
      >
        {label}
      </Typography>
      <Typography
        variant={compact ? "subtitle1" : "h6"}
        fontWeight={800}
        sx={{ color: VEEWASH_BRAND.ink, mt: 0.15, lineHeight: 1.15 }}
      >
        {value}
      </Typography>
      {delta ? (
        <Typography variant="caption" sx={{ color: deltaTone(delta), fontWeight: 600 }}>
          {formatDeltaBadge(delta)}
        </Typography>
      ) : null}
      {hint && !delta ? (
        <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {hint}
        </Typography>
      ) : null}
    </Paper>
  );
}
