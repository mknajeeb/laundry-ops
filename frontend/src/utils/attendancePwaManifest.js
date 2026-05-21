/**
 * Attendance kiosk PWA: separate manifest from main Laundry Ops app so
 * "Add to Home screen" opens /attendance/:slug, not /login.
 */

const MAIN_MANIFEST = "/manifest.webmanifest";
const MAIN_TITLE = "Laundry Ops";
const MAIN_THEME = "#111827";

const ATTENDANCE_THEME = "#2d3d9c";

function sanitizeSlug(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

/** Manifest href for this tenant slug (veewash uses primary attendance.manifest.webmanifest). */
export function attendanceManifestHref(orgSlug) {
  const slug = sanitizeSlug(orgSlug);
  if (slug === "veewash") return "/attendance.manifest.webmanifest";
  if (!slug) return "/attendance-manifests/default.webmanifest";
  return `/attendance-manifests/${slug}.webmanifest`;
}

function displayTitle(orgSlug) {
  const slug = sanitizeSlug(orgSlug);
  if (slug === "veewash") return "VeeWash Attendance";
  if (slug === "washpro") return "Washpro Attendance";
  return "Attendance";
}

function setMeta(name, content) {
  let el = document.querySelector(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute("name", name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

/**
 * Swap document manifest + title for attendance routes only.
 * @returns cleanup restores main app manifest
 */
export function applyAttendancePwaManifest(orgSlug) {
  const manifestHref = attendanceManifestHref(orgSlug);
  const title = displayTitle(orgSlug);

  let link = document.querySelector('link[rel="manifest"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "manifest";
    document.head.appendChild(link);
  }

  const prev = {
    manifest: link.getAttribute("href") || MAIN_MANIFEST,
    title: document.title,
    theme: document.querySelector('meta[name="theme-color"]')?.getAttribute("content") || MAIN_THEME,
    appleTitle:
      document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute("content") ||
      MAIN_TITLE,
  };

  link.href = manifestHref;
  document.title = title;
  setMeta("theme-color", ATTENDANCE_THEME);
  setMeta("apple-mobile-web-app-title", title.slice(0, 32));

  return () => {
    link.href = prev.manifest;
    document.title = prev.title;
    setMeta("theme-color", prev.theme);
    setMeta("apple-mobile-web-app-title", prev.appleTitle);
  };
}
