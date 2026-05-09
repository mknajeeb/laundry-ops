import { authLogout, clearAuthSession } from "../api";

/**
 * End Washpro/TA session and open the PIN kiosk for this tenant (shared-tablet flow).
 */
export async function lockSessionToKiosk(slugOverride) {
  try {
    await authLogout();
  } catch {
    /* ignore */
  }
  clearAuthSession();
  try {
    localStorage.removeItem("ta_token");
  } catch {
    /* ignore */
  }
  let slug = String(slugOverride || "").trim().toLowerCase();
  if (!slug) {
    try {
      slug = (localStorage.getItem("washpro_org_slug") || "").trim().toLowerCase();
    } catch {
      slug = "";
    }
  }
  window.location.assign(slug ? `/kiosk/${encodeURIComponent(slug)}` : "/login");
}
