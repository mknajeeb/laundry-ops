import { describe, expect, it } from "vitest";
import {
  allSectionsSubmitted,
  compactProgress,
  formatMoneyInput,
  managerStatusLabel,
  parseMoneyInput,
  parseQtyInput,
  sectionIsLocked,
  sectionIsReturned,
  valuesStateFromPayload,
} from "./drcMobileEntryHelpers";

describe("drcMobileEntryHelpers", () => {
  it("formats currency en-US", () => {
    expect(formatMoneyInput(12.5)).toBe("$12.50");
    expect(formatMoneyInput(0)).toBe("$0.00");
  });

  it("validates money and qty non-negative", () => {
    expect(parseMoneyInput("12.50").ok).toBe(true);
    expect(parseMoneyInput("-1").ok).toBe(false);
    expect(parseMoneyInput("abc").ok).toBe(false);
    expect(parseQtyInput("3").value).toBe(3);
    expect(parseQtyInput("-2").ok).toBe(false);
  });

  it("locks submitted/approved; returned reopens for correction", () => {
    expect(sectionIsLocked("submitted")).toBe(true);
    expect(sectionIsLocked("approved")).toBe(true);
    expect(sectionIsLocked("returned")).toBe(false);
    expect(sectionIsLocked("rejected")).toBe(false);
    expect(sectionIsReturned("returned")).toBe(true);
    expect(sectionIsReturned("rejected")).toBe(true);
    expect(managerStatusLabel("submitted")).toBe("Submitted");
    expect(managerStatusLabel("approved")).toBe("Approved");
    expect(managerStatusLabel("returned")).toBe("Returned");
  });

  it("builds values state and progress from payload", () => {
    const payload = {
      assigned_sections: [
        {
          section_key: "self_service",
          section_label: "Self Service Revenue",
          status: "draft",
          draft_revision: 1,
          values: { cash: 10, card: null },
          fields: [
            { key: "cash", required: true, kind: "money" },
            { key: "card", required: true, kind: "money" },
          ],
        },
        {
          section_key: "drop_off",
          status: "submitted",
          draft_revision: 2,
          values: { cash: 1, card: 2 },
          fields: [
            { key: "cash", required: true, kind: "money" },
            { key: "card", required: true, kind: "money" },
          ],
        },
      ],
    };
    const vs = valuesStateFromPayload(payload);
    expect(vs.self_service.values.cash).toBe(10);
    expect(compactProgress(vs)).toEqual({ done: 1, total: 2 });
    expect(allSectionsSubmitted(payload)).toBe(false);
    payload.assigned_sections[0].status = "submitted";
    expect(allSectionsSubmitted(payload)).toBe(true);
  });
});
