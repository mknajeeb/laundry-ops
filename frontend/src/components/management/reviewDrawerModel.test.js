import { describe, expect, it } from "vitest";
import {
  bagBulkReviewUnresolved,
  bagHasMissingPortal,
  bagHasSpecialtyBulk,
  bagHasSpecialtyReview,
  resolveReviewDrawerInlineVariant,
  catalogSpecialtyLines,
  fmtLbs,
  suggestedCompleteAudit,
  validateMissingComplete,
  validateSpecialtySave,
} from "./reviewDrawerModel";

describe("review drawer section flags", () => {
  it("shows missing actions from reason or category", () => {
    expect(bagHasMissingPortal({ reason_codes: ["DISAPPEARED_WITHOUT_COMPLETION"] })).toBe(true);
    expect(bagHasMissingPortal({ category: "missing_from_portal", reason_codes: [] })).toBe(true);
    expect(bagHasMissingPortal({ reason_codes: ["WF_BULK_WORKITEM_REVIEW"] })).toBe(false);
  });

  it("shows specialty bulk from reason or quantities without hiding missing", () => {
    const both = {
      reason_codes: ["WF_BULK_WORKITEM_REVIEW", "DISAPPEARED_WITHOUT_COMPLETION"],
    };
    expect(bagHasSpecialtyBulk(both)).toBe(true);
    expect(bagHasMissingPortal(both)).toBe(true);
    expect(bagHasSpecialtyBulk({ comforter_quantity: 2 })).toBe(true);
    expect(bagHasSpecialtyBulk({ reason_codes: ["WF_ZERO_OR_MISSING_POST_WEIGHT"] })).toBe(false);
  });

  it("respects backend bulk_review_unresolved flags", () => {
    expect(bagBulkReviewUnresolved({ bulk_review_unresolved: false })).toBe(false);
    expect(bagBulkReviewUnresolved({ bulk_review_unresolved: true })).toBe(true);
    expect(
      bagBulkReviewUnresolved({
        reason_codes: ["DISAPPEARED_WITHOUT_COMPLETION"],
        bulk_review_unresolved: true,
      }),
    ).toBe(true);
    expect(
      bagBulkReviewUnresolved({
        reason_codes: ["WF_BULK_WORKITEM_REVIEW"],
        bulk_workitems: [{ quantity: 2 }],
      }),
    ).toBe(false);
  });

  it("always mounts specialty review inline surface without bulk evidence", () => {
    const bag = {
      reason_codes: ["MANAGER_SENT_FOR_REVIEW"],
      has_specialty_bulk: false,
      bulk_review_unresolved: false,
    };
    expect(bagHasSpecialtyReview(bag)).toBe(true);
    expect(resolveReviewDrawerInlineVariant(bag, "specialty_items")).toBe("specialty_review");
    expect(resolveReviewDrawerInlineVariant(bag)).toBe("specialty_review");
  });

  it("keeps bulk controls separate from specialty review completion surface", () => {
    const unresolved = {
      reason_codes: ["WF_BULK_WORKITEM_REVIEW"],
      bulk_review_unresolved: true,
    };
    expect(resolveReviewDrawerInlineVariant(unresolved, "specialty_items")).toBe(
      "specialty_bulk",
    );
    const cleared = {
      reason_codes: ["SERVICE_CLASSIFICATION_MISMATCH"],
      category: "specialty_items",
      bulk_review_unresolved: false,
      has_specialty_bulk: false,
    };
    expect(resolveReviewDrawerInlineVariant(cleared, "specialty_items")).toBe(
      "specialty_review",
    );
  });
});

describe("fmtLbs", () => {
  it("omits empty and keeps zero", () => {
    expect(fmtLbs(null)).toBeNull();
    expect(fmtLbs("")).toBeNull();
    expect(fmtLbs(0)).toBe("0 lb");
    expect(fmtLbs(12.5)).toBe("12.5 lb");
  });
});

describe("validateMissingComplete", () => {
  it("explains missing employee and time", () => {
    expect(validateMissingComplete({ completedBy: "", completionAt: "2026-08-17T10:00" }).reason).toMatch(
      /employee/i,
    );
    expect(validateMissingComplete({ completedBy: "Ada", completionAt: "" }).reason).toMatch(/date/i);
    expect(
      validateMissingComplete({
        completedBy: "Ada",
        completionAt: "2026-08-17T10:00",
        postWeightLbs: "12",
      }).enabled,
    ).toBe(true);
  });

  it("allows empty POST and rejects invalid POST", () => {
    expect(
      validateMissingComplete({
        completedBy: "Ada",
        completionAt: "2026-08-17T10:00",
        postWeightLbs: "",
      }).enabled,
    ).toBe(true);
    expect(
      validateMissingComplete({
        completedBy: "Ada",
        completionAt: "2026-08-17T10:00",
        postWeightLbs: "nope",
      }).enabled,
    ).toBe(false);
  });
});

describe("validateSpecialtySave", () => {
  it("requires qty or no-charge reason", () => {
    expect(validateSpecialtySave({ lines: [{ quantity: 0 }] }).enabled).toBe(false);
    expect(
      validateSpecialtySave({
        lines: [{ quantity: 1, workitem_id: 1 }],
      }).enabled,
    ).toBe(true);
    expect(
      validateSpecialtySave({
        noChargeable: true,
        noChargeReason: "",
        lines: [],
      }).enabled,
    ).toBe(false);
    expect(
      validateSpecialtySave({
        noChargeable: true,
        noChargeReason: "False alarm",
        lines: [],
      }).enabled,
    ).toBe(true);
  });
});

describe("suggestedCompleteAudit", () => {
  it("uses CORRECT_COMPLETION_DETAILS when employee is newly entered", () => {
    const audit = suggestedCompleteAudit({
      draft: { completed_by: "Ada", completion_at: "2026-08-17T10:00", post_weight_lbs: "12" },
      baselineBag: { post_weight_lbs: "12" },
    });
    expect(audit.reasonCode).toBe("CORRECT_COMPLETION_DETAILS");
    expect(audit.reasonRequired).toBe(true);
  });
});

describe("catalogSpecialtyLines", () => {
  it("keeps Bath Mat and Comforter even at qty 0", () => {
    const lines = catalogSpecialtyLines(
      [
        { id: 1, name: "Bath Mat", current_unit_price: 4 },
        { id: 2, name: "Comforter", current_unit_price: 18 },
      ],
      [{ workitem_id: 1, quantity: 2, unit_price: 4 }],
    );
    expect(lines.map((l) => l.name)).toEqual(["Bath Mat", "Comforter"]);
    expect(lines[0].quantity).toBe(2);
    expect(lines[1].quantity).toBe(0);
  });
});
