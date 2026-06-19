import { useEffect, useState } from "react";
import { Box } from "@mui/material";
import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

/**
 * Tenant logo when `logo_url` / `organization_logo_url` is present and the image loads.
 * Falls back to the bundled VeeWash mark when no tenant logo is configured.
 */
export default function TenantLogo({ logoUrl, size = 40, sx = {} }) {
  const [failed, setFailed] = useState(false);
  const trimmed = logoUrl != null && String(logoUrl).trim() ? String(logoUrl).trim() : "";
  const src = trimmed ? resolveOrgLogoUrl(trimmed) : VEEWASH_LOGO_URL;

  useEffect(() => {
    setFailed(false);
  }, [src]);

  const resolvedSrc = failed ? VEEWASH_LOGO_URL : src;

  return (
    <Box
      component="img"
      src={resolvedSrc}
      alt=""
      onError={() => setFailed(true)}
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
