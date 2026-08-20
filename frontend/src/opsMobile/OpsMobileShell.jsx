import { Box } from "@mui/material";
import OpsLocaleToggle from "./OpsLocaleToggle";
import { opsMobilePageSx } from "./tokens";

/**
 * Full-viewport ops mobile page shell.
 * Avoids page-level overflow:hidden so content can grow with keyboard / large text.
 */
export default function OpsMobileShell({
  children,
  maxWidth = 420,
  sx = {},
  contentSx = {},
  showLocaleToggle = false,
}) {
  return (
    <Box sx={{ ...opsMobilePageSx, display: "flex", justifyContent: "center", ...sx }}>
      <Box
        sx={{
          width: "100%",
          maxWidth,
          display: "flex",
          flexDirection: "column",
          gap: 2,
          ...contentSx,
        }}
      >
        {showLocaleToggle ? (
          <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
            <OpsLocaleToggle />
          </Box>
        ) : null}
        {children}
      </Box>
    </Box>
  );
}
