import { describe, expect, it } from "vitest";
import {
  DRC_ENTRY_STATUS,
  drcWorkflowSupportsNotes,
  getDrcStatusChipColor,
  getDrcStatusLabel,
  getDrcWorkflowActions,
  isDrcEntryEditable,
} from "./dailyRevenueCostHelpers";

describe("DRC workflow helpers", () => {
  it("treats only open entries as editable", () => {
    expect(isDrcEntryEditable(DRC_ENTRY_STATUS.OPEN)).toBe(true);
    expect(isDrcEntryEditable(DRC_ENTRY_STATUS.LOCKED)).toBe(false);
    expect(isDrcEntryEditable(DRC_ENTRY_STATUS.SUBMITTED)).toBe(false);
    expect(isDrcEntryEditable(DRC_ENTRY_STATUS.APPROVED)).toBe(false);
    expect(isDrcEntryEditable(DRC_ENTRY_STATUS.REJECTED)).toBe(false);
  });

  it("returns workflow actions by status", () => {
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.OPEN, true)).toEqual(["lock", "submit"]);
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.SUBMITTED, true)).toEqual(["approve", "reject"]);
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.REJECTED, true)).toEqual(["reopen"]);
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.LOCKED, true)).toEqual([]);
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.APPROVED, true)).toEqual([]);
    expect(getDrcWorkflowActions(DRC_ENTRY_STATUS.OPEN, false)).toEqual([]);
  });

  it("maps status chip colors and labels", () => {
    expect(getDrcStatusChipColor(DRC_ENTRY_STATUS.SUBMITTED)).toBe("info");
    expect(getDrcStatusChipColor(DRC_ENTRY_STATUS.REJECTED)).toBe("error");
    expect(getDrcStatusLabel(DRC_ENTRY_STATUS.APPROVED)).toBe("Approved");
  });

  it("supports notes on reject and reopen", () => {
    expect(drcWorkflowSupportsNotes("reject")).toBe(true);
    expect(drcWorkflowSupportsNotes("reopen")).toBe(true);
    expect(drcWorkflowSupportsNotes("lock")).toBe(false);
  });
});
