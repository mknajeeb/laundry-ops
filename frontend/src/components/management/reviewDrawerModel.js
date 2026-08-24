/**
 * Compact Review drawer helpers — section visibility + save validation.
 * Does not change Review write-path semantics.
 */

import { classifyEditSavePath, parseWeightInput } from "../shift/editBagHelpers";

const MISSING_CODES = new Set(["DISAPPEARED_WITHOUT_COMPLETION"]);
const SPECIALTY_BULK_CODE = "WF_BULK_WORKITEM_REVIEW";

export function reasonCodeSet(bag) {
  return new Set(
    (bag?.reason_codes || []).map((c) => String(c || "").trim().toUpperCase()).filter(Boolean),
  );
}

export function bagHasMissingPortal(bag) {
  if (bag?.has_missing_portal === true) return true;
  if (bag?.category === "missing_from_portal") return true;
  return Boolean([...reasonCodeSet(bag)].some((c) => MISSING_CODES.has(c)));
}

export function bagHasSpecialtyBulk(bag) {
  if (bag?.bulk_review_unresolved === true) return true;
  if (bag?.bulk_review_unresolved === false) return false;
  if (bag?.has_specialty_bulk === true) return true;
  if (reasonCodeSet(bag).has(SPECIALTY_BULK_CODE)) return true;
  if (Number(bag?.comforter_quantity) > 0 || Number(bag?.bath_mat_quantity) > 0) return true;
  if (Array.isArray(bag?.bulk_workitems) && bag.bulk_workitems.length) return true;
  return false;
}

/** True when bulk workitem review still blocks Save & Complete. */
export function bagBulkReviewUnresolved(bag) {
  if (bag?.bulk_review_unresolved === false) return false;
  if (bag?.bulk_review_cleared === true) return false;
  if (bag?.bulk_review_unresolved === true) return true;
  if (!bagHasSpecialtyBulk(bag)) return false;
  const res = bag?.bulk_resolution;
  if (res?.resolution_type === "no_charge") return false;
  if (Array.isArray(bag?.bulk_workitems) && bag.bulk_workitems.some((l) => Number(l.quantity) > 0)) {
    return false;
  }
  return bagHasSpecialtyBulk(bag);
}

export function bulkItemsDraft(lines = [], { noChargeable = false, noChargeReason = "" } = {}) {
  if (noChargeable) {
    return {
      bulk_items: [],
      no_chargeable: true,
      no_charge_reason: String(noChargeReason || "").trim(),
    };
  }
  return {
    bulk_items: (lines || [])
      .filter((l) => Number(l.quantity) > 0)
      .map((l) => ({ workitem_id: l.workitem_id, quantity: l.quantity })),
    no_chargeable: false,
  };
}

export function fmtLbs(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return `${n} lb`;
}

export function toPickerValue(v) {
  if (!v) return "";
  const s = String(v).trim().replace(" ", "T");
  const m = s.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return m ? m[1] : s.slice(0, 16);
}

export function validateMissingComplete({
  completedBy,
  completionAt,
  postWeightLbs,
  lockReady = true,
  saving = false,
  readOnly = false,
}) {
  if (readOnly) return { enabled: false, reason: "Day closed — read only" };
  if (saving) return { enabled: false, reason: "Save in progress" };
  if (!lockReady) return { enabled: false, reason: "Bag details still loading" };
  if (!String(completedBy || "").trim()) {
    return { enabled: false, reason: "Select completion employee" };
  }
  if (!String(completionAt || "").trim()) {
    return { enabled: false, reason: "Enter completion date & time (ET)" };
  }
  const raw = String(postWeightLbs ?? "").trim();
  if (raw) {
    const n = parseWeightInput(raw);
    if (n == null || n < 0) {
      return { enabled: false, reason: "POST must be a valid non-negative weight" };
    }
  }
  return { enabled: true, reason: null };
}

export function validateSpecialtySave({
  lines = [],
  noChargeable = false,
  noChargeReason = "",
  saving = false,
  readOnly = false,
  catalogReady = true,
}) {
  if (readOnly) return { enabled: false, reason: "Day closed — read only" };
  if (saving) return { enabled: false, reason: "Save in progress" };
  if (!catalogReady) return { enabled: false, reason: "Specialty items still loading" };
  if (noChargeable) {
    if ((lines || []).some((l) => Number(l.quantity) > 0)) {
      return { enabled: false, reason: "Clear quantities before marking no-charge" };
    }
    if (!String(noChargeReason || "").trim()) {
      return { enabled: false, reason: "No-charge reason is required" };
    }
    return { enabled: true, reason: null };
  }
  const positive = (lines || []).filter((l) => Number(l.quantity) > 0);
  if (!positive.length) {
    return { enabled: false, reason: "Enter Bath Mat / Comforter quantity or mark no-charge" };
  }
  for (const line of lines || []) {
    const q = Number(line.quantity);
    if (!Number.isInteger(q) || q < 0) {
      return { enabled: false, reason: "Quantities must be zero or positive integers" };
    }
  }
  return { enabled: true, reason: null };
}

export function suggestedCompleteAudit({ draft, baselineBag }) {
  const path = classifyEditSavePath({
    draft,
    baselineBag,
    outcome: "mark_completed",
  });
  const code = path.suggestedReasonCode || "MARK_COMPLETED";
  const note = path.confirmCompleted
    ? "Missing From Portal — confirm completion"
    : "Missing From Portal — Save & Complete";
  return {
    reasonCode: path.reasonRequired ? code : "MARK_COMPLETED",
    reasonNote: note,
    reasonRequired: Boolean(path.reasonRequired),
    confirmCompleted: Boolean(path.confirmCompleted),
  };
}

export function catalogSpecialtyLines(catalog = [], existing = []) {
  const byId = new Map();
  for (const wi of catalog || []) {
    if (wi?.id == null) continue;
    byId.set(Number(wi.id), {
      workitem_id: Number(wi.id),
      name: wi.name || "Item",
      unit_price: Number(wi.current_unit_price) || 0,
      quantity: 0,
    });
  }
  for (const line of existing || []) {
    const id = line.workitem_id != null ? Number(line.workitem_id) : null;
    if (id == null) continue;
    const prev = byId.get(id) || {
      workitem_id: id,
      name: line.workitem_name || line.name || "Item",
      unit_price: Number(line.unit_price) || 0,
      quantity: 0,
    };
    prev.quantity = Number(line.quantity) || 0;
    if (!prev.unit_price) prev.unit_price = Number(line.unit_price) || 0;
    if (line.workitem_name && prev.name === "Item") prev.name = line.workitem_name;
    byId.set(id, prev);
  }
  const all = [...byId.values()];
  const bath = all.filter((l) => String(l.name || "").toLowerCase().includes("bath"));
  const comforter = all.filter((l) => String(l.name || "").toLowerCase().includes("comfort"));
  const named = [...bath, ...comforter];
  if (named.length) {
    const seen = new Set(named.map((l) => l.workitem_id));
    const extra = all.filter((l) => !seen.has(l.workitem_id) && Number(l.quantity) > 0);
    return [...named, ...extra];
  }
  return all;
}
