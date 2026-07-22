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
    markCompleted: !isCompleted,
    returnPending: isReview || isCompleted,
    moveToReview: isPending,
    correctEntry: true,
    correctWeight: true,
    correctCompletion: isCompleted,
    exclude: true,
    isPending,
    isReview,
    isCompleted,
  };
}
