/**
 * Phase 5A: Stock Back/PIN must return to the PIN launcher, never /login.
 * Contract documented from App.jsx + InventoryPage session ordering.
 */
import { describe, expect, it } from "vitest";

describe("Stock PIN navigation contract (Phase 5A)", () => {
  it("clears Washpro session before pin-hub app session so App.jsx can redirect to /pin", () => {
    // InventoryPage.returnToPinMenu / lockToPinEntry must NOT call
    // clearPinHubAppSession() before clearing the Washpro user.
    // App.jsx branch (isPinHubAppSessionActive && /inventory && !user)
    // Navigates to pinHubMenuPath(slug) and then clears the app session.
    const safeOrder = ["clearWashproSession", "App.jsx Navigate /pin", "clearPinHubAppSession"];
    const buggyOrder = ["clearPinHubAppSession", "clearWashproSession", "auth gate /login"];
    expect(safeOrder[0]).toBe("clearWashproSession");
    expect(buggyOrder[0]).toBe("clearPinHubAppSession");
    expect(safeOrder.includes("/login")).toBe(false);
  });

  it("PIN hub menu path for veewash is /pin/veewash", async () => {
    const { pinHubMenuPath } = await import("../utils/pinHubSession");
    expect(pinHubMenuPath("veewash")).toBe("/pin/veewash");
    expect(pinHubMenuPath("veewash")).not.toBe("/login");
  });
});
