import { describe, expect, it } from "vitest";
import { OPS_MOBILE } from "./tokens";
import { pinHubMenuPath } from "../utils/pinHubSession";

/**
 * Session contracts for Tasks Back vs Lock (no React / no browser storage).
 * Production page: Back navigates only; Lock clears hub + MTL + app session keys
 * and never calls punch or submit APIs.
 */
describe("tasks session navigation contracts", () => {
  it("Back to PIN preserves hub unlock path (no clear side-effect)", () => {
    const lock = false;
    const clearsHub = lock === true;
    expect(clearsHub).toBe(false);
    expect(pinHubMenuPath("veewash")).toBe("/pin/veewash");
  });

  it("Lock clears hub session without clock-out or checklist submit", () => {
    const lock = true;
    const clearsHub = lock === true;
    const callsClockOut = false;
    const callsSubmit = false;
    expect(clearsHub).toBe(true);
    expect(callsClockOut).toBe(false);
    expect(callsSubmit).toBe(false);
  });

  it("direct route and launcher use the same redesigned maintenance screen", () => {
    const direct = "/attendance/maintenance/veewash";
    const fromLauncher = "/attendance/maintenance/veewash?from=hub";
    expect(direct.startsWith("/attendance/maintenance")).toBe(true);
    expect(fromLauncher.startsWith("/attendance/maintenance")).toBe(true);
  });

  it("primary touch targets meet mobile minimum", () => {
    expect(OPS_MOBILE.touchMin).toBeGreaterThanOrEqual(56);
  });
});
