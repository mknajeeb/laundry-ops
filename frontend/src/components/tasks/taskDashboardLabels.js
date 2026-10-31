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
  waiting: "Pending Verification",
  pending_verification: "Pending Verification",
  partial: "Partially Verified",
  verified: "Verified",
  needs_correction: "Needs Correction",
};

/** Unified compact badge vocabulary for the redesigned dashboard. */
export const DASHBOARD_STATUS_BADGES = [
  "Not Started",
  "In Progress",
  "Completed",
  "Pending Verification",
  "Partially Verified",
  "Verified",
  "Needs Correction",
];

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

/** Checklist / group-item check-off status (not assignment participation). */
export const CHECKLIST_ITEM_LABELS = {
  pending: "Not checked off",
  not_started: "Not checked off",
  completed: "Checked off",
  in_progress: "In Progress",
  pending_approval: "Waiting for Verification",
  approved: "Verified",
  verified: "Verified",
  rejected: "Needs Correction",
};

export function checklistItemLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  return CHECKLIST_ITEM_LABELS[key] || "Not checked off";
}

const FINISHED_PARTICIPATION = new Set([
  "finished",
  "completed",
  "approved",
  "pending_approval",
  "pending_verification",
  "verified",
  "rejected",
]);

/** This employee's own timer. Do not infer it from a partner or the checklist. */
export function participationStatusOf(contribution) {
  const explicit = String(contribution?.participation_status || "").trim().toLowerCase();
  if (explicit === "finished" || explicit === "in_progress" || explicit === "not_started") {
    return explicit;
  }
  const st = String(contribution?.status || contribution?.activity?.status || "")
    .trim()
    .toLowerCase();
  if (st === "in_progress") return "in_progress";
  if (FINISHED_PARTICIPATION.has(st)) return "finished";
  return "not_started";
}

export function participationLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  if (key === "finished") return "Finished";
  if (key === "in_progress") return "In Progress";
  return "Not Started";
}

export function overallLabel(status) {
  const key = String(status || "").trim().toLowerCase();
  return (
    {
      not_started: "Not Started",
      in_progress: "In Progress",
      pending_verification: "Pending Verification",
      partial: "Partially Verified",
      verified: "Verified",
      completed: "Completed",
      needs_correction: "Needs Correction",
      overdue: "Overdue",
    }[key] || "In Progress"
  );
}

/** Headline counts: employees for participation, assignments for completion. */
export function dashboardHeadlineMetrics(rows) {
  const list = Array.isArray(rows) ? rows : [];
  let employeesAssigned = 0;
  let employeesStarted = 0;
  for (const row of list) {
    const contribs = Array.isArray(row?.contributions) ? row.contributions : [];
    employeesAssigned += contribs.length;
    for (const contrib of contribs) {
      const part = participationStatusOf(contrib);
      if (part === "in_progress" || part === "finished") employeesStarted += 1;
    }
  }
  const completedActivities = list.filter(
    (row) => String(row?.completion_status || "") === "completed"
  ).length;
  const verifiedActivities = list.filter(
    (row) =>
      String(row?.verification_status || "") === "verified" ||
      String(row?.overall_status || "") === "verified"
  ).length;
  const pendingVerification = list.filter((row) => {
    const verification = String(row?.verification_status || "");
    const overall = String(row?.overall_status || "");
    return verification === "waiting" || verification === "partial" || overall === "pending_verification";
  }).length;
  return {
    employeesAssigned,
    employeesStarted,
    completedActivities,
    verifiedActivities,
    pendingVerification,
  };
}

export function participationSummary({ finished, assigned, checklistDone, checklistRequired }) {
  const people = `${finished} of ${assigned} employees finished`;
  if (Number(checklistRequired) > 0) {
    return `${people} · ${checklistDone} of ${checklistRequired} checklist items completed`;
  }
  return people;
}

export function isChecklistTimestamp(activity) {
  if (!activity) return false;
  if (activity.timestamp_kind === "checklist_checkoff") return true;
  return String(activity.activity_kind || "") === "group_item";
}
