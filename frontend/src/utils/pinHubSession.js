/** SessionStorage helpers for /pin/:orgSlug phone hub. */

const SESSION_KEY = "washpro_pin_hub_session";

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
