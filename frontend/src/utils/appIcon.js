import { resolveOrgLogoUrl } from "./resolveOrgLogoUrl";

/** Unbranded slate tile when no tenant logo (matches `index.html` defaults). */
const NEUTRAL = "/neutral-app-icon.svg";

/**
 * Set tab / home-screen icons to the tenant organization logo when available.
 * With no tenant logo, use a neutral icon — not a Laundry Ops mark.
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
      svgEl.href = NEUTRAL;
      svgEl.type = "image/svg+xml";
    }
    if (pngEl) {
      pngEl.href = NEUTRAL;
      pngEl.type = "image/svg+xml";
    }
    if (appleEl) {
      appleEl.href = NEUTRAL;
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
