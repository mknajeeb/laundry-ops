/** Frontend OT premium display helpers. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  computeEarningsBreakdown,
  computeOvertimePremium,
  earningsReconcile,
} from "./payrollOtDisplay.js";

describe("payrollOtDisplay", () => {
  it("shows only OT premium above regular rate", () => {
    assert.equal(computeOvertimePremium(1, 20, { otRate: 30 }), 10);
    assert.equal(computeOvertimePremium(1, 20), 10);
  });

  it("reconciles base + premium + other = gross with OT hours", () => {
    const br = computeEarningsBreakdown({
      approved_hours: 40,
      ot_hours: 5,
      rate: 20,
      ot_rate: 30,
      gross_amount: 950,
    });
    assert.equal(br.base_earnings, 900);
    assert.equal(br.ot_premium, 50);
    assert.ok(earningsReconcile(br));
  });

  it("handles no overtime", () => {
    const br = computeEarningsBreakdown({
      approved_hours: 38,
      ot_hours: 0,
      rate: 20,
      gross_amount: 760,
    });
    assert.equal(br.ot_premium, 0);
    assert.ok(earningsReconcile(br));
  });

  it("uses stored gross so register matches payroll record", () => {
    const br = computeEarningsBreakdown({
      approved_hours: 40,
      ot_hours: 8.65,
      rate: 17,
      ot_rate: 25.5,
      gross_amount: 900.58,
    });
    assert.equal(br.gross_pay, 900.58);
    assert.ok(earningsReconcile(br));
  });

  it("never returns negative OT premium for edge rates", () => {
    assert.equal(computeOvertimePremium(2, 20, { otRate: null }), 20);
    assert.equal(computeOvertimePremium(2, 20, { otRate: 20 }), 0);
    assert.equal(computeOvertimePremium(2, 20, { otRate: 10 }), 0);
    assert.equal(computeOvertimePremium(-3, 20, { otRate: 30 }), 0);
    const low = computeEarningsBreakdown({
      approved_hours: 40,
      ot_hours: 10,
      rate: 20,
      ot_rate: 15,
      gross_amount: 950,
    });
    assert.equal(low.ot_premium, 0);
    assert.ok(earningsReconcile(low));
    const salaried = computeEarningsBreakdown({ rate: 0, gross_amount: 1500, ot_hours: 5 });
    assert.equal(salaried.ot_premium, 0);
    assert.equal(salaried.base_earnings, 0);
    assert.equal(salaried.other_earnings, 1500);
    assert.ok(earningsReconcile(salaried));
  });
});
