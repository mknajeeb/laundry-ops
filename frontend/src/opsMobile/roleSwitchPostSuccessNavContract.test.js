import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { pinHubMenuPath } from "../utils/pinHubSession";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * After a confirmed Change Role switch, clear the hub session and return to
 * the PIN pad — never the Mobile Ops menu.
 */
describe("role switch post-success navigation contract", () => {
  it("success path locks hub session and navigates to PIN pad", () => {
    const src = readFileSync(join(root, "pages/AttendanceRoleSwitchPage.jsx"), "utf8");
    expect(src).toContain("onSuccess: () => {");
    expect(src).toMatch(/onSuccess:\s*\(\)\s*=>\s*\{[^}]*goPinLauncher\(\{\s*lock:\s*true\s*\}\)/s);
    expect(src).not.toMatch(/onSuccess:\s*\(\)\s*=>\s*\{[^}]*goPinLauncher\(\{\s*lock:\s*false\s*\}\)/s);
    expect(pinHubMenuPath("veewash")).toBe("/pin/veewash");
  });

  it("Back preserves hub unlock; Lock clears session", () => {
    const src = readFileSync(join(root, "pages/AttendanceRoleSwitchPage.jsx"), "utf8");
    // Back must not clear session
    expect(src).toMatch(/const onBack = useCallback\(\(\) => \{[\s\S]*?navigate\(pinHubMenuPath\(slug\)/);
    expect(src).not.toMatch(/const onBack = useCallback\(\(\) => \{[\s\S]*?clearPinHubSession/);
    // Lock clears
    expect(src).toContain("goPinLauncher({ lock: true })");
  });

  it("controller only invokes onSuccess after backend ok", () => {
    const src = readFileSync(join(root, "opsMobile/createSwitchRoleController.js"), "utf8");
    expect(src).toContain("if (status >= 200 && status < 300 && body.ok)");
    expect(src).toContain("onSuccess?.(successBody)");
    expect(src).toContain("ROLE_SUCCESS_DELAY_MS = 5000");
    expect(src).toContain("dismissSuccess()");
    // Failure path must not call onSuccess
    expect(src).toMatch(/error = errFn\([\s\S]*?emit\(\);\s*return \{ called: true, ok: false/);
    const afterOk = src.slice(src.indexOf("return { called: true, ok: true, body }"));
    expect(afterOk.indexOf("onSuccess?.(")).toBe(-1);
  });
});
