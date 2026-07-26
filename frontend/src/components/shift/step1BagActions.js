/**
 * Manager action visibility for Step-1 metric drawer bag cards.
 */

export function actionsForBagStatus(status) {
  const s = String(status || "")
    .toLowerCase()
    .replace(/-/g, "_");
  const isPending = s === "pending" || s.endsWith("_pending");
  const isReview = s.includes("review");
  const isCompleted = s === "completed" || s.includes("completed");
  return {
    editBag: true,
    markCompleted: !isCompleted,
    returnPending: isReview || isCompleted,
    // Pending bags and completed bags (e.g. Missing PRE) can be sent to Review Required.
    moveToReview: isPending || isCompleted,
    // Legacy separate correction flows replaced by Edit Bag.
    correctEntry: false,
    correctWeight: false,
    correctCompletion: false,
    exclude: true,
    isPending,
    isReview,
    isCompleted,
  };
}
