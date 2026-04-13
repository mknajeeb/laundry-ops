/**
 * OneSignal External User ID — must match backend/onesignal_client.external_user_id().
 * Uses the same `id` and `organization_id` as GET /api/ta/auth/me.
 */

const ONESIGNAL_APP_ID = import.meta.env.VITE_ONESIGNAL_APP_ID;
const ONESIGNAL_DISABLED =
  import.meta.env.VITE_ONESIGNAL_DISABLED === "true" ||
  import.meta.env.VITE_ONESIGNAL_DISABLED === "1";

/** Match main.jsx: dashboard allowlist often blocks localhost; avoid queued SDK calls after login. */
function skipLocalOneSignal() {
  if (!import.meta.env.DEV || typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h === "localhost" || h === "127.0.0.1";
}

export function buildOneSignalExternalUserId(user) {
  if (!user || user.id == null || user.id === undefined) return null;
  const org = Number(user.organization_id ?? 1);
  const uid = Number(user.id);
  if (!Number.isFinite(org) || !Number.isFinite(uid)) return null;
  return `lo-${org}-${uid}`;
}

function deferredPush(fn) {
  window.OneSignalDeferred = window.OneSignalDeferred || [];
  window.OneSignalDeferred.push(fn);
}

/**
 * After TA user is known (post login / refreshMe). Links this browser to the DB user for targeted push.
 */
export function syncOneSignalUser(user) {
  if (!ONESIGNAL_APP_ID || ONESIGNAL_DISABLED) return;
  const externalId = buildOneSignalExternalUserId(user);
  if (!externalId) return;

  deferredPush(async function linkUser(OneSignal) {
    try {
      if (!OneSignal || typeof OneSignal.login !== "function") return;
      await OneSignal.login(externalId);
    } catch (e) {
      console.warn("OneSignal.login failed", e);
    }
  });
}

/**
 * On logout — unlink so the next account on this device does not receive the previous user's pushes.
 */
export function clearOneSignalUser() {
  if (!ONESIGNAL_APP_ID || ONESIGNAL_DISABLED || skipLocalOneSignal()) return;

  deferredPush(async function unlinkUser(OneSignal) {
    try {
      if (!OneSignal || typeof OneSignal.logout !== "function") return;
      await OneSignal.logout();
    } catch (e) {
      console.warn("OneSignal.logout failed", e);
    }
  });
}
