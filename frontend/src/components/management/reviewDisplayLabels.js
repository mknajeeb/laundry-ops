/**
 * Human-readable labels for Management Rinse WF Review UI.
 * Backend reason / error codes stay internal — never show raw ALL_CAPS or snake_case in normal UI.
 */

const REVIEW_REASON_LABELS = {
  SERVICE_CLASSIFICATION_MISMATCH: "Specialty items need review",
  WF_BULK_WORKITEM_REVIEW: "Bulk items need review",
  MISSING_FROM_PORTAL_AFTER_FULL_TRAVERSAL: "Missing from portal",
  DISAPPEARED_WITHOUT_COMPLETION: "Missing from portal",
  REVIEW_MISSING_FROM_PORTAL: "Missing from portal",
  SPLIT_MARKED_BUT_SECOND_WASHER_NOT_FOUND: "Split needs review",
  MULTIPLE_WASHERS_WITHOUT_SPLIT_MARKER: "Split needs review",
  SPLIT_EVIDENCE_INCOMPLETE_AT_DISAPPEARANCE: "Split needs review",
  MANAGER_SENT_FOR_REVIEW: "Manual review",
  WF_ZERO_OR_MISSING_POST_WEIGHT: "Specialty items need review",
  WF_ZERO_OR_MISSING_WEIGHT: "Specialty items need review",
  COMPLETED_WITHOUT_RECOGNIZED_ENTRY: "Specialty items need review",
  COMPLETION_DETAILS_MISSING: "Specialty items need review",
  MISSING_PRE_EVIDENCE: "Specialty items need review",
  SCAN_CHRONOLOGY_STALE: "Specialty items need review",
  CORRECT_COMPLETION_DETAILS: "Manual review",
  MARK_COMPLETED: "Manual review",
};

const SPLIT_STATE_LABELS = {
  REVIEW_REQUIRED: "Needs review",
  PENDING: "Pending",
  CONFIRMED_SPLIT: "Confirmed split",
  CONFIRMED_NOT_SPLIT: "Confirmed not split",
  MANAGER_SPLIT: "Marked split",
  MANAGER_NOT_SPLIT: "Marked not split",
};

const API_ERROR_LABELS = {
  bulk_workitem_review_required:
    "Please review the bulk items before completing this order.",
  completion_employee_required: "Select the employee who completed this order.",
  post_weight_required: "Enter the post weight.",
  bag_not_found: "Bag not found.",
  invalid_category: "Invalid review category.",
  invalid_bag_id: "Invalid bag id.",
  conflict: "This bag was updated while you were reviewing it. Close and reopen to retry.",
  reason_code_required: "A review reason is required.",
  reason_note_required_for_other: "Enter a note for this review action.",
  validation_failed: "Check the form and try again.",
  bulk_update_failed: "Could not save bulk items.",
  edit_not_found: "Edit not found.",
  newer_edit_exists: "A newer edit exists. Refresh and try again.",
};

const ALL_CAPS_CODE = /^[A-Z][A-Z0-9_]*$/;
const SNAKE_CASE_KEY = /^[a-z][a-z0-9_]*$/;

export function isRawBackendCode(value) {
  const s = String(value ?? "").trim();
  if (!s) return false;
  if (ALL_CAPS_CODE.test(s)) return true;
  return SNAKE_CASE_KEY.test(s) && s.includes("_");
}

function normalizeReasonKey(value) {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[·\-.]/g, " ")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_");
}

function lookupReviewReasonLabel(key) {
  if (!key) return null;
  return REVIEW_REASON_LABELS[key] || REVIEW_REASON_LABELS[normalizeReasonKey(key)] || null;
}

/** Map one review reason code (or preformatted text) to operator-facing copy. */
export function formatReviewReasonLabel(codeOrText, { fallback = "Needs review" } = {}) {
  const raw = String(codeOrText ?? "").trim();
  if (!raw) return fallback;
  const mapped = lookupReviewReasonLabel(raw);
  if (mapped) return mapped;
  if (!isRawBackendCode(raw)) return raw;
  return fallback;
}

