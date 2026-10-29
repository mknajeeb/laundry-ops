/** Friendly Task Dashboard status labels (never show raw codes). */

export const STATUS_LABELS = {
  pending: "Not Started",
  not_started: "Not Started",
  in_progress: "In Progress",
  pending_approval: "Waiting for Verification",
  pending_verification: "Waiting for Verification",
  approved: "Verified",
  verified: "Verified",
  completed: "Completed",
  rejected: "Needs Correction",
  overdue: "Overdue",
  partial: "In Progress",
};

export function friendlyStatusLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  return STATUS_LABELS[key] || "Not Started";
}

export function statusChipColor(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "approved" || key === "verified" || key === "completed") return "success";
  if (key === "pending_approval" || key === "pending_verification") return "warning";
  if (key === "rejected" || key === "overdue") return "error";
  if (key === "in_progress" || key === "partial") return "info";
  return "default";
}

export const COMPLETION_LABELS = {
  not_started: "Not Started",
  in_progress: "In Progress",
  completed: "Completed",
};

export const VERIFICATION_LABELS = {
  not_required: "Not Required",
  waiting: "Waiting for Verification",
  partial: "Partially Verified",
  verified: "Verified",
  needs_correction: "Needs Correction",
};

export function completionLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  return COMPLETION_LABELS[key] || "Not Started";
}

export function verificationLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  return VERIFICATION_LABELS[key] || "Not Required";
}

export function completionChipColor(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "completed") return "success";
  if (key === "in_progress") return "info";
  return "default";
}

export function verificationChipColor(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "verified") return "success";
  if (key === "waiting" || key === "partial") return "warning";
  if (key === "needs_correction") return "error";
  return "default";
}

export const DEFAULT_CATEGORY_TABS = [
  { code: "start_of_day", name: "Start of Day" },
  { code: "intra_day", name: "Intra-Day" },
  { code: "end_of_day", name: "End of Day" },
  { code: "inventory", name: "Inventory" },
];

export function formatEtWall(value) {
  if (!value) return "—";
  const text = String(value).replace("T", " ");
  return text.length >= 16 ? text.slice(0, 16) : text;
}
