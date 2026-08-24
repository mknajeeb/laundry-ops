/**
 * Review drawer expand — parse / fetch action metadata (no scans).
 */

export function parseReviewDrawerActionResponse(data) {
  const payload = data || {};
  if (payload.ok === false) {
    return {
      ok: false,
      error: payload.error || payload.message || "Failed to load bag details",
      bag: null,
      catalog: [],
    };
  }
  return {
    ok: true,
    error: null,
    bag: payload.bag || null,
    catalog: Array.isArray(payload.active_bulk_workitems)
      ? payload.active_bulk_workitems
      : [],
  };
}

export async function fetchReviewDrawerAction(getAction, selectedDateEt, bagId) {
  const res = await getAction(selectedDateEt, bagId);
  return parseReviewDrawerActionResponse(res?.data);
}
