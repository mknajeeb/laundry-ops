/** Time Records payroll classification + session rate display. */

export const CLASSIFICATION_OVERRIDE_OPTIONS = [
  { value: "", label: "Use employee default" },
  { value: "w2", label: "W-2" },
  { value: "contractor_1099", label: "1099" },
  { value: "temp", label: "Temp / One-Time" },
];

export const OT_WEEK_OPTIONS = [
  { value: "default", label: "Standard" },
  { value: "disable_ot", label: "Disable OT for this week" },
];

const CATEGORY_SHORT = {
  w2: "W-2",
  contractor_1099: "1099",
  temp: "Temp",
  tryout: "Try Out",
};

function formatRateHr(rate) {
  const n = Number(rate);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `$${n.toFixed(2)}/hr`;
}

/**
 * Temp · $17.00/hr
 * Temp · $20.00/hr (override)
 */
export function formatRecordClassificationLabel(row) {
  const code = row?.worker_category;
  const short = CATEGORY_SHORT[code] || row?.worker_category_label || code || "";
  const rate =
    formatRateHr(row?.resolved_hourly_rate ?? row?.regular_rate ?? row?.hourly_rate) ||
    null;
  const isRateOverride = row?.rate_source === "session_override";
  if (rate) {
    return isRateOverride ? `${short} · ${rate} (override)` : `${short} · ${rate}`;
  }
  if (row?.classification_source === "record_override") {
    return `${short} · Record override`;
  }
  return short;
}

export function classificationSelectValue(row) {
  if (
    row?.classification_source === "record_override" &&
    CLASSIFICATION_OVERRIDE_OPTIONS.some((opt) => opt.value && opt.value === row.worker_category)
  ) {
    return row.worker_category;
  }
  return "";
}

export function rateOverrideInputValue(row) {
  if (row?.payroll_rate_override == null || row.payroll_rate_override === "") return "";
  const n = Number(row.payroll_rate_override);
  return Number.isFinite(n) ? String(n) : "";
}

export function employeeWeekOtKey(row) {
  return `${row?.user_id}|${row?.payroll_week_start || ""}`;
}
