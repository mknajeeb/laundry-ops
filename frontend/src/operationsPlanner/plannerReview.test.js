import { describe, expect, it } from "vitest";
import { affectedShiftCount, explainSaveError, incompleteShiftLines, interpretSaveResponse, patternCells } from "./plannerReview";

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

  it("explains a missing envelope and keeps the draft", () => {
    const rejected = interpretSaveResponse(409, { ok: false, code: "rolled_back", error: "start_time and end_time must be HH:MM" });
    expect(rejected.saved).toBe(false);
    expect(rejected.keepDraft).toBe(true);
    expect(explainSaveError(rejected.error)).toMatch(/needs a start and end/);
    expect(explainSaveError(rejected.error)).not.toMatch(/Add a role/);
    expect(explainSaveError("a role is required")).toMatch(/Add a role/);
    expect(explainSaveError("a role is required")).toMatch(/hours and break stay/);
    expect(explainSaveError(rejected.error)).toMatch(/draft is still here/);
    expect(explainSaveError("the same role cannot overlap itself on one shift")).toMatch(/Remove the extra row/);
  });

  it("names a partial add and leaves it out of a day that also has a valid change", () => {
    const monday = { id: 11, user_id: 7, day_of_week: 1, start_time: "06:00", end_time: "14:00", role: "fold", break_minutes: 0, break_slots: [], role_assignments: [] };
    const blank = { id: "draft-blank", user_id: 9, day_of_week: 1, start_time: "", end_time: "", role: "", break_minutes: 0, break_slots: [], role_assignments: [] };
    const partial = { id: "draft-partial", user_id: 38, day_of_week: 1, start_time: "10:00", end_time: "", role: "fold", break_minutes: 30, break_slots: [], role_assignments: [] };
    const changed = { ...monday, end_time: "15:00" };
    const employees = [{ user_id: 38, display_name: "Amna" }];
    const after = [changed, blank, partial];
    const cells = patternCells([monday], after);
    expect(cells).toHaveLength(1);
    expect(cells[0].shifts.map((shift) => shift.id)).toEqual([11]);
    expect(incompleteShiftLines(after, employees)).toEqual([
      { employee: "Amna", day: "Monday", detail: "Needs a start and end" },
    ]);
    expect(affectedShiftCount({
      scope: "this_and_future",
      cells,
      anchor: "2026-11-23",
      today: "2026-11-22",
    }).shifts).toBe(16);
  });

  it("asks again only when the server needs a scope confirmation", () => {
    const confirm = interpretSaveResponse(409, { code: "confirmation_required" });
    expect(confirm.saved).toBe(false);
    expect(confirm.confirm).toBe(true);
    expect(confirm.error).toBe("");
  });
});
