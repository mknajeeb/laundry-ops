/** Notification tap → existing PIN Issues report. Query values stay inside this app. */

const REPORT_KEY = /^(employee|rinse):[1-9]\d*$/;

export function reportKeyFromSearch(search) {
  const raw = String(search || "").replace(/^\?/, "");
  const report = new URLSearchParams(raw).get("report") || "";
  return REPORT_KEY.test(report) ? report : "";
}

/** Allow only the Issues screen, optionally opened on one report. */
export function safePinIssuesPath(raw) {
  if (!raw || typeof raw !== "string") return "";
  let path = raw.trim();
  if (!path) return "";
  try {
    path = decodeURIComponent(path);
  } catch {
    return "";
  }
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://") || path.includes("\\")) {
    return "";
  }
  const hashAt = path.indexOf("#");
  if (hashAt !== -1) path = path.slice(0, hashAt);
  const qIndex = path.indexOf("?");
  const bare = qIndex === -1 ? path : path.slice(0, qIndex);
  if (bare !== "/pin-issues") return "";
  const report = qIndex === -1 ? "" : reportKeyFromSearch(path.slice(qIndex + 1));
  return report ? `/pin-issues?report=${report}` : "/pin-issues";
}
