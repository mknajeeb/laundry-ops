import { describe, expect, it } from "vitest";
import week from "./fixtures/veewash-2027-01-04.json";
import { barBox, dayScheduleSummary, displaySegments, draftOperations, placeBreak, relocateShift, resizeBreak, resizeEdge, resizeSegment, roleColor, scheduleCardRows, splitHalves, storedRoleSegments, timelineAxis, visibleBreaks, visualPieces } from "./plannerGeometry";

describe("planner geometry", () => {
  it("starts the axis at the earliest shift instead of clipping 02:00 to 06:00", () => {
    const axis = timelineAxis([{ start_time: "02:00", end_time: "11:30" }]);
    expect(axis.startMin).toBe(2 * 60);
    expect(barBox("02:00", "11:30", axis).left).toBe("0%");
  });

  it("does not invent a clock time for break minutes", () => {
    const [slot] = visibleBreaks({ start_time: "08:00", end_time: "16:00", break_minutes: 30, break_slots: null });
    expect(slot.unscheduled).toBe(true);
    expect(slot.minutes).toBe(30);
    expect(slot.timed).toBe(false);
    expect(slot.start_time).toBeUndefined();
    const moved = relocateShift({
      start_time: "05:00",
      end_time: "13:00",
      role: "wash,attendant",
      break_minutes: 30,
      break_slots: null,
      role_assignments: null,
    }, "06:00", 1);
    expect(moved.break_slots).toBeNull();
    expect(moved.role_assignments).toBeNull();
    expect(displaySegments(moved)).toEqual([
      { role: "wash,attendant", start_time: "06:00", end_time: "14:00", allocated: false },
    ]);
    expect(resizeBreak(moved, 0, "start", 10 * 60)).toBe(moved);
    expect(placeBreak(moved, "09:00", "09:30").break_slots).toEqual([
      { start_time: "09:00", end_time: "09:30", timed: true },
    ]);
  });

  it("keeps role segments attached when a shift moves", () => {
    const moved = relocateShift({
      start_time: "08:00",
      end_time: "16:00",
      role: "wash",
      role_assignments: [
        { role: "wash", start_time: "08:00", end_time: "12:00" },
        { role: "fold", start_time: "12:30", end_time: "16:00" },
      ],
      break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }],
    }, "09:00", 2);
    expect(moved.end_time).toBe("17:00");
    expect(moved.day_of_week).toBe(2);
    expect(moved.role_assignments[0].start_time).toBe("09:00");
    expect(moved.break_slots[0].start_time).toBe("13:00");
    expect(moved.role).toBe("wash");
    expect(moved.role_assignments[0].allocated).toBeUndefined();
    expect(displaySegments(moved)).toHaveLength(2);
  });

  it("keeps a VeeWash combined role when a segment or the shift moves", () => {
    const jennifer = week.entries.find((entry) => entry.id === 5136);
    const resized = resizeSegment(jennifer, 1, "end", 14 * 60);
    expect(resized).toEqual({
      ...jennifer,
      end_time: "14:00",
      role_assignments: [
        { role: "weigher", start_time: "05:00", end_time: "06:00" },
        { role: "fold", start_time: "06:00", end_time: "14:00" },
      ],
    });
    const moved = relocateShift(resized, "07:30", 1);
    expect(moved.role).toBe("weigher,fold");
    expect(moved.id).toBe(5136);
    expect(moved.break_slots).toBeNull();
    expect(moved.break_minutes).toBe(30);
    expect(moved.start_time).toBe("07:30");
    expect(moved.end_time).toBe("16:30");
    expect(moved.role_assignments[0]).toEqual({ role: "weigher", start_time: "07:30", end_time: "08:30" });
    const edged = resizeEdge(jennifer, "end", 13 * 60 + 30);
    expect(edged.role).toBe("weigher,fold");
    expect(edged.start_time).toBe("05:00:00");
    expect(edged.role_assignments[1].role).toBe("fold");
    expect(edged.break_slots).toBeNull();
    const placed = placeBreak(jennifer, "09:00", "09:30");
    expect(placed.role).toBe("weigher,fold");
    expect(placed.start_time).toBe(jennifer.start_time);
    expect(placed.role_assignments).toEqual(jennifer.role_assignments);
    expect(placed.break_slots).toEqual([{ start_time: "09:00", end_time: "09:30", timed: true }]);
  });

  it("does not invent segments or rewrite a combined label that has no allocations", () => {
    const attendant = week.entries.find((entry) => entry.id === 5251);
    expect(resizeSegment(attendant, 0, "end", 17 * 60)).toBe(attendant);
    const edged = resizeEdge(attendant, "end", 16 * 60 + 30);
    expect(edged.role).toBe("wash,attendant");
    expect(edged.role_assignments).toBeNull();
    expect(edged.break_slots).toBeNull();
    expect(edged.break_minutes).toBe(30);
    expect(displaySegments(edged)[0].allocated).toBe(false);
    expect(displaySegments(edged)[0].role).toBe("wash,attendant");
  });

  it("keeps an unallocated combined remainder on the combined role", () => {
    const maria = week.entries.find((entry) => entry.id === 5266);
    const pieces = visualPieces(maria);
    expect(pieces.map((piece) => piece.role)).toEqual(["fold,attendant", "attendant"]);
    expect(pieces[0].allocated).toBe(false);
    expect(pieces[1].allocated).toBe(true);
    expect(roleColor("fold,attendant")).toBe("#3e4c59");
    expect(roleColor("fold,attendant")).not.toBe(roleColor("fold"));
    expect(roleColor("weigher,fold")).toBe("#3e4c59");
  });

  it("ignores a full-shift placeholder from the weekly schedule payload", () => {
    const fromApi = {
      role: "fold,attendant",
      start_time: "08:00",
      end_time: "16:00",
      role_assignments: null,
      assignments: [
        { role: "attendant", start_time: "14:00", end_time: "16:00", full_shift: false },
        { role: "fold", start_time: "08:00", end_time: "16:00", full_shift: true },
      ],
    };
    expect(storedRoleSegments(fromApi).map((segment) => segment.role)).toEqual(["attendant"]);
    const pieces = visualPieces({ ...fromApi, role_assignments: storedRoleSegments(fromApi) });
    expect(pieces.map((piece) => piece.role)).toEqual(["fold,attendant", "attendant"]);
    expect(pieces[0].allocated).toBe(false);
    const plain = storedRoleSegments({
      role: "fold",
      assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00", full_shift: true }],
    });
    expect(plain).toEqual([]);
  });

  it("splits one shift into two halves with their own segments and breaks", () => {
    const jennifer = week.entries.find((entry) => entry.id === 5136);
    const halves = splitHalves(jennifer);
    expect(halves.first.id).toBe(5136);
    expect(halves.first.end_time).toBe("09:00");
    expect(halves.first.role_assignments.map((segment) => segment.role)).toEqual(["weigher", "fold"]);
    expect(halves.first.role_assignments[1].end_time).toBe("09:00");
    expect(halves.first.break_minutes).toBe(30);
    expect(halves.second.id).toBeUndefined();
    expect(halves.second.start_time).toBe("09:00");
    expect(halves.second.role).toBe("fold");
    expect(halves.second.break_minutes).toBe(0);
    expect(halves.second.role_assignments).toEqual([{ role: "fold", start_time: "09:00", end_time: "13:00" }]);
    const saved = [jennifer];
    const draft = [{ ...halves.first }, { ...halves.second, id: "draft-1" }];
    const operations = draftOperations(saved, draft);
    expect(operations.map((item) => item.op)).toEqual(["update", "create"]);
    expect(operations[0].id).toBe(5136);
    const removed = draftOperations(saved, []);
    expect(removed).toEqual([{ op: "delete", id: 5136, user_id: jennifer.user_id, day_of_week: jennifer.day_of_week }]);
  });

  it("gives each stored role its own card row and leaves an unsplit gap unlabeled", () => {
    const monday = {
      id: 1,
      user_id: 7,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:00",
      role: "wash",
      break_minutes: 30,
      break_slots: [{ start_time: "12:00", end_time: "12:30", timed: true }],
      role_assignments: [
        { role: "wash", start_time: "08:00", end_time: "12:00" },
        { role: "fold", start_time: "12:30", end_time: "16:00" },
      ],
    };
    expect(scheduleCardRows(monday).map((row) => [row.role, row.start_time, row.end_time])).toEqual([
      ["wash", "08:00", "12:00"],
      ["fold", "12:30", "16:00"],
    ]);
    const summary = dayScheduleSummary([monday], 1);
    expect(summary.people).toBe(1);
    expect(summary.gross).toBe(8);
    expect(summary.net).toBe(7.5);
    expect(summary.roles.wash).toBe(4);
    expect(summary.roles.fold).toBe(3.5);
    const combined = scheduleCardRows({
      start_time: "05:00",
      end_time: "13:00",
      role: "wash,attendant",
      break_minutes: 30,
      break_slots: null,
      role_assignments: null,
    });
    expect(combined.map((row) => row.role)).toEqual(["wash", "attendant"]);
    expect(combined.every((row) => row.unsplit && !row.start_time)).toBe(true);
  });
});
