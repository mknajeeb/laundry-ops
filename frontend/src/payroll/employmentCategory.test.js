import { describe, expect, test } from "vitest";
import {
  classifyEmploymentCategory,
  currentAssignment,
  isVendorReceiptCategory,
  validateTryOutDates,
} from "./employmentCategory";

describe("employmentCategory", () => {
  test("classifies Try Out before Temp (TRYOUT contains TEMP)", () => {
    expect(classifyEmploymentCategory({ code: "EC_TRYOUT", name: "Try Out" })).toBe("tryout");
    expect(classifyEmploymentCategory({ code: "TRYOUT", name: "Tryout" })).toBe("tryout");
    expect(classifyEmploymentCategory({ code: "EC_TEMP", name: "Temporary / seasonal" })).toBe(
      "temp",
    );
  });

  test("does not classify Try Out as W-2 or 1099", () => {
    expect(classifyEmploymentCategory({ code: "EC_TRYOUT", name: "Try Out" })).not.toBe("w2");
    expect(classifyEmploymentCategory({ code: "EC_TRYOUT", name: "Try Out" })).not.toBe(
      "contractor_1099",
    );
  });

  test("vendor receipt categories include tryout, not W-2", () => {
    expect(isVendorReceiptCategory("tryout")).toBe(true);
    expect(isVendorReceiptCategory("temp")).toBe(true);
    expect(isVendorReceiptCategory("contractor_1099")).toBe(true);
    expect(isVendorReceiptCategory("w2")).toBe(false);
  });

  test("rejects invalid try out range", () => {
    expect(validateTryOutDates("2026-08-13", "2026-08-10")).toMatch(/earlier/);
    expect(validateTryOutDates("2026-08-10", "2026-08-13")).toBeNull();
    expect(validateTryOutDates("", "2026-08-13")).toMatch(/require/);
  });

  test("current assignment prefers covering period", () => {
    const rows = [
      {
        employment_category_id: 1,
        effective_from: "2026-08-10",
        effective_to: "2026-08-13",
        id: 1,
      },
      {
        employment_category_id: 2,
        effective_from: "2026-08-14",
        effective_to: "",
        id: 2,
      },
    ];
    expect(currentAssignment(rows, "2026-08-12").id).toBe(1);
    expect(currentAssignment(rows, "2026-08-15").id).toBe(2);
  });
});
