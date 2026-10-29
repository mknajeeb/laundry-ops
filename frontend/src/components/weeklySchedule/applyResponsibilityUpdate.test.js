import { describe, expect, it } from "vitest";
import { applyResponsibilityUpdate, mergeScheduleMutation } from "./applyResponsibilityUpdate";

const week = {
  week_start: "2026-11-01",
  employees: [{ user_id: 28, total_hours: 8 }],
  entries: [{ id: 9, user_id: 28, day_of_week: 1 }],
  totals: { total_hours: 8 },
  daily_responsibilities: [
    { id: 1, user_id: 28, day_of_week: 1, user_ids: [28, 31], assignment_group_id: "g1" },
    { id: 2, user_id: 31, day_of_week: 1, user_ids: [28, 31], assignment_group_id: "g1" },
    { id: 6, user_id: 61, day_of_week: 0, user_ids: [61], assignment_group_id: "keep" },
  ],
};

describe("applyResponsibilityUpdate", () => {
  it("replaces both cards of a shared pairing and leaves shifts alone", () => {
    const next = applyResponsibilityUpdate(week, {
      responsibility_update: {
        removed_ids: [2],
        responsibilities: [{ id: 1, user_id: 28, day_of_week: 1, user_ids: [28], execution_mode: "individual" }],
      },
    });
    expect(next.employees).toBe(week.employees);
    expect(next.entries).toBe(week.entries);
    expect(next.totals).toEqual({ total_hours: 8 });
    expect(next.daily_responsibilities.map((row) => row.id).sort()).toEqual([1, 6]);
    expect(next.daily_responsibilities.find((row) => row.id === 1).user_ids).toEqual([28]);
  });

  it("moves both members by replacing the same ids on the new day", () => {
    const next = applyResponsibilityUpdate(week, {
      responsibility_update: {
        removed_ids: [],
        responsibilities: [
          { id: 1, user_id: 28, day_of_week: 3, user_ids: [28, 31] },
          { id: 2, user_id: 31, day_of_week: 3, user_ids: [28, 31] },
        ],
      },
    });
    const moved = next.daily_responsibilities.filter((row) => row.id === 1 || row.id === 2);
    expect(moved.every((row) => row.day_of_week === 3)).toBe(true);
    expect(next.daily_responsibilities.some((row) => row.id === 6)).toBe(true);
  });

  it("keeps a full week payload for shift saves", () => {
    const full = { employees: [], entries: [], daily_responsibilities: [] };
    expect(mergeScheduleMutation(week, full)).toBe(full);
  });
});
