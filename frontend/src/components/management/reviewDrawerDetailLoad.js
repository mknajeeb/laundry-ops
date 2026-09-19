/**
 * Review drawer expand — parse / fetch action metadata (no scans).
 */

import { formatReviewApiError } from "./reviewDisplayLabels";

export function parseReviewDrawerActionResponse(data) {
  const payload = data || {};
  if (payload.ok === false) {
    return {
      ok: false,
      error: formatReviewApiError(payload.error, payload.message || "Failed to load bag details"),
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

export function reviewActionRequestParams(drawerCategory, bag) {
  if (drawerCategory !== "specialty_items") return { params: {} };
  const oi = Number(bag?.order_instance_id);
  if (!Number.isFinite(oi) || oi <= 0) {
    return { missingOrderInstance: true, params: {} };
  }
  return { params: { order_instance_id: oi } };
}

export async function fetchReviewDrawerAction(getAction, selectedDateEt, bagId, options = {}) {
  const params = { ...(options.params || {}) };
  if (options.orderInstanceId != null && options.orderInstanceId !== "") {
    params.order_instance_id = options.orderInstanceId;
  }
  const res = await getAction(selectedDateEt, bagId, params);
  return parseReviewDrawerActionResponse(res?.data);
}
