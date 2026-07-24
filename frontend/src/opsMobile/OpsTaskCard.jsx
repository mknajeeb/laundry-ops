import { Box, Button, IconButton, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckIcon from "@mui/icons-material/Check";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import UndoIcon from "@mui/icons-material/Undo";
import { useState } from "react";
import { OPS_MOBILE } from "./tokens";

/**
 * Employee checklist task card — explicit Complete/Undo control (not whole-card tap).
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
  const [expanded, setExpanded] = useState(false);
  const text = String(instruction || "").trim();
  const long = text.length > 72;
  const shown = !text ? "" : long && !expanded ? `${text.slice(0, 72).trim()}…` : text;

  return (
    <Box
      sx={{
        width: "100%",
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        bgcolor: completed ? alpha(OPS_MOBILE.success, 0.08) : alpha("#fff", 0.98),
        px: 1.75,
        py: 1.5,
        opacity: completed && !readOnly ? 0.92 : 1,
        boxShadow: completed ? "none" : `0 1px 0 ${alpha(OPS_MOBILE.navy, 0.06)}`,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.25, width: "100%" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: { xs: "1.1rem", sm: "1.15rem" },
              lineHeight: 1.3,
              color: completed ? alpha(OPS_MOBILE.navy, 0.72) : OPS_MOBILE.navy,
              whiteSpace: "normal",
              wordBreak: "break-word",
              overflowWrap: "anywhere",
            }}
          >
            {completed ? `✓ ${title}` : title}
          </Typography>
          {shown ? (
            <Box sx={{ mt: 0.75 }}>
              <Typography
                sx={{
                  fontWeight: 600,
                  fontSize: "0.9rem",
                  color: OPS_MOBILE.muted,
                  whiteSpace: "normal",
                  wordBreak: "break-word",
                }}
              >
                {shown}
              </Typography>
              {long ? (
                <Button
                  size="small"
                  onClick={() => setExpanded((v) => !v)}
                  endIcon={
                    <ExpandMoreIcon
                      sx={{ transform: expanded ? "rotate(180deg)" : "none", transition: "0.15s" }}
                    />
                  }
                  sx={{
                    mt: 0.25,
                    px: 0.5,
                    minHeight: 40,
                    textTransform: "none",
                    fontWeight: 800,
                    color: OPS_MOBILE.blue,
                  }}
                >
                  {expanded ? "Less" : "More"}
                </Button>
              ) : null}
            </Box>
          ) : null}
        </Box>

        {!readOnly ? (
          completed ? (
            <IconButton
              aria-label={`Undo ${title}`}
              disabled={busy}
              onClick={() => onUndo?.()}
              sx={{
                flexShrink: 0,
                width: 56,
                height: 56,
                borderRadius: 2,
                bgcolor: alpha(OPS_MOBILE.navy, 0.06),
                color: OPS_MOBILE.navy,
              }}
            >
              <UndoIcon />
            </IconButton>
          ) : (
            <Button
              aria-label={`Complete ${title}`}
              disabled={busy}
              onClick={() => onComplete?.()}
              startIcon={<CheckIcon />}
              sx={{
                flexShrink: 0,
                minHeight: 56,
                minWidth: 112,
                px: 1.5,
                borderRadius: `${OPS_MOBILE.radius.button}px`,
                textTransform: "none",
                fontWeight: 900,
                fontSize: "0.95rem",
                bgcolor: alpha(OPS_MOBILE.cobalt, 0.14),
                color: OPS_MOBILE.navy,
                "&:hover": { bgcolor: alpha(OPS_MOBILE.cobalt, 0.22) },
              }}
            >
              Complete
            </Button>
          )
        ) : completed ? (
          <Box
            aria-hidden
            sx={{
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              bgcolor: alpha(OPS_MOBILE.success, 0.16),
              color: OPS_MOBILE.success,
            }}
          >
            <CheckIcon />
          </Box>
        ) : null}
      </Box>
    </Box>
  );
}
