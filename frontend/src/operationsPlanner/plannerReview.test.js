import { describe, expect, it } from "vitest";
import { affectedShiftCount, interpretSaveResponse } from "./plannerReview";

describe("interpretSaveResponse", () => {
  it("treats a committed save as the only success", () => {
    expect(interpretSaveResponse(200, { ok: true }).saved).toBe(true);
  });

  it("keeps the draft when another manager is saving or already saved", () => {
    const busy = interpretSaveResponse(409, { ok: false, code: "busy", error: "Another manager is saving this schedule" });
    const changed = interpretSaveResponse(409, { ok: false, code: "schedule_changed", error: "Another manager saved this week" });
    expect(busy.saved).toBe(false);
    expect(busy.keepDraft).toBe(true);
    expect(busy.reload).toBe(false);
    expect(changed.saved).toBe(false);
    expect(changed.error).toMatch(/Another manager saved/);
  });

  it("counts one week by default and sixteen weeks only after a repeating choice", () => {
    const cells = [{ shifts: [{ start_time: "05:00" }, { start_time: "17:00" }] }];
    const anchor = "2026-11-23";
    const today = "2026-11-22";
    expect(affectedShiftCount({ scope: "this_week", cells, anchor, today })).toEqual({ weeks: 1, perWeek: 2, shifts: 2 });
    expect(affectedShiftCount({ scope: "this_and_future", cells, anchor, today })).toEqual({ weeks: 16, perWeek: 2, shifts: 32 });
    expect(affectedShiftCount({ scope: "future_only", cells, anchor, today }).weeks).toBe(16);
    expect(affectedShiftCount({ scope: "selected_weeks", cells, anchor, today, selectedWeeks: "2026-11-23, 2026-12-07, tuesday" }).shifts).toBe(4);
  });

  it("asks again only when the server needs a scope confirmation", () => {
    const confirm = interpretSaveResponse(409, { code: "confirmation_required" });
    expect(confirm.saved).toBe(false);
    expect(confirm.confirm).toBe(true);
    expect(confirm.error).toBe("");
  });
});
