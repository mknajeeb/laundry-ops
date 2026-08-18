/** Client cache for Split Cost Simulator closed-day baselines. */

const mem = new Map();

function key(dateEt, windowDays) {
  return `${dateEt || ""}|${windowDays || 7}`;
}

export function getSplitCostBaselineCache(dateEt, windowDays) {
  const hit = mem.get(key(dateEt, windowDays));
  if (!hit) return null;
  // Soft client TTL 30 min — server also caches 6h
  if (Date.now() - hit.ts > 30 * 60 * 1000) {
    mem.delete(key(dateEt, windowDays));
    return null;
  }
  return hit.data;
}

export function setSplitCostBaselineCache(dateEt, windowDays, data) {
  if (!data) return;
  mem.set(key(dateEt, windowDays), { ts: Date.now(), data });
}

export function clearSplitCostBaselineCache() {
  mem.clear();
}
