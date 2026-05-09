import { resolveOrgLogoUrl } from "./resolveOrgLogoUrl";

/** Static defaults built into `index.html` — LO on black. */
const DEFAULT = {
  svg: "/lo-mark.svg",
  png192: "/icon-192.png",
  apple: "/apple-touch-icon.png",
};

/**
 * Set tab / home-screen icons to the tenant organization logo when available,
 * otherwise restore Laundry Ops "LO" marks (`/lo-mark.svg`, PNG icons).
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
      svgEl.href = DEFAULT.svg;
      svgEl.type = "image/svg+xml";
    }
    if (pngEl) {
      pngEl.href = DEFAULT.png192;
      pngEl.type = "image/png";
    }
    if (appleEl) appleEl.href = DEFAULT.apple;
    return;
  }

  const isSvg = /\.svg(\?|;|#|$)/i.test(tenant);

  if (isSvg) {
    if (svgEl) {
      svgEl.href = tenant;
      svgEl.type = "image/svg+xml";
    }
    if (pngEl) {
      pngEl.href = DEFAULT.png192;
      pngEl.type = "image/png";
    }
    if (appleEl) appleEl.href = DEFAULT.apple;
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
