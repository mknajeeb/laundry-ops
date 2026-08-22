import { useState } from "react";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { Box, IconButton, Tooltip, Typography } from "@mui/material";
import { createCopyableBagIdPointerHandlers } from "../CopyableBagId";

/**
 * Reusable Management copyable identifier (bag / order ID).
 * Selectable text + copy icon + brief "Copied" feedback.
 * Future-ready for HD / Performance / Bag Search / Analysis.
 */
export default function ManagementCopyableId({
  value,
  label = null,
  empty = "—",
  fontSize = 13,
  fontWeight = 700,
  sx = {},
  stopPropagation = true,
}) {
  const [copied, setCopied] = useState(false);
  const text = String(value || "").trim();

  if (!text) {
    return (
      <Typography component="span" sx={{ fontSize, color: "#94a3b8", ...sx }}>
        {empty}
      </Typography>
    );
  }

  const copy = async (e) => {
    if (stopPropagation) {
      e?.preventDefault?.();
      e?.stopPropagation?.();
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* text remains selectable */
    }
  };

  const pointer = stopPropagation ? createCopyableBagIdPointerHandlers(copy) : { onClick: copy };

  return (
    <Box
      component="span"
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: 0.35,
        maxWidth: "100%",
        ...sx,
      }}
      data-testid="management-copyable-id"
    >
      {label ? (
        <Typography component="span" sx={{ fontSize: 11, color: "#64748b", mr: 0.25 }}>
          {label}
        </Typography>
      ) : null}
      <Tooltip title={copied ? "Copied" : "Click to copy"} placement="top" enterDelay={300}>
        <Typography
          component="span"
          {...pointer}
          role="button"
          tabIndex={0}
          aria-label={`Copy ${text}`}
          sx={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            fontSize,
            fontWeight,
            userSelect: "text",
            cursor: "copy",
            letterSpacing: 0.2,
            color: "#0f172a",
            wordBreak: "break-all",
          }}
        >
          {text}
        </Typography>
      </Tooltip>
      <Tooltip title={copied ? "Copied" : "Copy"} placement="top" enterDelay={300}>
        <IconButton
          size="small"
          aria-label={`Copy ${text}`}
          {...pointer}
          sx={{
            p: 0.35,
            color: copied ? "#059669" : "#64748b",
            "&:hover": { color: "#0f172a", bgcolor: "#f1f5f9" },
          }}
        >
          <ContentCopyIcon sx={{ fontSize: 14 }} />
        </IconButton>
      </Tooltip>
      {copied ? (
        <Typography component="span" sx={{ fontSize: 10, fontWeight: 700, color: "#059669" }}>
          Copied
        </Typography>
      ) : null}
    </Box>
  );
}
