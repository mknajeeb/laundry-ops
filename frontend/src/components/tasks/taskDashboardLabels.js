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
