import { Box } from "@mui/material";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

const FALLBACK = "/washpro-mark.png";

/**
 * Tenant logo from profile (`logo_url` / `organization_logo_url`), or shared Washpro mark.
 */
export default function TenantLogo({ logoUrl, size = 40, sx = {} }) {
  const src = logoUrl ? resolveOrgLogoUrl(logoUrl) : FALLBACK;
  return (
    <Box
      component="img"
      src={src}
      alt=""
      onError={(e) => {
        e.currentTarget.src = FALLBACK;
      }}
      sx={{
        width: size,
        height: size,
        flexShrink: 0,
        objectFit: "contain",
        display: "block",
        ...sx,
      }}
    />
  );
}
