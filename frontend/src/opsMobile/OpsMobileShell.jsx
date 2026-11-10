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
          height: "100%",
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          px: 1.5,
          pt: `max(12px, env(safe-area-inset-top, 0px))`,
          pb: `max(8px, env(safe-area-inset-bottom, 0px))`,
        }}
      >
        {showLocaleToggle ? (
          <Box sx={{ display: "flex", justifyContent: "flex-end", flexShrink: 0 }}>
            <OpsLocaleToggle />
          </Box>
        ) : null}
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
            overflowX: "hidden",
            WebkitOverflowScrolling: "touch",
            display: "flex",
            flexDirection: "column",
            gap: 1.25,
            ...contentSx,
          }}
        >
          {children}
        </Box>
      </Box>
    </Box>
  );
}
