/** Status and configured-text helpers. Strings live in the existing translation table. */

const STATUS_KEYS = {
  pending: "tasks.pin.status.pending",
  overdue: "tasks.pin.status.overdue",
  in_progress: "tasks.pin.status.in_progress",
  pending_approval: "tasks.pin.status.pending_verification",
  pending_verification: "tasks.pin.status.pending_verification",
  waiting: "tasks.pin.status.pending_verification",
  approved: "tasks.pin.status.verified",
  verified: "tasks.pin.status.verified",
  completed: "tasks.pin.status.completed",
  rejected: "tasks.pin.status.rejected",
  not_started: "tasks.pin.status.not_started",
  excused: "tasks.pin.excused",
  incomplete: "tasks.pin.status.incomplete",
  partial: "tasks.pin.status.partial",
  finished: "tasks.dashboard.finished",
  not_required: "tasks.dashboard.notRequired",
  needs_correction: "tasks.pin.status.needs_correction",
};

const PHRASE_KEYS = {
  "Waiting for Verification": "tasks.pin.status.pending_verification",
  "Pending Verification": "tasks.pin.status.pending_verification",
  Verified: "tasks.pin.status.verified",
  Completed: "tasks.pin.status.completed",
  "Not Started": "tasks.pin.status.not_started",
  "In Progress": "tasks.pin.status.in_progress",
  "In progress": "tasks.pin.status.in_progress",
  Overdue: "tasks.pin.status.overdue",
  "Needs Correction": "tasks.pin.status.needs_correction",
  "Not Required": "tasks.dashboard.notRequired",
  "Partially Verified": "tasks.dashboard.partiallyVerified",
  "Not verified": "tasks.dashboard.notVerified",
  Finished: "tasks.dashboard.finished",
  Excused: "tasks.pin.excused",
};

export function taskStatusLabel(t, status) {
  const key = STATUS_KEYS[String(status || "")];
  if (!key) return localizedStatusPhrase(t, status);
  return t(key);
}

/** Translate a fixed status phrase. Activity names are left as entered. */
export function localizedStatusPhrase(t, text) {
  const raw = String(text || "").trim();
  const key = PHRASE_KEYS[raw];
  if (!key) return raw;
  return t(key);
}

export function verificationStatusLabel(t, status) {
  if (String(status || "") === "partial") return t("tasks.dashboard.partiallyVerified");
  return taskStatusLabel(t, status);
}

export function categoryLabel(t, code, fallback) {
  const key = `tasks.pin.category.${code || ""}`;
  const translated = t(key);
  if (translated && translated !== key) return translated;
  return fallback || code || "";
}

/** Spanish is used only when that field was configured. English stays the stored field. */
export function localizedConfigured(record, locale, englishKey, spanishKey) {
  if (locale === "es") {
    const spanish = String(record?.[spanishKey] || "").trim();
    if (spanish) return spanish;
  }
  return String(record?.[englishKey] || "").trim();
}

export function localizedInstruction(record, locale) {
  return localizedConfigured(record, locale, "instructions", "instructions_es");
}

export function isVerificationRemark(remark) {
  const kind = String(remark?.remark_kind || "");
  if (kind === "verification") return true;
  if (kind === "comment") return false;
  return remark?.legacy_source === "supervisor_remark" || remark?.author_role === "supervisor";
}

export function splitActivityRemarks(remarks) {
  const comments = [];
  const verification = [];
  for (const remark of remarks || []) {
    if (isVerificationRemark(remark)) verification.push(remark);
    else comments.push(remark);
  }
  return { comments, verification };
}

export function remarkRoleLabel(t, role) {
  const key = `tasks.pin.role.${role || "employee"}`;
  const translated = t(key);
  return translated === key ? role || t("tasks.pin.role.employee") : translated;
}
