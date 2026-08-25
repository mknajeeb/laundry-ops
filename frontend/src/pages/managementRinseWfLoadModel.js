/** Merge primary + secondary Rinse WF API payloads for the dashboard section. */
export function mergeRinseWfDashboardPayload(primary, secondary) {
  if (!primary) return null;
  const rinse = {
    ...(primary.rinse || {}),
    ...(secondary?.rinse || {}),
    weight_totals: primary.rinse?.weight_totals ?? secondary?.rinse?.weight_totals,
    segments: primary.rinse?.segments ?? secondary?.rinse?.segments,
    specialty_metrics:
      secondary?.rinse?.specialty_metrics ?? primary.rinse?.specialty_metrics,
  };
  const review =
    secondary?.review && !secondary.review.deferred
      ? secondary.review
      : primary.review;
  return {
    date_et: primary.date_et,
    generated_at_et: primary.generated_at_et,
    rinse,
    review,
    _meta: {
      primary: primary._meta || null,
      secondary: secondary?._meta || null,
    },
  };
}
