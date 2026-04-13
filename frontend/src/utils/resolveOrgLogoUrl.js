import { getWashproApiBase } from "../api";

/**
 * DB/API may still return http://127.0.0.1:8000/... from dev uploads; HTTPS sites cannot load that.
 * Rewrites localhost origins to the configured API base (same host that serves /media/org-logos/...).
 */
export function resolveOrgLogoUrl(url) {
  if (url == null || url === "") return url;
  const base = getWashproApiBase();
  if (!base) return url;
  const s = String(url).trim();
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
