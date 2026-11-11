/** Finalize Payroll batch navigator. Pay period is not a batch identity. */

import { canonicalInclusiveYmd } from "../utils/businessTime";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const FINALIZE_NAV_INITIAL_COUNT = 5;

export const FINALIZE_NAV_SECTIONS = [
  { key: "w2", label: "W-2", categories: ["w2"] },
  { key: "contractor_1099", label: "1099", categories: ["contractor_1099"] },
  { key: "temp", label: "Temp / One-Time", categories: ["temp", "tryout"] },
];

function ymd(val) {
  const s = String(val || "");
  return s.length >= 10 ? s.slice(0, 10) : s;
}

function monthDay(val) {
  const [y, m, d] = ymd(val).split("-").map((x) => parseInt(x, 10));
  if (!y || !m || !d || m < 1 || m > 12) return ymd(val);
  return `${MONTHS[m - 1]} ${d}`;
}

export function finalizeBatchStatusLabel(batch) {
  return batch?.payroll_display?.display_status_label || "Draft";
}

/** Sep 7–Sep 13 · W2-2026-019 · Ready For Payroll */
export function formatFinalizeBatchRow(batch) {
  const periodDates = canonicalInclusiveYmd(batch?.pay_period_start, batch?.pay_period_end);
  const period = `${monthDay(periodDates.start)}\u2013${monthDay(periodDates.end)}`;
  const name = batch?.batch_name || (batch?.id != null ? `Batch ${batch.id}` : "Batch");
  return `${period} · ${name} · ${finalizeBatchStatusLabel(batch)}`;
}

export function sortFinalizeBatches(batches = []) {
  return [...batches].sort((a, b) => {
    const endOf = (batch) =>
      canonicalInclusiveYmd(batch?.pay_period_start, batch?.pay_period_end).end;
    const byEnd = ymd(endOf(b)).localeCompare(ymd(endOf(a)));
    if (byEnd) return byEnd;
    return Number(b?.id) - Number(a?.id);
  });
}

export function groupFinalizeBatches(batches = []) {
  return FINALIZE_NAV_SECTIONS.map((section) => ({
    ...section,
    items: sortFinalizeBatches(
      batches.filter((b) => section.categories.includes(b?.worker_category)),
    ),
  }));
}

export function visibleFinalizeBatches(items = [], expanded = false, limit = FINALIZE_NAV_INITIAL_COUNT) {
  if (expanded) return items;
  return items.slice(0, limit);
}
