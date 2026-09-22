import {
  addDaysYmd,
  businessTodayYmd,
  formatWeekRangeLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";

/** Normalize API date to YYYY-MM-DD for comparisons. */
export function normPayPeriodYmd(val) {
  if (!val) return "";
  const s = String(val);
  if (s.length >= 10 && s[4] === "-" && s[7] === "-") return s.slice(0, 10);
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s.slice(0, 10);
  return d.toISOString().slice(0, 10);
}

/** Weekly pay period options for dropdowns. */
export function buildPayPeriodOptions(weekStartsOn = 0, { weeksBack = 78, weeksForward = 8 } = {}) {
  const today = businessTodayYmd();
  const currentStart = weekStartFromDate(today, weekStartsOn);
  const options = [];
  for (let offset = weeksForward; offset >= -weeksBack; offset -= 1) {
    const start = addDaysYmd(currentStart, offset * 7);
    const end = weekEndFromStart(start);
    options.push({
      start,
      end,
      key: `${start}|${end}`,
      label: formatWeekRangeLabel(start, end),
      year: start.slice(0, 4),
    });
  }
  return options;
}

export function findPayPeriodOption(options, start, end) {
  const key = `${normPayPeriodYmd(start)}|${normPayPeriodYmd(end)}`;
  return options.find((o) => o.key === key) || null;
}

function periodKey(start, end) {
  return `${normPayPeriodYmd(start)}|${normPayPeriodYmd(end)}`;
}

const MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Sep 7" — deterministic, not locale-dependent. */
export function formatMonthDayLabel(ymd) {
  const [y, m, d] = String(ymd || "").split("-").map((x) => parseInt(x, 10));
  if (!y || !m || !d || m < 1 || m > 12) return String(ymd || "");
  return `${MONTH_SHORT[m - 1]} ${d}`;
}

/** Week label for Analysis availability, e.g. "Sep 7–Sep 13". */
export function formatPayrollWeekLabel(start, end) {
  return `${formatMonthDayLabel(normPayPeriodYmd(start))}\u2013${formatMonthDayLabel(normPayPeriodYmd(end))}`;
}

/** Select value for one canonical payout batch. Never a pay-period key. */
export function accountantBatchOptionKey(batchId) {
  return `batch:${batchId}`;
}

/**
 * For Accountant → By Batch label.
 * Batch name first, status second, period last.
 * Example: "W2-2026-019 · Paid · Sep 7–Sep 13"
 */
export function formatAccountantByBatchOptionLabel(batch, status) {
  const start = normPayPeriodYmd(batch?.pay_period_start);
  const end = normPayPeriodYmd(batch?.pay_period_end);
  const period = `${formatMonthDayLabel(start)}\u2013${formatMonthDayLabel(end)}`;
  const name = batch?.batch_name || (batch?.id != null ? `Batch ${batch.id}` : "Batch");
  return status ? `${name} · ${status} · ${period}` : `${name} · ${period}`;
}

/**
 * One option per payout batch. Same pay period does not collapse rows.
 * Selection key is the canonical batch id.
 */
export function buildAccountantBatchOptions(batches = [], batchStatusLabel) {
  const options = [];
  for (const b of batches) {
    if (b?.id == null || b.id === "") continue;
    const start = normPayPeriodYmd(b.pay_period_start);
    const end = normPayPeriodYmd(b.pay_period_end);
    if (!start || !end) continue;
    const status = batchStatusLabel
      ? batchStatusLabel(b)
      : b.payroll_display?.display_status_label || null;
    options.push({
      start,
      end,
      key: accountantBatchOptionKey(b.id),
      label: formatAccountantByBatchOptionLabel(b, status),
      year: start.slice(0, 4),
      fromBatch: true,
      batchStatus: status || b.payroll_display?.display_status || null,
      batchId: b.id,
      batchName: b.batch_name || null,
    });
  }
  return options.sort((a, b) => {
    const byStart = b.start.localeCompare(a.start);
    if (byStart) return byStart;
    return Number(b.batchId) - Number(a.batchId);
  });
}

/**
 * Resolve a For Accountant selection by canonical batch id only.
 * Period keys such as "2026-09-07|2026-09-13" do not match.
 */
export function resolveAccountantBatchById(batches = [], batchId) {
  if (batchId == null || batchId === "") return null;
  const raw = String(batchId);
  if (raw.includes("|")) return null;
  const id = raw.startsWith("batch:") ? raw.slice("batch:".length) : raw;
  if (!id || id.includes("|")) return null;
  return batches.find((b) => String(b?.id) === id) || null;
}

/** Merge batch periods with generated weeks; dedupe by start|end.

  Period labels are week identity only (e.g. "Mon, Sep 14 – Sun, Sep 20").
  Never append Paid / Pending / Draft — those are batch-level statuses.

  Optional week-level Analysis flag may append " · Available in Analysis"
  when analysisAvailableKeys contains the period key.
*/
export function mergePayPeriodOptions(
  generated = [],
  batches = [],
  _batchStatusLabel,
  { analysisAvailableKeys = null } = {},
) {
  const map = new Map();
  for (const o of generated) {
    map.set(o.key, { ...o, fromBatch: false, batchStatus: null });
  }
  for (const b of batches) {
    const start = normPayPeriodYmd(b.pay_period_start);
    const end = normPayPeriodYmd(b.pay_period_end);
    if (!start || !end) continue;
    const key = periodKey(start, end);
    // _batchStatusLabel intentionally unused: period labels are not batch statuses.
    const analysisAvailable =
      analysisAvailableKeys instanceof Set
        ? analysisAvailableKeys.has(key)
        : Array.isArray(analysisAvailableKeys)
          ? analysisAvailableKeys.includes(key)
          : false;
    const baseLabel = formatWeekRangeLabel(start, end);
    const label = analysisAvailable ? `${baseLabel} · Available in Analysis` : baseLabel;
    map.set(key, {
      start,
      end,
      key,
      label,
      year: start.slice(0, 4),
      fromBatch: true,
      batchStatus: null,
      analysisAvailable: Boolean(analysisAvailable),
      // Keep a representative batch id for callers that still sync period→batch,
      // but do not treat it as period status.
      batchId: b.id,
    });
  }
  return Array.from(map.values()).sort((a, b) => b.start.localeCompare(a.start));
}

/**
 * Default ~9 weeks (~2 months); expanded loads full history.
 * batchOnly = one option per canonical batch (For Accountant → By Batch).
 * Pay period is not unique: two batches in the same week both remain.
 * Non-batchOnly period labels never include Paid/Pending/Draft.
 */
export function buildPayrollPeriodChoices(
  weekStartsOn = 0,
  batches = [],
  { expanded = false, batchStatusLabel, batchOnly = false, analysisAvailableKeys = null } = {},
) {
  if (batchOnly) {
    return buildAccountantBatchOptions(batches, batchStatusLabel);
  }
  const weeksBack = expanded ? 78 : 9;
  const weeksForward = expanded ? 8 : 2;
  const generated = buildPayPeriodOptions(weekStartsOn, { weeksBack, weeksForward });
  return mergePayPeriodOptions(generated, batches, batchStatusLabel, {
    analysisAvailableKeys,
  });
}

/** Group options by year for MUI Select ListSubheader. */
export function groupPayPeriodOptionsByYear(options = []) {
  const years = [...new Set(options.map((o) => o.year))].sort((a, b) => b.localeCompare(a));
  return years.map((year) => ({
    year,
    items: options.filter((o) => o.year === year),
  }));
}
