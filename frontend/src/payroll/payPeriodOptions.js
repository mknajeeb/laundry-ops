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

/** Merge batch periods with generated weeks; dedupe by start|end. */
export function mergePayPeriodOptions(generated = [], batches = [], batchStatusLabel) {
  const map = new Map();
  for (const o of generated) {
    map.set(o.key, { ...o, fromBatch: false, batchStatus: null });
  }
  for (const b of batches) {
    const start = normPayPeriodYmd(b.pay_period_start);
    const end = normPayPeriodYmd(b.pay_period_end);
    if (!start || !end) continue;
    const key = periodKey(start, end);
    const baseLabel = formatWeekRangeLabel(start, end);
    const status = batchStatusLabel
      ? batchStatusLabel(b)
      : b.accountant_processing_status || null;
    const label = status ? `${baseLabel} · ${status}` : baseLabel;
    map.set(key, {
      start,
      end,
      key,
      label,
      year: start.slice(0, 4),
      fromBatch: true,
      batchStatus: status || b.accountant_processing_status || b.status,
      batchId: b.id,
    });
  }
  return Array.from(map.values()).sort((a, b) => b.start.localeCompare(a.start));
}

/** Default ~9 weeks (~2 months); expanded loads full history. batchOnly = accountant periods only. */
export function buildPayrollPeriodChoices(
  weekStartsOn = 0,
  batches = [],
  { expanded = false, batchStatusLabel, batchOnly = false } = {},
) {
  if (batchOnly) {
    return mergePayPeriodOptions([], batches, batchStatusLabel);
  }
  const weeksBack = expanded ? 78 : 9;
  const weeksForward = expanded ? 8 : 2;
  const generated = buildPayPeriodOptions(weekStartsOn, { weeksBack, weeksForward });
  return mergePayPeriodOptions(generated, batches, batchStatusLabel);
}

/** Group options by year for MUI Select ListSubheader. */
export function groupPayPeriodOptionsByYear(options = []) {
  const years = [...new Set(options.map((o) => o.year))].sort((a, b) => b.localeCompare(a));
  return years.map((year) => ({
    year,
    items: options.filter((o) => o.year === year),
  }));
}
