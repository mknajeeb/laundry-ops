/**
 * Show bag details is a Bag-ID fallback only — never when bagId already present.
 * (Logic mirror of expandRowAndReadBag early-return; no Playwright.)
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

function shouldClickShowBagDetails({ bagIdAfterExpand, skipShow }) {
  if (bagIdAfterExpand) return false;
  if (skipShow) return false;
  return true;
}

describe("Show bag details fallback gate", () => {
  it("does not click when Bag ID already available", () => {
    assert.equal(shouldClickShowBagDetails({ bagIdAfterExpand: "CEA4TAF6IK", skipShow: false }), false);
  });

  it("clicks only when Bag ID missing after expand", () => {
    assert.equal(shouldClickShowBagDetails({ bagIdAfterExpand: "", skipShow: false }), true);
  });

  it("respects skip flag", () => {
    assert.equal(shouldClickShowBagDetails({ bagIdAfterExpand: "", skipShow: true }), false);
  });
});
