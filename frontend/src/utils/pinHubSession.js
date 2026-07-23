/** SessionStorage helpers for /pin/:orgSlug phone hub. */

const SESSION_KEY = "washpro_pin_hub_session";
/** Marks a short Washpro login opened from the phone PIN menu (inventory). */
const APP_SESSION_KEY = "washpro_pin_hub_app_session";

export function loadPinHubSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.token || !parsed?.organization_slug || !parsed?.pin) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function savePinHubSession(session) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* ignore */
  }
}

export function clearPinHubSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

/** Consume one-shot PIN for a feature page (role switch) without clearing the whole hub. */
export function takePinHubPinForSlug(orgSlug) {
  const sess = loadPinHubSession();
  if (!sess) return "";
  const slug = String(orgSlug || "").toLowerCase();
  if (sess.organization_slug !== slug) return "";
  return String(sess.pin || "");
}

export function markPinHubAppSession(orgSlug) {
  try {
    sessionStorage.setItem(
      APP_SESSION_KEY,
      JSON.stringify({
        organization_slug: String(orgSlug || "").toLowerCase(),
        at: Date.now(),
      }),
    );
  } catch {
    /* ignore */
  }
}

export function loadPinHubAppSession() {
  try {
    const raw = sessionStorage.getItem(APP_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.organization_slug) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearPinHubAppSession() {
  try {
    sessionStorage.removeItem(APP_SESSION_KEY);
  } catch {
    /* ignore */
  }
}

export function isPinHubAppSessionActive() {
  return !!loadPinHubAppSession();
}

export function pinHubMenuPath(orgSlug) {
  const slug = String(orgSlug || "").trim().toLowerCase();
  return slug ? `/pin/${encodeURIComponent(slug)}` : "/pin";
}
