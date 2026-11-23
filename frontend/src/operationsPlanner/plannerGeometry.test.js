import { describe, expect, it } from "vitest";
import week from "./fixtures/veewash-2027-01-04.json";
import { applyRoleEdits, barBox, breakAssignment, canonicalSchedule, copyBreaksOnto, copyTaskAssignments, dayScheduleSummary, displaySegments, draftOperations, moveBreakTo, moveTaskTo, operationsWereSaved, persistedRoleSignature, placeBreak, proposeBreak, relocateShift, removeBreak, resizeBreak, resizeEdge, resizeSegment, roleColor, scheduleCardRows, scheduledRoleHours, slideBreak, splitHalves, staffingFigures, storedRoleSegments, timelineAxis, visibleBreaks, visualPieces } from "./plannerGeometry";

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
    expect(pieces.map((piece) => piece.role)).toEqual(["attendant"]);
    expect(pieces[0].allocated).toBe(true);
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
    expect(pieces.map((piece) => piece.role)).toEqual(["attendant"]);
    expect(pieces[0].allocated).toBe(true);
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
    expect(summary.gross).toBe(7.5);
    expect(summary.net).toBe(7.5);
    expect(summary.roles.wash).toBe(4);
    expect(summary.roles.fold).toBe(3.5);
    expect(summary.roleCounts.wash).toBe(1);
    expect(summary.roleCounts.fold).toBe(1);
    const overlap = dayScheduleSummary([
      monday,
      {
        ...monday,
        id: 2,
        user_id: 7,
        role_assignments: [
          { role: "wash", start_time: "08:00", end_time: "10:00" },
          { role: "wash", start_time: "09:00", end_time: "11:00" },
        ],
      },
      {
        ...monday,
        id: 3,
        user_id: 8,
        role_assignments: [{ role: "wash", start_time: "08:00", end_time: "10:00" }],
      },
    ], 1);
    expect(overlap.roleCounts.wash).toBe(2);
    expect(overlap.roles.wash).toBe(6);
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

  it("schedules only the role intervals and ignores a wider stored shift", () => {
    const monday = {
      user_id: 38,
      day_of_week: 1,
      start_time: "05:00",
      end_time: "13:30",
      role: "dry",
      break_minutes: 30,
      break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }],
      role_assignments: [
        { role: "weigher", start_time: "05:00", end_time: "06:00" },
        { role: "sort", start_time: "06:00", end_time: "10:00" },
      ],
    };
    expect(scheduleCardRows(monday).map((row) => [row.role, row.start_time, row.end_time])).toEqual([
      ["weigher", "05:00", "06:00"],
      ["sort", "06:00", "10:00"],
    ]);
    expect(scheduleCardRows(monday).some((row) => !row.role)).toBe(false);
    const hours = scheduledRoleHours(monday);
    expect(hours.gross).toBe(5);
    expect(hours.net).toBe(5);
    const overlap = scheduledRoleHours({
      ...monday,
      role_assignments: [
        { role: "weigher", start_time: "05:00", end_time: "07:00" },
        { role: "sort", start_time: "06:00", end_time: "10:00" },
      ],
    });
    expect(overlap.gross).toBe(5);
    const inside = scheduledRoleHours({
      ...monday,
      break_slots: [{ start_time: "09:00", end_time: "09:30", timed: true }],
      role_assignments: [
        { role: "weigher", start_time: "05:00", end_time: "06:00" },
        { role: "sort", start_time: "06:00", end_time: "10:00" },
      ],
    });
    expect(inside.gross).toBe(5);
    expect(inside.net).toBe(4.5);
    const amna = staffingFigures(monday);
    expect(amna).toMatchObject({ role: 5, unallocated: 3.5, total: 8.5, net: 8 });
    const longerSort = applyRoleEdits(monday, [
      { role: "weigher", start_time: "05:00", end_time: "06:00" },
      { role: "sort", start_time: "06:00", end_time: "11:00" },
    ]);
    expect(longerSort.confirm).toBeUndefined();
    expect(longerSort.entry.end_time).toBe("13:30");
    expect(staffingFigures(longerSort.entry)).toMatchObject({ role: 6, unallocated: 2.5, total: 8.5 });
    const extended = applyRoleEdits(monday, [
      { role: "weigher", start_time: "05:00", end_time: "06:00" },
      { role: "sort", start_time: "06:00", end_time: "14:00" },
    ]);
    expect(extended.confirm.kind).toBe("extend");
    expect(extended.entry.end_time).toBe("13:30");
    const trimmed = applyRoleEdits(monday, monday.role_assignments, "trim");
    expect(trimmed.entry.end_time).toBe("10:00");
    expect(staffingFigures(trimmed.entry).total).toBe(5);
    const fresh = {
      id: "draft-angelica",
      user_id: 12,
      day_of_week: 1,
      start_time: "",
      end_time: "",
      role: "",
      break_minutes: 0,
      break_slots: [],
      role_assignments: [],
    };
    const created = applyRoleEdits(fresh, [{ role: "fold", start_time: "06:00", end_time: "16:00" }]);
    expect(created.confirm).toBeUndefined();
    expect(created.entry).toMatchObject({ start_time: "06:00", end_time: "16:00", role: "fold" });
    expect(created.entry.role_assignments).toEqual([{ role: "fold", start_time: "06:00", end_time: "16:00" }]);
    expect(scheduleCardRows(created.entry)).toHaveLength(1);
    const savedShape = {
      ...created.entry,
      break_minutes: 30,
      break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }],
    };
    expect(staffingFigures(savedShape)).toMatchObject({ role: 10, unallocated: 0, total: 10, net: 9.5 });
    const splitRoles = applyRoleEdits(savedShape, [
      { role: "fold", start_time: "06:00", end_time: "12:00" },
      { role: "wash", start_time: "12:00", end_time: "16:00" },
    ]);
    expect(splitRoles.confirm).toBeUndefined();
    expect(splitRoles.entry.start_time).toBe("06:00");
    expect(splitRoles.entry.end_time).toBe("16:00");
    expect(splitRoles.entry.role_assignments).toHaveLength(2);
    const removed = applyRoleEdits(splitRoles.entry, [{ role: "fold", start_time: "06:00", end_time: "12:00" }]);
    expect(removed.entry.end_time).toBe("16:00");
    expect(removed.entry.role_assignments).toEqual([{ role: "fold", start_time: "06:00", end_time: "12:00" }]);
    const asks = applyRoleEdits(savedShape, [{ role: "fold", start_time: "06:00", end_time: "17:00" }]);
    expect(asks.confirm.kind).toBe("extend");
    expect(asks.entry.end_time).toBe("16:00");
    const opened = applyRoleEdits(fresh, [
      { role: "fold", start_time: "06:00", end_time: "12:00" },
      { role: "wash", start_time: "12:00", end_time: "16:00" },
    ]);
    expect(opened.entry.start_time).toBe("06:00");
    expect(opened.entry.end_time).toBe("16:00");
    expect(staffingFigures(opened.entry)).toMatchObject({ role: 10, unallocated: 0, total: 10, net: 10 });
    const aselisa = staffingFigures([
      {
        user_id: 4,
        day_of_week: 1,
        start_time: "08:00",
        end_time: "16:30",
        role: "attendant",
        role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
        break_slots: [{ minutes: 30 }],
      },
      {
        id: 2,
        user_id: 4,
        day_of_week: 1,
        start_time: "08:00",
        end_time: "16:00",
        role: "attendant",
        role_assignments: [{ role: "attendant", start_time: "08:00", end_time: "16:00" }],
        break_slots: [{ minutes: 30 }],
      },
    ]);
    expect(aselisa).toMatchObject({ role: 8, unallocated: 0.5, total: 8.5, net: 8, review: true });
    const sent = {
      role: "sort",
      start_time: "09:00",
      end_time: "11:00",
      role_assignments: [{ role: "sort", start_time: "09:00", end_time: "11:00" }],
    };
    const stored = { role: "sort", start_time: "09:00", end_time: "11:00", role_assignments: null };
    expect(persistedRoleSignature(sent)).toBe(persistedRoleSignature(stored));
  });

  it("previews a bulk break without replacing an existing record or touching the shift envelope", () => {
    const stored = {
      user_id: 7,
      day_of_week: 1,
      start_time: "08:00",
      end_time: "16:30",
      role: "fold",
      role_assignments: [{ role: "fold", start_time: "08:00", end_time: "16:00" }],
      break_slots: [],
    };
    const added = proposeBreak(stored, { mode: "untimed", minutes: 30, replace: false });
    expect(added.skipped).toBe(false);
    expect(added.entry.end_time).toBe("16:30");
    expect(added.entry.break_slots).toEqual([{ minutes: 30 }]);
    const kept = proposeBreak(added.entry, { mode: "timed", minutes: 15, start: "12:00", replace: false });
    expect(kept.skipped).toBe(true);
    expect(kept.entry.break_slots).toEqual([{ minutes: 30 }]);
    const replaced = proposeBreak(added.entry, { mode: "timed", minutes: 30, start: "12:00", replace: true });
    expect(replaced.entry.break_slots).toEqual([{ start_time: "12:00", end_time: "12:30", timed: true }]);
    const removed = removeBreak(replaced.entry, 0);
    expect(removed.break_slots).toEqual([]);
    expect(removed.break_minutes).toBe(0);
    expect(removed.start_time).toBe(replaced.entry.start_time);
    const monday = { user_id: 7, day_of_week: 1, start_time: "06:00", end_time: "16:00", role: "fold", break_slots: [{ start_time: "10:00", end_time: "10:30", timed: true }], break_minutes: 30 };
    const tuesday = { user_id: 7, day_of_week: 2, start_time: "06:00", end_time: "16:00", role: "fold", break_slots: [], break_minutes: 0 };
    const other = { user_id: 8, day_of_week: 2, start_time: "12:00", end_time: "15:00", role: "wash", break_slots: [], break_minutes: 0 };
    const sameEmployee = copyBreaksOnto([monday, tuesday], monday, [7], [1, 2]);
    expect(sameEmployee.entries[1].break_slots).toEqual([{ start_time: "10:00", end_time: "10:30", timed: true }]);
    expect(sameEmployee.notes.some((note) => note.day === 1 && note.reason === "This break is already on the shift.")).toBe(true);
    const otherDay = copyBreaksOnto([monday, other], monday, [8], [2]);
    expect(otherDay.entries[1].break_slots).toEqual([]);
    expect(otherDay.notes.some((note) => note.reason.includes("outside this shift"))).toBe(true);
    const missing = copyBreaksOnto([monday], monday, [7, 8], [1, 3]);
    expect(missing.notes.some((note) => note.userId === 8 && note.reason.includes("No shift"))).toBe(true);
    expect(missing.notes.some((note) => note.day === 3 && note.reason.includes("No shift"))).toBe(true);
    const several = copyBreaksOnto([monday, tuesday, { ...other, start_time: "06:00", end_time: "16:00" }], monday, [7, 8], [2]);
    expect(several.entries[1].break_slots).toHaveLength(1);
    expect(several.entries[2].break_slots).toHaveLength(1);
    expect(several.notes.filter((note) => note.reason === "Copied.")).toHaveLength(2);
    const shared = { id: 4, user_id: 7, day_of_week: 1, role: "agroup_floor", timing_mode: "anytime", assignment_group_id: "g1", status: "completed", execution_mode: "shared" };
    const copies = copyTaskAssignments([shared], shared, [8], [1]);
    expect(copies.tasks).toEqual([shared]);
    expect(copies.refused).toMatch(/shared activity/);
    const individual = copyTaskAssignments([{ id: 5, user_id: 7, day_of_week: 1, role: "floor_cleaning", timing_mode: "anytime" }], { id: 5, user_id: 7, day_of_week: 1, role: "floor_cleaning", timing_mode: "anytime" }, [8], [1, 2]);
    expect(individual.tasks).toHaveLength(3);
    expect(individual.tasks[1].assignment_group_id).toBeNull();
    expect(individual.tasks[1].timing_mode).toBe("anytime");
    expect(individual.tasks[0].id).toBe(5);
    const slid = slideBreak(monday, 0, 11 * 60);
    expect(slid.break_slots[0]).toEqual({ start_time: "11:00", end_time: "11:30", timed: true });
    expect(slideBreak(monday, 0, 4 * 60)).toBe(monday);
    const moved = moveBreakTo([monday, tuesday], monday, monday.break_slots[0], 7, 2);
    expect(moved.entries[0].break_slots).toEqual([]);
    expect(moved.entries[1].break_slots).toHaveLength(1);
    expect(staffingFigures(moved.entries[0]).net).toBe(10);
    expect(staffingFigures(moved.entries[1]).net).toBe(9.5);
    expect(moveBreakTo([monday], monday, monday.break_slots[0], 8, 4).note).toMatch(/No shift/);
    const keptGroup = moveTaskTo([shared], shared, 8, 2);
    expect(keptGroup.tasks[0]).toEqual(shared);
    expect(keptGroup.note).toMatch(/shared activity/);
    expect(breakAssignment(stored, [{ minutes: 30 }, { minutes: 30 }]).break_minutes).toBe(30);
  });

  it("treats a stored full-span role as the same schedule the editor sent", () => {
    const sent = {
      id: 12,
      user_id: 34,
      day_of_week: 0,
      start_time: "06:00",
      end_time: "16:00",
      role: "fold",
      break_minutes: 30,
      break_slots: [{ start_time: "10:30", end_time: "11:00", timed: true }],
      role_assignments: [{ role: "fold", start_time: "06:00", end_time: "16:00" }],
    };
    const stored = {
      id: 12,
      user_id: 34,
      day_of_week: 0,
      start_time: "06:00",
      end_time: "16:00",
      role: "fold",
      break_minutes: 30,
      break_slots: [{ start_time: "10:30", end_time: "11:00" }],
      assignments: [{ role: "fold", start_time: "06:00", end_time: "16:00", full_shift: true }],
    };
    expect(canonicalSchedule(sent)).toEqual(canonicalSchedule(stored));
    const saved = operationsWereSaved([stored], [{ op: "update", id: 12, day_of_week: 0, shift: sent }], []);
    expect(saved.ok).toBe(true);
    const created = operationsWereSaved(
      [stored, { ...stored, id: 90 }],
      [{ op: "create", day_of_week: 0, shift: { ...sent, id: "draft-1" } }],
      [12],
    );
    expect(created.ok).toBe(true);
    expect(created.missing).toEqual([]);
    const absent = operationsWereSaved([], [{ op: "create", day_of_week: 0, user_id: 34, shift: sent }], []);
    expect(absent.ok).toBe(false);
    expect(absent.missing).toHaveLength(1);
  });
});
