/** Floor inventory workflow helpers — presentation + filtering only. */

import { isPinHubAppSessionActive, loadPinHubAppSession } from "./pinHubSession";

export const FLOOR_STOCK_MODES = ["count", "low", "out", "recount"];

export const FLOOR_QUICK_NOTES = [
  { label: "Opened", value: "Opened new box" },
  { label: "Damaged", value: "Damaged" },
  { label: "Missing", value: "Missing" },
  { label: "Received", value: "Received today" },
];

/**
 * Floor Count shell from PIN Stock / shared-device entry — not viewport width.
 * Manager direct /inventory (no pin-hub app session) keeps tabs + Dashboard.
 */
export function isFloorInventoryWorkflow({ pinHubApp } = {}) {
  const hub = pinHubApp !== undefined ? pinHubApp : loadPinHubAppSession();
  return Boolean(hub) || isPinHubAppSessionActive();
}

export function itemIsStatusTracked(item) {
  return String(item?.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
}

export function itemCurrentQty(item) {
  return Number(item?.current_on_hand ?? item?.on_hand_qty ?? 0);
}

export function itemIsLow(item) {
  if (!item || item.is_active === false) return false;
  if (itemIsStatusTracked(item)) {
    const s = String(item.status_level || "OK").toUpperCase();
    return s === "LOW";
  }
  const current = itemCurrentQty(item);
  const reorder = Number(item.reorder_level ?? item.reorder_threshold ?? 0);
  return current > 0 && current <= reorder;
}

export function itemIsOut(item) {
  if (!item || item.is_active === false) return false;
  if (itemIsStatusTracked(item)) {
    return String(item.status_level || "OK").toUpperCase() === "OUT";
  }
  return itemCurrentQty(item) <= 0;
}

export function itemNeedsRecountUnresolved(item, draftRecounts = {}) {
  if (!item) return false;
  if (draftRecounts[item.id]) return true;
  return Boolean(item.needs_recount);
}

/** Items due for today's stock check (existing due-today / weekly rules). */
export function stockCheckDueItems(items) {
  return (items || []).filter((i) => {
    if (i.is_active === false) return false;
    if (typeof i.due_for_check_today === "boolean") return i.due_for_check_today;
    return i.track_weekly_check !== false;
  });
}

export function filterFloorStockItems(items, mode, { search = "", draftRecounts = {} } = {}) {
  let list = mode === "count" ? stockCheckDueItems(items) : (items || []).filter((i) => i.is_active !== false);

  if (mode === "low") list = list.filter(itemIsLow);
  else if (mode === "out") list = list.filter(itemIsOut);
  else if (mode === "recount") list = list.filter((i) => itemNeedsRecountUnresolved(i, draftRecounts));

  const q = String(search || "").trim().toLowerCase();
  if (!q) return list;
  return list.filter(
    (i) =>
      (i.name || i.item_name || "").toLowerCase().includes(q) ||
      (i.category_name || "").toLowerCase().includes(q) ||
      (i.sku || "").toLowerCase().includes(q) ||
      (i.barcode || "").toLowerCase().includes(q),
  );
}

export function itemIsDone(item, counts, statuses, recounts) {
  if (recounts[item.id]) return true;
  if (itemIsStatusTracked(item)) return Boolean(statuses[item.id]);
  return counts[item.id] !== "" && counts[item.id] != null;
}

export function stockCheckProgress(items, counts, statuses, recounts) {
  const list = stockCheckDueItems(items);
  const total = list.length;
  const done = list.filter((i) => itemIsDone(i, counts, statuses, recounts)).length;
  return { done, total };
}

export function emptyFloorFilterMessage(mode) {
  if (mode === "low") return "No low items";
  if (mode === "out") return "No out-of-stock items";
  if (mode === "recount") return "No recounts needed";
  return "No stock items";
}

export function compactQtyDiff(entered, current) {
  if (entered === "" || entered == null) return null;
  const n = Number(entered);
  if (!Number.isFinite(n)) return null;
  const c = Number(current) || 0;
  const d = n - c;
  if (d === 0) return null;
  return d;
}
