import { useState } from "react";
import { Tooltip, Typography } from "@mui/material";

/**
 * Pointer/keyboard handlers that copy without toggling parent accordion/row clicks.
 * Exported for unit tests.
 */
export function createCopyableBagIdPointerHandlers(copyFn) {
  return {
    onClick: (e) => {
      e?.preventDefault?.();
      e?.stopPropagation?.();
      return copyFn(e);
    },
    onMouseDown: (e) => {
      e?.stopPropagation?.();
    },
    onKeyDown: (e) => {
      if (e?.key === "Enter" || e?.key === " ") {
        e.preventDefault?.();
        e.stopPropagation?.();
        return copyFn(e);
      }
    },
  };
}

/**
 * Bag / order ID that can be selected or click-copied.
 * Stops accordion/row click handlers so copy/select does not expand or navigate.
 */
export default function CopyableBagId({
  bagId,
  variant = "body2",
  fontWeight = 700,
  sx = {},
  empty = "—",
}) {
  const [copied, setCopied] = useState(false);
  const value = String(bagId || "").trim();

  if (!value) {
    return (
      <Typography component="span" variant={variant} color="text.secondary" sx={sx}>
        {empty}
      </Typography>
    );
  }

  const copy = async (e) => {
    e?.preventDefault?.();
    e?.stopPropagation?.();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const ta = document.createElement("textarea");
        ta.value = value;
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
      /* leave text selectable as fallback */
    }
  };

  const pointer = createCopyableBagIdPointerHandlers(copy);

  return (
    <Tooltip title={copied ? "Copied" : "Click to copy"} placement="top" enterDelay={400}>
      <Typography
        component="span"
        variant={variant}
        {...pointer}
        role="button"
        tabIndex={0}
        aria-label={`Copy bag ID ${value}`}
        sx={{
          fontFamily: "monospace",
          fontWeight,
          userSelect: "text",
          cursor: "copy",
          letterSpacing: 0.2,
          ...sx,
        }}
      >
        {value}
      </Typography>
    </Tooltip>
  );
}
