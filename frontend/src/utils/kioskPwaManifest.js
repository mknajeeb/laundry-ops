/**
 * Kiosk / phone PIN unlock PWA (e.g. Inventory deep-link).
 * Separate from attendance punch + main Laundry Ops manifests.
 */

const MAIN_MANIFEST = "/manifest.webmanifest";
const MAIN_TITLE = "Laundry Ops";
const MAIN_THEME = "#111827";
const KIOSK_THEME = "#0e7490";

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

function orgDisplayName(slug) {
  if (slug === "veewash") return "VeeWash";
  if (slug === "washpro") return "Washpro";
  return "";
}

export function kioskManifestHref(orgSlug, mode = "inventory") {
  const slug = sanitizeSlug(orgSlug);
  const infix = mode === "inventory" ? "-inventory" : "";
  if (!slug) return `/kiosk-manifests/default${infix}.webmanifest`;
  return `/kiosk-manifests/${slug}${infix}.webmanifest`;
}

function displayTitle(orgSlug, mode = "inventory") {
  const slug = sanitizeSlug(orgSlug);
  const org = orgDisplayName(slug);
  const suffix = mode === "inventory" ? "Inventory" : "PIN Unlock";
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
 * @param {string} orgSlug
 * @param {"inventory"} [mode="inventory"]
 * @returns cleanup restores main app manifest
 */
export function applyKioskPwaManifest(orgSlug, mode = "inventory") {
  const manifestHref = kioskManifestHref(orgSlug, mode);
  const title = displayTitle(orgSlug, mode);

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
  setMeta("theme-color", KIOSK_THEME);
  setMeta("apple-mobile-web-app-title", title.slice(0, 32));

  return () => {
    link.href = prev.manifest;
    document.title = prev.title;
    setMeta("theme-color", prev.theme);
    setMeta("apple-mobile-web-app-title", prev.appleTitle);
  };
}
