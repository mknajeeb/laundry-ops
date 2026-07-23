import { Box } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { OPS_MOBILE } from "./tokens";

/**
 * Sticky bottom (or top) action strip for Submit / primary actions.
 * Respects safe-area insets; does not use page-level overflow:hidden.
 */
export default function OpsStickyActionBar({ children, edge = "bottom", sx = {} }) {
  const isBottom = edge !== "top";
  return (
    <Box
      sx={{
        position: "sticky",
        [isBottom ? "bottom" : "top"]: 0,
        zIndex: 3,
        width: "100%",
        bgcolor: alpha("#fff", 0.94),
        backdropFilter: "blur(10px)",
        pt: isBottom ? 1.25 : `max(8px, ${OPS_MOBILE.safeTop})`,
        pb: isBottom ? `max(12px, ${OPS_MOBILE.safeBottom})` : 1.25,
        mt: isBottom ? "auto" : 0,
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}
