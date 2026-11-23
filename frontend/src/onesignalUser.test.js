import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { pinPushAssociation } from "./onesignalUser";

const root = dirname(fileURLToPath(import.meta.url));

function src(name) {
  return readFileSync(join(root, name), "utf8");
}

function block(text, signature) {
  const start = text.indexOf(signature);
  expect(start).toBeGreaterThan(-1);
  return text.slice(start, start + 700);
}

describe("PIN push association", () => {
  it("links an authorized reviewer and replaces the previous person", () => {
    expect(
      pinPushAssociation({
        employee_id: 15,
        organization_id: 3,
        features: { issues: { allowed: true } },
      }),
    ).toEqual({ action: "link", user: { id: 15, organization_id: 3 } });
    expect(
      pinPushAssociation({
        employee_id: 41,
        organization_id: 3,
        is_system: true,
        features: { issues: { allowed: true } },
      }),
    ).toEqual({ action: "link", user: { id: 41, organization_id: 3 } });
  });

  it("unlinks when the employee cannot review issues", () => {
    expect(
      pinPushAssociation({
        employee_id: 60,
        organization_id: 3,
        features: { issues: { allowed: false } },
      }),
    ).toEqual({ action: "clear" });
    expect(pinPushAssociation({ employee_id: 15, organization_id: 3 })).toEqual({
      action: "clear",
    });
  });
});

describe("PIN Lock keeps the notification association", () => {
  it("hub lock clears the PIN session and does not log out of OneSignal", () => {
    const hub = block(src("pages/EmployeePinHubPage.jsx"), "const lockSession = () => {");
    expect(hub).toContain("clearPinHubSession()");
    expect(hub).toContain("clearPinHubAppSession()");
    expect(hub).toContain('setPhase("pin")');
    expect(hub).not.toContain("clearOneSignalUser");
    expect(hub).not.toContain("OneSignal.logout");
  });

  it("module lock clears the PIN session and does not log out of OneSignal", () => {
    const page = block(src("pages/PinModulePage.jsx"), "const onLock = useCallback(async () => {");
    expect(page).toContain("clearPinHubSession()");
    expect(page).toContain("clearPinHubAppSession()");
    expect(page).not.toContain("clearOneSignalUser");
    expect(page).not.toContain("OneSignal.logout");
  });

  it("a successful PIN applies the reviewer association", () => {
    const hub = src("pages/EmployeePinHubPage.jsx");
    expect(hub).toContain("applyPinPushAssociation(body)");
  });

  it("explicit sign-out and turning push off still unlink", () => {
    const auth = src("context/AuthContext.jsx");
    expect(auth).toMatch(/const logout = useCallback\(\(\) => \{\s*clearOneSignalUser\(\)/);
    const prefs = src("pages/NotificationsPage.jsx");
    expect(prefs).toContain("if (!prefs.push_out) clearOneSignalUser()");
  });

  it("a missing auth session does not unlink push", () => {
    const auth = src("context/AuthContext.jsx");
    const start = auth.indexOf("if (!token) {");
    const missing = auth.slice(start, auth.indexOf("refreshMe();", start));
    expect(missing).not.toContain("clearOneSignalUser");
  });
});
