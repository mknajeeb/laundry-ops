import { useEffect, useState } from "react";
import { Box } from "@mui/material";
import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";

/**
 * Tenant logo when `logo_url` / `organization_logo_url` is present and the image loads.
 * Renders nothing if missing or on load error (no generic app mark).
 */
export default function TenantLogo({ logoUrl, size = 40, sx = {} }) {
  const [failed, setFailed] = useState(false);
  const trimmed = logoUrl != null && String(logoUrl).trim() ? String(logoUrl).trim() : "";
  const src = trimmed ? resolveOrgLogoUrl(trimmed) : null;

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return null;
  }

  return (
    <Box
      component="img"
      src={src}
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
