import { Box } from "@mui/material";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";

/** Bundled VeeWash mark — PNG with transparent background. */
export default function VeeWashLogo({ height = 40, sx = {} }) {
  return (
    <Box
      component="img"
      src={VEEWASH_LOGO_URL}
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
