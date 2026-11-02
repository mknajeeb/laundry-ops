import { useState } from "react";
import { Box, Collapse, IconButton, Tooltip, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

/**
 * Compact instructions. Hover shows the text on desktop. Click or tap pins it open.
 */
export default function InstructionHint({ text, label = "Instructions" }) {
  const [pinned, setPinned] = useState(false);
  const value = String(text || "").trim();
  if (!value) return null;
  return (
    <Box sx={{ display: "inline-flex", flexDirection: "column", maxWidth: "100%" }}>
      <Tooltip title={value} placement="top" enterTouchDelay={0} leaveTouchDelay={4000} arrow>
        <IconButton
          size="small"
          aria-label={label}
          aria-expanded={pinned}
          onClick={(event) => {
            event.stopPropagation();
            setPinned((open) => !open);
          }}
        >
          <InfoOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Collapse in={pinned}>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", mt: 0.25 }}>
          {value}
        </Typography>
      </Collapse>
    </Box>
  );
}