/** Join multiple reason codes into a short comma-separated label list. */
export function formatReviewReasonLabels(codes = [], { fallback = "Needs review" } = {}) {
  const list = (codes || [])
    .map((c) => formatReviewReasonLabel(c, { fallback: null }))
    .filter(Boolean);
  const unique = [...new Set(list)];
  if (unique.length) return unique.join(", ");
  return fallback;
}

/** Prefer mapped labels from reason_codes; otherwise sanitize short_reason from API. */
export function formatReviewBagShortReason(
  bag,
  { fallback = "Needs review", categoryFallback = null } = {},
) {
  const codes = bag?.reason_codes;
  if (Array.isArray(codes) && codes.length) {
    return formatReviewReasonLabels(codes, { fallback });
  }
  const short = String(bag?.short_reason ?? "").trim();
  if (short) {
    const mapped = lookupReviewReasonLabel(short);
    if (mapped) return mapped;
    if (!isRawBackendCode(short)) return short;
    const fromNormalized = lookupReviewReasonLabel(normalizeReasonKey(short));
    if (fromNormalized) return fromNormalized;
  }
  if (categoryFallback) return categoryFallback;
  const cat = String(bag?.category || bag?.review_category || "").toLowerCase();
  if (cat === "missing_from_portal") return "Missing from portal";
  if (cat === "split_order_review") return "Split needs review";
  if (cat === "manual_review") return "Manual review";
  if (cat === "specialty_items") return "Specialty items need review";
  return fallback;
}

export function formatSplitStateLabel(state, { fallback = "Needs review" } = {}) {
  const raw = String(state ?? "").trim();
  if (!raw) return null;
  const mapped = SPLIT_STATE_LABELS[raw.toUpperCase()] || SPLIT_STATE_LABELS[normalizeReasonKey(raw)];
  if (mapped) return mapped;
  if (!isRawBackendCode(raw)) return raw;
  return fallback;
}

function isHumanMessage(text) {
  const s = String(text ?? "").trim();
  if (!s) return false;
  if (isRawBackendCode(s)) return false;
  return true;
}

/** Format API `error` / `message` fields for Review drawers and save actions. */
export function formatReviewApiError(error, message) {
  const errKey = String(error ?? "").trim();
  const msg = String(message ?? "").trim();
  if (errKey && API_ERROR_LABELS[errKey]) return API_ERROR_LABELS[errKey];
  if (isHumanMessage(msg)) return msg;
  if (errKey && isRawBackendCode(errKey)) {
    return API_ERROR_LABELS[errKey] || "Something went wrong. Try again.";
  }
  if (msg) return formatReviewReasonLabel(msg, { fallback: "Something went wrong. Try again." });
  return "Something went wrong. Try again.";
}

/** Raw code string for engineer-only debug disclosure (never default UI). */
export function formatReviewReasonDebugDetail(bagOrCodes) {
  const codes = Array.isArray(bagOrCodes)
    ? bagOrCodes
    : bagOrCodes?.reason_codes || (bagOrCodes?.review_reason ? [bagOrCodes.review_reason] : []);
  const list = (codes || []).map((c) => String(c || "").trim()).filter(Boolean);
  if (!list.length) return null;
  return list.join(", ");
}

/**
 * Strings that would appear in normal Review UI for one bag — used by tests to guard against raw codes.
 */
export function collectNormalReviewUiText(bag, { apiError, apiMessage, validationReason } = {}) {
  const parts = [
    formatReviewBagShortReason(bag, { categoryFallback: null }),
    bag?.review_reason ? formatReviewReasonLabel(bag.review_reason) : null,
    bag?.split_state ? formatSplitStateLabel(bag.split_state) : null,
    apiError || apiMessage ? formatReviewApiError(apiError, apiMessage) : null,
    validationReason || null,
  ].filter(Boolean);
  return parts;
}

export { REVIEW_REASON_LABELS, API_ERROR_LABELS, SPLIT_STATE_LABELS };
