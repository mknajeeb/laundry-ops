/** Shared helpers for cross-period employee paystub archive downloads. */

export const DEFAULT_RECENT_PAYSTUB_BATCHES = 6;

export function recentBatchIds(batches, limit = DEFAULT_RECENT_PAYSTUB_BATCHES) {
  const list = Array.isArray(batches) ? batches : [];
  if (!list.length) return [];
  const n = Math.max(1, Number(limit) || DEFAULT_RECENT_PAYSTUB_BATCHES);
  return list.slice(-n).map((b) => b.id);
}

export function archiveWorkerCategory(batchOrCategory) {
  if (typeof batchOrCategory === "string") return batchOrCategory || "w2";
  return batchOrCategory?.worker_category || "w2";
}
