/**
 * PIN feature PWAs: separate manifests from main Laundry Ops app so
 * "Add to Home screen" opens the intended PIN page, not /login.
 *
 * Modes:
 * - punch: shared-tablet clock in/out only
 * - role: mobile switch-role PIN
 * - maintenance: end-of-day / maintenance checklist PIN
 * - hub: phone PIN menu
 *
 * VeeWash uses root-level *.manifest.webmanifest files (same pattern as
 * attendance.manifest.webmanifest) so Azure SWA serves them reliably.
 */

const MAIN_MANIFEST = "/manifest.webmanifest";
const MAIN_TITLE = "Laundry Ops";
const MAIN_THEME = "#111827";

const ATTENDANCE_THEME = "#2d3d9c";

const MODE_META = {
  punch: {
    shortName: "Attendance",
    titleSuffix: "Attendance",
    description: "Clock in and out with your attendance PIN.",
    pathPrefix: (slug) => (slug ? `/attendance/${slug}` : "/attendance"),
    fileInfix: "",
  },
  role: {
    shortName: "Switch Role",
    titleSuffix: "Switch Role",
    description: "Switch your shift role with your attendance PIN.",
    pathPrefix: (slug) => (slug ? `/attendance/role/${slug}` : "/attendance/role"),
    fileInfix: "-role",
  },
  maintenance: {
    shortName: "Checklist",
    titleSuffix: "Checklist",
    description: "Complete end-of-day checklist with your attendance PIN.",
    pathPrefix: (slug) =>
      slug ? `/attendance/maintenance/${slug}` : "/attendance/maintenance",
    fileInfix: "-maintenance",
  },
  hub: {
    shortName: "PIN Menu",
    titleSuffix: "PIN Menu",
    description: "Switch role, checklist, and inventory with your attendance PIN.",
    pathPrefix: (slug) => (slug ? `/pin/${slug}` : "/pin"),
    fileInfix: "-hub",
  },
};

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

function normalizeMode(mode) {
  if (mode === "role" || mode === "maintenance" || mode === "hub") return mode;
  return "punch";
}

function orgDisplayName(slug) {
  if (slug === "veewash") return "VeeWash";
  if (slug === "washpro") return "Washpro";
  return "";
}

/** Manifest href for this tenant slug + PIN feature mode. */
export function attendanceManifestHref(orgSlug, mode = "punch") {
  const slug = sanitizeSlug(orgSlug);
  const m = normalizeMode(mode);
  const infix = MODE_META[m].fileInfix;

  // VeeWash: root-level manifests (deployed reliably like attendance.manifest.webmanifest).
  if (slug === "veewash") {
    if (m === "punch") return "/attendance.manifest.webmanifest";
    if (m === "role") return "/attendance-role.manifest.webmanifest";
    if (m === "maintenance") return "/attendance-maintenance.manifest.webmanifest";
    if (m === "hub") return "/pin.manifest.webmanifest";
  }

  if (m === "hub") {
    if (!slug) return "/pin-manifests/default.webmanifest";
    return `/pin-manifests/${slug}.webmanifest`;
  }

  if (m === "punch") {
    if (!slug) return "/attendance-manifests/default.webmanifest";
    return `/attendance-manifests/${slug}.webmanifest`;
  }

  if (!slug) return `/attendance-manifests/default${infix}.webmanifest`;
  return `/attendance-manifests/${slug}${infix}.webmanifest`;
}

function displayTitle(orgSlug, mode = "punch") {
  const slug = sanitizeSlug(orgSlug);
  const m = normalizeMode(mode);
  const org = orgDisplayName(slug);
  const suffix = MODE_META[m].titleSuffix;
  return org ? `${org} ${suffix}` : suffix;
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
 * Replace manifest <link> entirely so browsers re-read start_url
 * (setting .href alone is often ignored after first parse).
 */
function setManifestHref(href) {
  const next = String(href || MAIN_MANIFEST);
  const prev = document.querySelector('link[rel="manifest"]');
  const link = document.createElement("link");
  link.id = "app-manifest";
  link.rel = "manifest";
  link.href = next;
  if (prev && prev.parentNode) {
    prev.parentNode.replaceChild(link, prev);
  } else {
    document.head.appendChild(link);
  }
  return link;
}

/**
 * Swap document manifest + title for PIN feature routes.
 * @param {string} orgSlug
 * @param {"punch"|"role"|"maintenance"|"hub"} [mode="punch"]
 * @returns cleanup restores main app manifest
 */
export function applyAttendancePwaManifest(orgSlug, mode = "punch") {
  const manifestHref = attendanceManifestHref(orgSlug, mode);
  const title = displayTitle(orgSlug, mode);

  const prevLink = document.querySelector('link[rel="manifest"]');
  const prev = {
    manifest: prevLink?.getAttribute("href") || MAIN_MANIFEST,
    title: document.title,
    theme: document.querySelector('meta[name="theme-color"]')?.getAttribute("content") || MAIN_THEME,
    appleTitle:
      document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute("content") ||
      MAIN_TITLE,
  };

  setManifestHref(manifestHref);
  document.title = title;
  setMeta("theme-color", ATTENDANCE_THEME);
  setMeta("apple-mobile-web-app-title", title.slice(0, 32));

  return () => {
    setManifestHref(prev.manifest);
    document.title = prev.title;
    setMeta("theme-color", prev.theme);
    setMeta("apple-mobile-web-app-title", prev.appleTitle);
  };
}

/**
 * Sync path → manifest before React (also inlined in index.html).
 * Exported for tests / reuse.
 */
export function manifestHrefForPathname(pathname) {
  const p = String(pathname || "");
  const m = p.match(/^\/attendance\/maintenance\/([^/]+)\/?$/i);
  if (m) return attendanceManifestHref(m[1], "maintenance");
  const r = p.match(/^\/attendance\/role\/([^/]+)\/?$/i);
  if (r) return attendanceManifestHref(r[1], "role");
  const pin = p.match(/^\/pin\/([^/]+)\/?$/i);
  if (pin) return attendanceManifestHref(pin[1], "hub");
  if (p === "/pin") return attendanceManifestHref("", "hub");
  const a = p.match(/^\/attendance\/([^/]+)\/?$/i);
  if (a && a[1] !== "role" && a[1] !== "maintenance") {
    return attendanceManifestHref(a[1], "punch");
  }
  if (p === "/attendance") return attendanceManifestHref("", "punch");
  return MAIN_MANIFEST;
}
