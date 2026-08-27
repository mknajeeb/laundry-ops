import { describe, expect, it } from "vitest";
import {
  API_ERROR_LABELS,
  REVIEW_REASON_LABELS,
  collectNormalReviewUiText,
  formatReviewApiError,
  formatReviewBagShortReason,
  formatReviewReasonLabel,
  formatReviewReasonLabels,
  formatSplitStateLabel,
  isRawBackendCode,
} from "./reviewDisplayLabels";

const SAMPLE_CODES = Object.keys(REVIEW_REASON_LABELS);

describe("isRawBackendCode", () => {
  it("detects ALL_CAPS and snake_case machine keys", () => {
    expect(isRawBackendCode("WF_BULK_WORKITEM_REVIEW")).toBe(true);
    expect(isRawBackendCode("bulk_workitem_review_required")).toBe(true);
    expect(isRawBackendCode("Specialty items need review")).toBe(false);
    expect(isRawBackendCode("Missing from portal")).toBe(false);
  });
});

describe("formatReviewReasonLabel", () => {
  it("maps known review codes to VeeWash language", () => {
    expect(formatReviewReasonLabel("SERVICE_CLASSIFICATION_MISMATCH")).toBe(
      "Specialty items need review",
    );
    expect(formatReviewReasonLabel("WF_BULK_WORKITEM_REVIEW")).toBe("Bulk items need review");
    expect(formatReviewReasonLabel("MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL")).toBe(
      "Missing from portal",
    );
    expect(formatReviewReasonLabel("SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND")).toBe(
      "Split needs review",
    );
    expect(formatReviewReasonLabel("MANAGER_SENT_FOR_REVIEW")).toBe("Manual review");
  });

  it("falls back for unknown machine codes", () => {
    expect(formatReviewReasonLabel("TOTALLY_UNKNOWN_CODE_XYZ")).toBe("Needs review");
  });

  it("passes through human text unchanged", () => {
    expect(formatReviewReasonLabel("Manager sent bag back to review")).toBe(
      "Manager sent bag back to review",
    );
  });
});

describe("formatReviewApiError", () => {
  it("maps validation error keys to short English", () => {
    expect(formatReviewApiError("bulk_workitem_review_required")).toBe(
      API_ERROR_LABELS.bulk_workitem_review_required,
    );
    expect(formatReviewApiError("completion_employee_required")).toBe(
      "Select the employee who completed this order.",
    );
    expect(formatReviewApiError("post_weight_required")).toBe("Enter the post weight.");
  });

  it("prefers human message when error key is unknown", () => {
    expect(
      formatReviewApiError("unknown_validation_key", "Resolve bulk quantities before completing."),
    ).toBe("Resolve bulk quantities before completing.");
  });

  it("uses mapped copy for known error keys even when message is present", () => {
    expect(
      formatReviewApiError(
        "bulk_workitem_review_required",
        "Resolve bulk quantities before completing.",
      ),
    ).toBe(API_ERROR_LABELS.bulk_workitem_review_required);
  });
});

describe("formatReviewBagShortReason", () => {
  it("derives labels from reason_codes instead of raw short_reason", () => {
    const label = formatReviewBagShortReason({
      short_reason: "Wf Bulk Workitem Review",
      reason_codes: ["WF_BULK_WORKITEM_REVIEW"],
    });
    expect(label).toBe("Bulk items need review");
    expect(label).not.toMatch(/WF_BULK|workitem/i);
  });

  it("uses category fallback when codes are absent", () => {
    expect(formatReviewBagShortReason({ category: "manual_review" })).toBe("Manual review");
  });
});

describe("formatSplitStateLabel", () => {
  it("never exposes raw split state tokens in normal copy", () => {
    expect(formatSplitStateLabel("REVIEW_REQUIRED")).toBe("Needs review");
    expect(formatSplitStateLabel("REVIEW_REQUIRED")).not.toBe("REVIEW_REQUIRED");
  });
});

describe("normal Review UI never shows raw backend codes", () => {
  it("sanitizes every mapped review reason code", () => {
    for (const code of SAMPLE_CODES) {
      const label = formatReviewReasonLabel(code);
      expect(label).not.toBe(code);
      expect(label).not.toMatch(/^[A-Z0-9_]+$/);
    }
  });

  it("collectNormalReviewUiText excludes raw codes from bag payloads", () => {
    const bag = {
      short_reason: "SERVICE_CLASSIFICATION_MISMATCH",
      review_reason: "SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND",
      split_state: "REVIEW_REQUIRED",
      reason_codes: ["WF_BULK_WORKITEM_REVIEW", "DISAPPEARED_WITHOUT_COMPLETION"],
      category: "specialty_items",
    };
    const uiText = collectNormalReviewUiText(bag, {
      apiError: "completion_employee_required",
      validationReason: "Select the employee who completed this order.",
    }).join(" | ");

    for (const code of [
      ...bag.reason_codes,
      bag.short_reason,
      bag.review_reason,
      bag.split_state,
      "completion_employee_required",
    ]) {
      expect(uiText).not.toContain(code);
    }
    expect(uiText).toMatch(/Bulk items need review/i);
    expect(uiText).toMatch(/Select the employee/i);
  });

  it("formatReviewReasonLabels dedupes combined reasons", () => {
    expect(
      formatReviewReasonLabels([
        "DISAPPEARED_WITHOUT_COMPLETION",
        "MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL",
      ]),
    ).toBe("Missing from portal");
  });
});
