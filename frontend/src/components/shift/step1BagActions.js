/**
 * Manager action visibility for Step-1 metric drawer bag cards.
 */

function hasUnresolvedSpecialtyReason(reasonCodes) {
  return (reasonCodes || []).some((c) => {
    const code = String(c || "").trim().toUpperCase();
    if (!code) return false;
    // Missing-from-portal alone is not specialty-unresolved.
    if (code === "DISAPPEARED_WITHOUT_COMPLETION") return false;
    return true;
  });
}

/**
 * @param {string} status
 * @param {{
 *   specialtyReviewResolved?: boolean,
 *   specialtyReviewUnresolved?: boolean,
 *   bulkReviewCleared?: boolean,
 *   reasonCodes?: string[],
 * }} [opts]
 */
export function actionsForBagStatus(status, opts = {}) {
  const s = String(status || "")
    .toLowerCase()
    .replace(/-/g, "_");
  const isPending = s === "pending" || s.endsWith("_pending");
  const isReview = s.includes("review");
  const isCompleted = s === "completed" || s.includes("completed");

  // Specialty unresolved wins over completed — completed alone does NOT settle specialty.
  const specialtyUnresolved =
    opts.specialtyReviewUnresolved === true
    || (
      opts.specialtyReviewUnresolved !== false
      && opts.specialtyReviewResolved !== true
      && opts.bulkReviewCleared !== true
      && hasUnresolvedSpecialtyReason(opts.reasonCodes)
    );

  const specialtyReviewResolved =
    !specialtyUnresolved
    && (opts.specialtyReviewResolved === true || opts.bulkReviewCleared === true);

  // Settled only when specialty is resolved (or never specialty-open) AND
  // completed / explicitly specialty-resolved. Completed + unresolved specialty
  // keeps Review actions.
  const isSettled =
    specialtyReviewResolved
    || (isCompleted && !specialtyUnresolved && !isReview);

  return {
    editBag: !isSettled,
    viewDetails: isSettled,
    markCompleted: !isCompleted,
    returnPending: isReview || isCompleted,
    // Unresolved pending bags can still be sent to Review Required.
    moveToReview: isPending && !isSettled && !specialtyUnresolved,
    // Settled/completed bags (not currently in review) can be sent back.
    sendBackToReview: (isSettled || isCompleted) && !isReview,
    correctEntry: false,
    correctWeight: false,
    correctCompletion: false,
    exclude: true,
    isPending,
    isReview,
    isCompleted,
    isSettled,
    specialtyReviewUnresolved: Boolean(specialtyUnresolved),
    specialtyReviewResolved: Boolean(specialtyReviewResolved),
    statusLabel: specialtyUnresolved
      ? null
      : isCompleted
        ? "COMPLETED"
        : specialtyReviewResolved
          ? "REVIEWED"
          : null,
  };
}
