import { getWashproApiBase } from "../api";

/**
 * DB/API may still return http://127.0.0.1:8000/... from dev uploads; HTTPS sites cannot load that.
 * Rewrites localhost origins to the configured API base (same host that serves /media/org-logos/...).
 *
 * Also prefixes relative `/media/...` paths with the API origin when the SPA is on another host
 * (e.g. Azure Static Web Apps → laundryops-api for org logos and favicons).
 */
export function resolveOrgLogoUrl(url) {
  if (url == null || url === "") return url;
  let s = String(url).trim();
  if (/^media\//i.test(s) && !s.startsWith("/")) {
    s = `/${s}`;
  }
  const base = String(getWashproApiBase() || "").replace(/\/+$/, "");

  if (base && s.startsWith("/") && /^\/media\//i.test(s)) {
    return `${base}${s}`;
  }

  if (!base) return url;
  if (!/^https?:\/\//i.test(s)) return url;
  try {
    const u = new URL(s);
    const h = u.hostname.toLowerCase();
    const local = h === "127.0.0.1" || h === "localhost" || h === "::1";
    if (!local) return url;
    const rest = `${u.pathname || ""}${u.search || ""}${u.hash || ""}`;
    return `${base}${rest.startsWith("/") ? rest : `/${rest}`}`;
  } catch {
    return url;
  }
}
