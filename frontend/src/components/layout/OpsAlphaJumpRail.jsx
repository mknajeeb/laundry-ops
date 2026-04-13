import { Box, Button, Paper } from "@mui/material";
import { getOpsAlphaPaletteForLetter } from "../../utils/opsAlphaIndex";

/**
 * Sticky horizontal A–Z (or keys) rail: one tap expands that section and scrolls it into view.
 * Letter colors match section headers (palette is keyed by letter, not list position).
 */
export default function OpsAlphaJumpRail({ letters, onPick, ariaLabelFor }) {
  if (!letters?.length) return null;
  return (
    <Paper
      elevation={0}
      sx={{
        display: "flex",
        gap: 0.35,
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
        p: 0.5,
        mb: 0.85,
        borderRadius: 2,
        border: "1px solid rgba(148, 163, 184, 0.4)",
        bgcolor: "rgba(255,255,255,0.92)",
        flexShrink: 0,
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
              minWidth: 36,
              height: 40,
              p: 0,
              flexShrink: 0,
              borderRadius: 1.25,
              fontWeight: 800,
              fontSize: 14,
              lineHeight: 1,
              bgcolor: pal.chipBg,
              color: pal.chipColor,
              boxShadow: "0 1px 4px rgba(15,23,42,0.12)",
              "&:hover": { opacity: 0.92 },
            }}
          >
            <Box component="span" sx={{ mt: 0.1 }}>
              {letter}
            </Box>
          </Button>
        );
      })}
    </Paper>
  );
}
