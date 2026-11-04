import { useState } from "react";
import { Box, IconButton, Popover, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

/**
 * Instructions stay on the info icon. Desktop hover or click, and mobile tap,
 * open an anchored popover that wraps long text beside that control.
 */
export default function InstructionHint({ text, label = "Instructions" }) {
  const [anchor, setAnchor] = useState(null);
  const [pinned, setPinned] = useState(false);
  const value = String(text || "").trim();
  if (!value) return null;
  const close = () => {
    setPinned(false);
    setAnchor(null);
  };
  return (
    <Box
      component="span"
      sx={{ display: "inline-flex" }}
      onMouseEnter={(event) => setAnchor(event.currentTarget)}
      onMouseLeave={() => {
        if (!pinned) setAnchor(null);
      }}
    >
      <IconButton
        size="small"
        aria-label={label}
        aria-expanded={Boolean(anchor)}
        onClick={(event) => {
          event.stopPropagation();
          setPinned((open) => !open);
          setAnchor(event.currentTarget);
        }}
      >
        <InfoOutlinedIcon fontSize="small" />
      </IconButton>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        transformOrigin={{ vertical: "top", horizontal: "left" }}
        disableRestoreFocus
        slotProps={{
          paper: {
            sx: { maxWidth: 320, p: 1.25 },
          },
        }}
      >
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {value}
        </Typography>
      </Popover>
    </Box>
  );
}
