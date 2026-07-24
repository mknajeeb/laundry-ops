import { Box, Button, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";

/**
 * Compact employee checklist row — heading, short description, Complete / Completed.
 * No decorative icons. No large completion banners.
 */
export default function OpsTaskCard({
  title,
  instruction = "",
  completed = false,
  readOnly = false,
  busy = false,
  onComplete,
  onUndo,
}) {
  const text = String(instruction || "").trim();

  return (
    <Box
      sx={{
        width: "100%",
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        bgcolor: alpha("#fff", 0.98),
        px: 1.25,
        py: 1,
        boxShadow: `0 1px 0 ${alpha(OPS_MOBILE.navy, 0.06)}`,
      }}
    >
      <Typography
        sx={{
          fontWeight: 800,
          fontSize: { xs: "1rem", sm: "1.05rem" },
          lineHeight: 1.25,
          color: OPS_MOBILE.navy,
          wordBreak: "break-word",
        }}
      >
        {title}
      </Typography>
      {text ? (
        <Typography
          sx={{
            mt: 0.35,
            fontWeight: 600,
            fontSize: "0.8rem",
            lineHeight: 1.3,
            color: OPS_MOBILE.muted,
            wordBreak: "break-word",
          }}
        >
          {text}
        </Typography>
      ) : null}

      {!readOnly ? (
        <Button
          fullWidth
          disabled={busy}
          onClick={() => (completed ? onUndo?.() : onComplete?.())}
          aria-label={completed ? `Undo ${title}` : `Complete ${title}`}
          sx={{
            mt: 1,
            minHeight: 48,
            textTransform: "none",
            fontWeight: 800,
            fontSize: "1rem",
            borderRadius: 2,
            color: completed ? OPS_MOBILE.navy : "#fff",
            bgcolor: completed ? alpha(OPS_MOBILE.navy, 0.08) : OPS_MOBILE.cobalt,
            "&:hover": {
              bgcolor: completed ? alpha(OPS_MOBILE.navy, 0.12) : alpha(OPS_MOBILE.cobalt, 0.9),
            },
          }}
        >
          {completed ? "Completed" : "Complete"}
        </Button>
      ) : null}
    </Box>
  );
}
