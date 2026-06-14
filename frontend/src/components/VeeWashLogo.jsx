import { Box } from "@mui/material";
import veewashLogo from "../assets/veewash-logo.png";

/** Bundled VeeWash mark — PNG with transparent background. */
export default function VeeWashLogo({ height = 40, sx = {} }) {
  return (
    <Box
      component="img"
      src={veewashLogo}
      alt="VeeWash"
      sx={{
        height,
        width: "auto",
        maxWidth: height * 2.2,
        objectFit: "contain",
        display: "block",
        flexShrink: 0,
        ...sx,
      }}
    />
  );
}
