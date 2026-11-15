import { describe, expect, it } from "vitest";
import { reconciliationCheck } from "./supervisorFormat";

describe("supervisor reconciliation display", () => {
  it("shows the November 14 historical case as fully accounted", () => {
    const check = reconciliationCheck({
      total_completed: 175,
      total_accounted: 175,
      unaccounted: 0,
      categories: {
        approved: 156,
        pending: 3,
        excluded: 3,
        outside_session: 11,
        nonqualifying: 2,
        unmapped: 0,
        unresolved: 0,
      },
    });
    expect(check.holds).toBe(true);
    expect(check.sum).toBe(175);
    expect(check.unaccounted).toBe(0);
  });
});
