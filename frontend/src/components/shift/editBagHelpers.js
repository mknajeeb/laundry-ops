/**
 * Pure helpers for unified Edit Bag / one-shot WF Review draft + drawer cache merge.
 */

export function parseWeightInput(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** @deprecated Prefer reasonOptionsForTriggers / context-specific lists. */
export const EDIT_BAG_REASON_CODES = [
  { code: "POST_CORRECTION", label: "POST weight correction" },
  { code: "PRE_CORRECTION", label: "PRE weight correction" },
  { code: "EXCLUDE", label: "Exclude bag" },
  { code: "MARK_COMPLETED", label: "Manually mark completed" },
  { code: "RETURN_PENDING", label: "Return to pending" },
  { code: "ACCEPT_EXCEPTION", label: "Accept exception" },
  { code: "STATUS_OVERRIDE", label: "Manual status override" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_POST_CORRECTION = [
  { code: "INCORRECT_CAPTURED_WEIGHT", label: "Incorrect captured weight" },
  { code: "SCALE_ISSUE", label: "Scale issue" },
  { code: "WRONG_BAG_ASSOCIATION", label: "Wrong bag association" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_PRE_CORRECTION = [
  { code: "PRE_CORRECTION", label: "PRE weight correction" },
  { code: "MISSING_PRE_EVIDENCE", label: "Missing PRE evidence" },
  { code: "INCORRECT_CAPTURED_WEIGHT", label: "Incorrect captured weight" },
  { code: "SCALE_ISSUE", label: "Scale issue" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_RETURN_PENDING = [
  { code: "COMPLETION_ASSIGNED_INCORRECTLY", label: "Completion assigned incorrectly" },
  { code: "BAG_NOT_ACTUALLY_COMPLETED", label: "Bag not actually completed" },
  { code: "COMPLETION_EVIDENCE_INVALID", label: "Completion evidence invalid" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_EXCLUDE = [
  { code: "NOT_VEEWASH_BAG", label: "Not a VeeWash bag" },
  { code: "DUPLICATE_RECORD", label: "Duplicate record" },
  { code: "TEST_RECORD", label: "Test record" },
  { code: "WRONG_SERVICE_DAY", label: "Wrong service/day" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_COMPLETION_CHANGE = [
  { code: "COMPLETION_ASSIGNED_INCORRECTLY", label: "Completion assigned incorrectly" },
  { code: "CORRECT_COMPLETION_DETAILS", label: "Correct completion details" },
  { code: "OTHER", label: "Other" },
];

export const REASON_CODES_MANUAL_MARK_COMPLETED = [
  { code: "MARK_COMPLETED", label: "Manually mark completed" },
  { code: "STATUS_OVERRIDE", label: "Manual status override" },
  { code: "OTHER", label: "Other" },
];

export const EXCEPTIONAL_OUTCOMES = new Set(["mark_completed", "return_pending", "exclude"]);

function weightsDiffer(a, b) {
  const na = parseWeightInput(a);
  const nb = parseWeightInput(b);
  if (na == null && nb == null) return false;
  if (na == null || nb == null) return true;
  return Number(na) !== Number(nb);
}

function normalizeCompletionKey(raw) {
  if (raw == null || raw === "") return "";
  const text = String(raw).trim().replace("Z", "").replace(" ", "T");
  if (text.length >= 16 && text.includes("T")) return text.slice(0, 16).toLowerCase();
  return text.toLowerCase();
}

export function hasCanonicalCompletion(bag) {
  const emp = String(bag?.completed_by || bag?.canonical_completion_employee || "").trim();
  const ts = bag?.completion_at ?? bag?.canonical_completion_timestamp;
  if (emp && ts != null && ts !== "") return true;
  const status = String(bag?.dashboard_status || bag?.outcome || "").trim().toLowerCase();
  return ["completed", "complete", "done"].includes(status) && Boolean(emp || ts);
}

export function reasonOptionsForTriggers(triggers = []) {
  if (triggers.includes("post_weight_correction")) return REASON_CODES_POST_CORRECTION;
  if (triggers.includes("pre_weight_correction")) return REASON_CODES_PRE_CORRECTION;
  if (triggers.includes("return_pending")) return REASON_CODES_RETURN_PENDING;
  if (triggers.includes("exclude")) return REASON_CODES_EXCLUDE;
  if (
    triggers.includes("completion_employee_changed") ||
    triggers.includes("completion_timestamp_changed")
  ) {
    return REASON_CODES_COMPLETION_CHANGE;
  }
  if (triggers.includes("mark_completed") || triggers.includes("status_override")) {
    return REASON_CODES_MANUAL_MARK_COMPLETED;
  }
  return EDIT_BAG_REASON_CODES;
}

/**
 * Classify whether the current draft is a routine review save, confirm-completed,
 * or a manager override that needs a structured reason.
 */
export function classifyEditSavePath({ draft, baselineBag, outcome = null }) {
  const triggers = [];
  const baselinePost = baselineBag?.post_weight_value ?? baselineBag?.post_weight_lbs;
  if (baselineBag && weightsDiffer(draft?.post_weight_lbs, baselinePost)) {
    triggers.push("post_weight_correction");
  }
  if (baselineBag && weightsDiffer(draft?.pre_weight_lbs, baselineBag.pre_weight_lbs)) {
    triggers.push("pre_weight_correction");
  }

  const draftEmp = String(draft?.completed_by || draft?.completion_employee || "")
    .trim()
    .toLowerCase();
  const beforeEmp = String(baselineBag?.completed_by || "").trim().toLowerCase();
  const empChanged = draftEmp !== beforeEmp;
  const tsChanged =
    normalizeCompletionKey(draft?.completion_at) !==
    normalizeCompletionKey(baselineBag?.completion_at);
  if (empChanged) triggers.push("completion_employee_changed");
  if (tsChanged) triggers.push("completion_timestamp_changed");

  const weightOverride =
    triggers.includes("post_weight_correction") || triggers.includes("pre_weight_correction");
  let confirmCompleted = false;
  if (outcome === "mark_completed") {
    if (
      hasCanonicalCompletion(baselineBag) &&
      !empChanged &&
      !tsChanged &&
      !weightOverride &&
      !draft?.manual_status_override
    ) {
      confirmCompleted = true;
    } else {
      triggers.push("mark_completed");
    }
  } else if (outcome === "return_pending" || outcome === "exclude") {
    triggers.push(String(outcome));
  }

  if (draft?.manual_status_override) triggers.push("status_override");

  const reasonRequired = triggers.length > 0;
  let suggestedReasonCode = null;
  if (triggers.includes("pre_weight_correction") && !triggers.includes("post_weight_correction")) {
    const baselinePre = baselineBag?.pre_weight_lbs;
    suggestedReasonCode =
      baselinePre === null || baselinePre === undefined || baselinePre === ""
        ? "MISSING_PRE_EVIDENCE"
        : "PRE_CORRECTION";
  } else if (triggers.includes("post_weight_correction") || triggers.includes("pre_weight_correction")) {
    suggestedReasonCode = "INCORRECT_CAPTURED_WEIGHT";
  } else if (outcome === "exclude" || triggers.includes("exclude")) {
    suggestedReasonCode = "NOT_VEEWASH_BAG";
  } else if (outcome === "return_pending" || triggers.includes("return_pending")) {
    suggestedReasonCode = "BAG_NOT_ACTUALLY_COMPLETED";
  } else if (
    triggers.includes("completion_employee_changed") ||
    triggers.includes("completion_timestamp_changed")
  ) {
    suggestedReasonCode = "CORRECT_COMPLETION_DETAILS";
  } else if (triggers.includes("mark_completed")) {
    suggestedReasonCode = "MARK_COMPLETED";
  } else if (triggers.includes("status_override")) {
    suggestedReasonCode = "STATUS_OVERRIDE";
  }

  const path = confirmCompleted && !reasonRequired
    ? "confirm_completed"
    : reasonRequired
      ? "manager_override"
      : "routine_review";

  return {
    path,
    isRoutineReview: path === "routine_review",
    isManagerOverride: path === "manager_override",
    confirmCompleted,
    reasonRequired,
    triggers,
    suggestedReasonCode,
    reasonCodes: reasonRequired ? reasonOptionsForTriggers(triggers) : [],
    systemAction: confirmCompleted && !reasonRequired
      ? "REVIEW_CONFIRMED_COMPLETED"
      : "WORKITEMS_UPDATED",
  };
}

/**
 * Mirror of backend classify_edit_reason_requirements for UI gating.
 */
export function classifyEditReasonRequirements({
  draft,
  baselineBag,
  outcome,
  lines,
}) {
  const path = classifyEditSavePath({ draft, baselineBag, outcome });
  const bulkTouched = (lines || []).some((l) => Number(l.quantity) > 0) || draft?.no_chargeable;
  let systemAction = path.systemAction;
  if (path.confirmCompleted && !path.reasonRequired) {
    systemAction = "REVIEW_CONFIRMED_COMPLETED";
  } else if (!path.reasonRequired) {
    systemAction = bulkTouched ? "WORKITEMS_UPDATED" : "REVIEW_UPDATED";
  }
  return {
    reasonRequired: path.reasonRequired,
    triggers: path.triggers,
    suggestedReasonCode: path.suggestedReasonCode,
    reasonCodes: path.reasonCodes,
    systemAction,
    path: path.path,
    isRoutineReview: path.isRoutineReview,
    isManagerOverride: path.isManagerOverride,
    confirmCompleted: path.confirmCompleted,
  };
}

export function validateEditBagDraft({
  reason,
  reasonCode,
  reasonNote,
  noChargeable,
  noChargeReason,
  lines,
  isHd,
  reasonRequired = false,
}) {
  if (reasonRequired) {
    const code = String(reasonCode || "").trim().toUpperCase();
    const note = String(reasonNote || reason || "").trim();
    if (!code && !note) return "A reason code is required for this action";
    if (code === "OTHER" && !note) return "Add a short note when reason is Other";
    if (!code && note) {
      /* free-text alone ok as Other */
    } else if (!code) {
      return "A reason code is required for this action";
    }
  }
  if (noChargeable) {
    if ((lines || []).some((l) => Number(l.quantity) > 0)) {
      return "No Chargeable Bulk Items cannot coexist with positive quantities";
    }
    if (!String(noChargeReason || "").trim()) {
      return "No-charge reason is required";
    }
  }
  if (!isHd) {
    for (const l of lines || []) {
      const q = Number(l.quantity);
      if (!Number.isInteger(q) || q < 0) {
        return "Bulk quantities must be zero or positive integers";
      }
    }
  }
  return "";
}

/** Format portal observation / event time for managers in America/New_York. */
export function formatWeightObservedEt(raw) {
  if (!raw) return "";
  const s = String(raw).trim();
  if (!s) return "";

  // Timezone-aware ISO (Z or offset) — convert with DST-aware America/New_York.
  if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).formatToParts(d);
      const pick = (t) => parts.find((p) => p.type === t)?.value ?? "";
      return `${pick("month")}/${pick("day")} ${pick("hour")}:${pick("minute")} ET`;
    }
  }

  // Legacy naive wall string — treat as already-Eastern portal chronology.
  const m = s.replace("T", " ").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return s.slice(0, 16);
  const [, , mo, d, hh, mm] = m;
  return `${mo}/${d} ${hh}:${mm} ET`;
}

/** Friendly clock for evidence cards: "8:24 AM ET". */
export function formatEvidenceClockEt(raw) {
  if (!raw) return "";
  const s = String(raw).trim();
  if (!s) return "";

  if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return `${d.toLocaleString("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      })} ET`;
    }
  }

  const m = s.replace("T", " ").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    const hour24 = Number(m[4]);
    const hour12 = hour24 % 12 || 12;
    const ampm = hour24 >= 12 ? "PM" : "AM";
    return `${hour12}:${m[5]} ${ampm} ET`;
  }
  return formatWeightObservedEt(raw);
}

/**
 * Capture lag in whole minutes (first observed − portal weight-entry).
 * Prefers timezone-aware ISO from the API.
 */
export function captureLagMinutes(portalEventAt, observedAt) {
  const toMs = (raw) => {
    if (raw == null || raw === "") return null;
    const s = String(raw).trim();
    if (!s) return null;
    if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) {
      const t = Date.parse(s);
      return Number.isFinite(t) ? t : null;
    }
    // Naive portal ET wall: attach America/New_York offset for that calendar day.
    const m = s.replace("T", " ").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (!m) return null;
    const wall = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6] || "00"}`;
    // Probe noon UTC on that date to learn EDT vs EST offset, then apply to wall.
    const probe = new Date(`${m[1]}-${m[2]}-${m[3]}T16:00:00Z`);
    const offsetLabel = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      timeZoneName: "shortOffset",
      hour: "2-digit",
    })
      .formatToParts(probe)
      .find((p) => p.type === "timeZoneName")?.value;
    // GMT-4 / GMT-5 / UTC-4
    const om = String(offsetLabel || "").match(/([+-])(\d{1,2})(?::?(\d{2}))?/);
    let offsetHours = -4;
    if (om) {
      offsetHours = Number(`${om[1]}${om[2]}`);
      if (om[3]) offsetHours += (Number(om[3]) / 60) * (om[1] === "-" ? -1 : 1);
    }
    const sign = offsetHours <= 0 ? "-" : "+";
    const absH = String(Math.abs(Math.trunc(offsetHours))).padStart(2, "0");
    const absM = String(Math.round((Math.abs(offsetHours) % 1) * 60)).padStart(2, "0");
    const t = Date.parse(`${wall}${sign}${absH}:${absM}`);
    return Number.isFinite(t) ? t : null;
  };

  const eventMs = toMs(portalEventAt);
  const obsMs = toMs(observedAt);
  if (eventMs == null || obsMs == null) return null;
  return Math.round((obsMs - eventMs) / 60000);
}

/**
 * Human label + tooltip for a Pre/Post weight enrichment source.
 * Separates portal weight-entry time from scrape first-observed time.
 * @returns {{ helperText: string, title: string, lines: string[] }}
 */
export function describeWeightProvenance({
  role, // "pre" | "post"
  weightLbs,
  source,
  observedAt,
  portalEventAt,
  attachBatchId,
  attachReason,
  needsManagerCorrection = false,
}) {
  const blank = "Blank = null · 0 is valid";
  if (role === "pre" && needsManagerCorrection) {
    return {
      helperText: "Missing — no recoverable historical portal observation",
      title: "Manager correction required to set Pre Weight",
      lines: ["Missing — no recoverable historical portal observation"],
    };
  }
  if (weightLbs === null || weightLbs === undefined || weightLbs === "") {
    return { helperText: blank, title: "", lines: [blank] };
  }

  const entered = formatEvidenceClockEt(portalEventAt);
  const observed = formatEvidenceClockEt(observedAt);
  const lag = captureLagMinutes(portalEventAt, observedAt);
  const lines = [];
  if (entered) lines.push(`Weight entered: ${entered}`);
  if (observed) {
    lines.push(
      entered
        ? `First observed: ${observed}`
        : `First observed by scrape: ${observed}`
    );
  }
  if (lag != null && lag >= 0) lines.push(`Capture lag: ${lag} min`);

  const batchBit =
    attachBatchId != null && attachBatchId !== ""
      ? `Batch ${attachBatchId}`
      : "";
  const src = String(source || "");
  const titleBits = [];
  if (
    src === "portal_weight_num_historical" ||
    attachReason === "RECOVERED_FROM_HISTORICAL_PORTAL_OBSERVATION"
  ) {
    titleBits.push("Source: Historical Portal Observation");
  } else if (
    src === "portal_weight_num" ||
    attachReason === "CURRENT_WEIGHT_ATTACHED_TO_LATEST_EVENT"
  ) {
    titleBits.push("Source: Portal scrape observation");
  } else if (src) {
    titleBits.push(src);
  }
  if (batchBit) titleBits.push(batchBit);
  if (attachReason && !titleBits.some((t) => t.includes(attachReason))) {
    titleBits.push(String(attachReason));
  }

  if (!lines.length) {
    return { helperText: blank, title: titleBits.join(" · "), lines: [blank] };
  }
  return {
    helperText: lines.join(" · "),
    title: titleBits.join(" · "),
    lines,
  };
}

export function buildEditBagPayloadDraft({
  draft,
  lines,
  isHd,
}) {
  return {
    service_type: String(draft.service_type || "WF").toUpperCase(),
    rush_flag: draft.rush_flag,
    entry_at: draft.entry_at || null,
    rack: draft.service_type === "HD" ? null : draft.rack,
    pre_weight_lbs: parseWeightInput(draft.pre_weight_lbs),
    post_weight_lbs: parseWeightInput(draft.post_weight_lbs),
    completion_at: draft.completion_at || null,
    completed_by: draft.completed_by || null,
    completion_employee: draft.completed_by || null,
    no_chargeable: Boolean(draft.no_chargeable),
    no_charge_reason: draft.no_chargeable ? draft.no_charge_reason : null,
    bulk_items:
      isHd || draft.no_chargeable
        ? []
        : (lines || [])
            .filter((l) => Number(l.quantity) > 0)
            .map((l) => ({ workitem_id: l.workitem_id, quantity: l.quantity })),
  };
}

/** Compare unsaved draft fields to latest saved bag for conflict recovery UI. */
export function diffEditBagDraftVsLatest({ draft, lines, latest }) {
  if (!latest) return [];
  const changes = [];
  const pairs = [
    ["Service", draft?.service_type, latest.service_type],
    ["Rush", draft?.rush_flag, latest.rush_flag || latest.rush_status],
    ["PRE lbs", draft?.pre_weight_lbs, latest.pre_weight_lbs],
    ["POST lbs", draft?.post_weight_lbs, latest.post_weight_value ?? latest.post_weight_lbs],
    ["Entry", draft?.entry_at, latest.entry_at],
    ["Completion", draft?.completion_at, latest.completion_at],
    ["Completed by", draft?.completed_by, latest.completed_by],
  ];
  for (const [label, unsaved, saved] of pairs) {
    const a = unsaved == null || unsaved === "" ? "—" : String(unsaved);
    const b = saved == null || saved === "" ? "—" : String(saved);
    if (a !== b) changes.push({ label, unsaved: a, latest: b });
  }
  const latestLines = latest.bulk_workitems || [];
  const unsavedMap = Object.fromEntries(
    (lines || []).filter((l) => Number(l.quantity) > 0).map((l) => [l.workitem_id, Number(l.quantity)])
  );
  const latestMap = Object.fromEntries(
    latestLines.map((l) => [l.workitem_id, Number(l.quantity) || 0])
  );
  const ids = new Set([...Object.keys(unsavedMap), ...Object.keys(latestMap)]);
  for (const id of ids) {
    const u = unsavedMap[id] || 0;
    const s = latestMap[id] || 0;
    if (u !== s) {
      const name =
        (lines || []).find((l) => String(l.workitem_id) === String(id))?.name ||
        latestLines.find((l) => String(l.workitem_id) === String(id))?.workitem_name ||
        `Item ${id}`;
      changes.push({ label: `Work item · ${name}`, unsaved: String(u), latest: String(s) });
    }
  }
  return changes;
}

/**
 * Merge a list-row (include_details=false) with prior detail / cache.
 * Prevents empty bulk_workitems from hiding persisted lines (42EN4J3VRB bug).
 */
export function mergeBagListRow({
  listBag,
  previousBag,
  cachedDetail,
  editingBagId,
  skipCacheMerge = false,
}) {
  if (!listBag?.bag_id) return listBag;
  const bagId = listBag.bag_id;

  if (editingBagId && bagId === editingBagId && previousBag) {
    return { ...listBag, ...previousBag, bag_id: bagId };
  }

  if (previousBag?._detailsLoaded) {
    return {
      ...listBag,
      ...previousBag,
      dashboard_status: listBag.dashboard_status ?? previousBag.dashboard_status,
      outcome: listBag.outcome ?? previousBag.outcome,
      reason_codes: listBag.reason_codes?.length
        ? listBag.reason_codes
        : previousBag.reason_codes,
      bulk_workitems: previousBag.bulk_workitems,
      scans: previousBag.scans,
      corrections: previousBag.corrections,
      _detailsLoaded: true,
    };
  }

  if (skipCacheMerge) return listBag;
  if (!cachedDetail) return listBag;

  return {
    ...listBag,
    ...cachedDetail,
    scans: cachedDetail.scans || [],
    corrections: cachedDetail.corrections || [],
    bulk_workitems:
      Array.isArray(cachedDetail.bulk_workitems) && cachedDetail.bulk_workitems.length
        ? cachedDetail.bulk_workitems
        : listBag.bulk_workitems,
    _detailsLoaded: true,
  };
}
