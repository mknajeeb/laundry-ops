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

/** Shared kiosk unlock must not keep a management push identity on that device. */
export function isSharedKioskPath(pathname) {
  const p = String(pathname || "");
  return p === "/kiosk" || p.startsWith("/kiosk/");
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
 * The person who just entered a PIN becomes this phone's push identity.
 * A different PIN replaces the previous id. Issue-review access does not
 * decide the link. Lock, session expiry, and a missing identity do not log out.
 */
export function pinPushAssociation(body) {
  const id = Number(body?.employee_id);
  const org = Number(body?.organization_id);
  if (!Number.isFinite(id) || id <= 0 || !Number.isFinite(org) || org <= 0) {
    return { action: "skip" };
  }
  return { action: "link", user: { id, organization_id: org } };
}

/** Status only. Never include the external id or subscription id. */
export function phoneRegistrationState({
  externalId,
  expectedExternalId,
  subscriptionId,
  optedIn,
} = {}) {
  if (!expectedExternalId) return "unavailable";
  if (externalId === expectedExternalId && subscriptionId && optedIn === true) {
    return "registered";
  }
  return "not_registered";
}

function readSdkRegistration(OneSignal, externalId) {
  const sub = OneSignal?.User?.PushSubscription;
  return phoneRegistrationState({
    externalId: OneSignal?.User?.externalId,
    expectedExternalId: externalId,
    subscriptionId: sub?.id,
    optedIn: sub?.optedIn,
  });
}

/**
 * Link this phone, then report whether the SDK's identity and push
 * subscription match. Resolves "unavailable" when OneSignal is not in use.
 */
export function applyPinPushAssociation(body) {
  const decision = pinPushAssociation(body);
  if (decision.action !== "link") return Promise.resolve("unavailable");
  return registerPhoneForPush(decision.user);
}

export function registerPhoneForPush(user) {
  const externalId = buildOneSignalExternalUserId(user);
  if (!ONESIGNAL_APP_ID || ONESIGNAL_DISABLED || skipLocalOneSignal() || !externalId) {
    return Promise.resolve("unavailable");
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve("not_registered"), 8000);
    deferredPush(async function linkUser(OneSignal) {
      clearTimeout(timer);
      try {
        if (!OneSignal || typeof OneSignal.login !== "function") {
          resolve("not_registered");
          return;
        }
        await OneSignal.login(externalId);
        resolve(readSdkRegistration(OneSignal, externalId));
      } catch (e) {
        console.warn("OneSignal.login failed", e);
        resolve("not_registered");
      }
    });
  });
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
