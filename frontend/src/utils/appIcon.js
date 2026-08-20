import { resolveOrgLogoUrl } from "./resolveOrgLogoUrl";

/** Default VeeWash home-screen / favicon set (versioned; replaces legacy LO mark). */
const DEFAULT_FAVICON = "/icons/veewash-favicon-32-v2.png";
const DEFAULT_PNG = "/icons/veewash-icon-192-v2.png";
const DEFAULT_APPLE = "/icons/veewash-apple-touch-180-v2.png";

/**
 * Set tab / home-screen icons to the tenant organization logo when available.
 * With no tenant logo, use the VeeWash icon set — never the legacy LO mark.
 */
export function applyAppIconFromOrganizationLogo(logoUrl) {
  if (typeof document === "undefined") return;

  const svgEl = document.getElementById("app-icon-svg");
  const pngEl = document.getElementById("app-icon-png");
  const appleEl = document.getElementById("app-icon-apple");

  const raw =
    logoUrl != null && String(logoUrl).trim()
      ? resolveOrgLogoUrl(String(logoUrl).trim())
      : null;
  const tenant = raw && String(raw).trim() ? String(raw).trim() : null;

  if (!tenant) {
    if (svgEl) {
      svgEl.href = DEFAULT_FAVICON;
      svgEl.type = "image/png";
    }
    if (pngEl) {
      pngEl.href = DEFAULT_PNG;
      pngEl.type = "image/png";
    }
    if (appleEl) {
      appleEl.href = DEFAULT_APPLE;
    }
    return;
  }

  const isSvg = /\.svg(\?|;|#|$)/i.test(tenant);

  if (isSvg) {
    if (svgEl) {
      svgEl.href = tenant;
      svgEl.type = "image/svg+xml";
    }
    if (pngEl) {
      pngEl.href = tenant;
      pngEl.type = "image/svg+xml";
    }
    if (appleEl) appleEl.href = tenant;
  } else {
    /** Raster tenant logo — same URL on svg/png/apple so tab + iOS home screen match the tenant. */
    if (svgEl) {
      svgEl.href = tenant;
      svgEl.removeAttribute("type");
    }
    if (pngEl) {
      pngEl.href = tenant;
      pngEl.type = "image/png";
    }
    if (appleEl) appleEl.href = tenant;
  }
}
