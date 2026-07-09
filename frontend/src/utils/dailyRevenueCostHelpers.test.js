import { describe, expect, it } from "vitest";
import {
  DRC_ENTRY_STATUS,
  buildDrcOverridePayload,
  drcWorkflowSupportsNotes,
  fieldsNeedingOverrideReason,
  getDrcSourceIndicatorStyle,
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

describe("DRC source indicators", () => {
  it("styles manual, imported, and override sources", () => {
    expect(getDrcSourceIndicatorStyle(null).label).toBe("Manual");
    expect(getDrcSourceIndicatorStyle({ source_system: "payroll" }).color).toBe("info");
    expect(getDrcSourceIndicatorStyle({ source_system: "payroll", is_manual_override: true }).color).toBe("warning");
  });

  it("detects imported field changes needing override reason", () => {
    const baselineForm = { payroll_total: 500 };
    const form = { payroll_total: 642.15 };
    const lineSources = {
      "payroll.total": { source_system: "payroll", is_manual_override: false },
    };
    const needs = fieldsNeedingOverrideReason({ baselineForm, form, lineSources, overrideReasons: {} });
    expect(needs).toHaveLength(1);
    expect(needs[0].lineKey).toBe("payroll.total");
  });

  it("builds override payload for save", () => {
    expect(buildDrcOverridePayload({ "payroll.total": "Adjusted for bonus payout" })).toEqual({
      "payroll.total": { is_manual_override: true, reason: "Adjusted for bonus payout" },
    });
  });
});
