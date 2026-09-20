import { describe, expect, it } from "vitest";
import {
  formatOpenBreakCaption,
  payrollBreakRowActions,
} from "./payrollBreakActions";

describe("payrollBreakRowActions", () => {
  it("exposes Close Break and Delete Break for open breaks", () => {
    const actions = payrollBreakRowActions({
      id: 86,
      status: "open",
      break_start_at: "2026-09-10T13:25:22",
      break_end_at: null,
    });
    expect(actions.map((a) => a.key)).toEqual(["close", "delete"]);
    expect(actions.map((a) => a.label)).toEqual(["Close Break", "Delete Break"]);
  });

  it("exposes Edit Break and Delete Break for completed breaks", () => {
    const actions = payrollBreakRowActions({
      id: 73,
      status: "completed",
      deducted: true,
    });
    expect(actions.map((a) => a.key)).toEqual(["edit", "delete"]);
    expect(actions.map((a) => a.label)).toEqual(["Edit Break", "Delete Break"]);
  });

  it("does not hide actions for open breaks (approval block is separate)", () => {
    // Approval is blocked on the parent row; break management must remain available.
    expect(payrollBreakRowActions({ status: "open" }).length).toBe(2);
  });
});

describe("formatOpenBreakCaption", () => {
  it("labels open breaks as not deducted", () => {
    expect(formatOpenBreakCaption({ status: "open" })).toMatch(/not deducted/i);
    expect(formatOpenBreakCaption({ status: "completed" })).toBeNull();
  });
});
