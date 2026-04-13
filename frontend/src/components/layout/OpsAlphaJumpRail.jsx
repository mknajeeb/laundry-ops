import { Button, Paper } from "@mui/material";
import { getOpsAlphaPaletteForLetter } from "../../utils/opsAlphaIndex";

/**
 * A–Z (and #) jump grid: all letters visible without horizontal scroll — 7 columns × up to 4 rows.
 * Letter colors match section headers (palette keyed by letter).
 */
export default function OpsAlphaJumpRail({ letters, onPick, ariaLabelFor }) {
  if (!letters?.length) return null;
  return (
    <Paper
      elevation={0}
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
        gap: { xs: 0.65, sm: 0.85 },
        p: { xs: 0.9, sm: 1.05 },
        mb: 0.9,
        borderRadius: 2,
        border: "1px solid rgba(148, 163, 184, 0.32)",
        bgcolor: "rgba(255,255,255,0.96)",
        flexShrink: 0,
        boxShadow: "0 1px 8px rgba(15, 23, 42, 0.06)",
      }}
    >
      {letters.map((letter) => {
        const pal = getOpsAlphaPaletteForLetter(letter);
        const label = ariaLabelFor ? ariaLabelFor(letter) : `Letter ${letter}`;
        return (
          <Button
            key={letter}
            aria-label={label}
            onClick={() => onPick(letter)}
            sx={{
              minWidth: 0,
              width: "100%",
              minHeight: { xs: 46, sm: 50 },
              maxHeight: 52,
              p: 0.25,
              flexShrink: 0,
              borderRadius: 1.5,
              fontWeight: 800,
              fontSize: { xs: "1.02rem", sm: "1.08rem" },
              lineHeight: 1,
              letterSpacing: 0.02,
              bgcolor: pal.chipBg,
              color: pal.chipColor,
              boxShadow: "0 2px 6px rgba(15,23,42,0.14)",
              "&:hover": { filter: "brightness(1.06)" },
              "&:active": { transform: "scale(0.97)" },
            }}
          >
            <Box component="span" sx={{ mt: 0.05 }}>
              {letter}
            </Box>
          </Button>
        );
      })}
    </Paper>
  );
}
