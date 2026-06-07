/** Payroll Management default values for worker scheduling/payroll profile. */

export const PAYROLL_DEFAULT_REGULAR_RATE = 17;
export const PAYROLL_DEFAULT_OT_RATE = 25.5;
export const PAYROLL_DEFAULT_MAX_HOURS = 40;
export const PAYROLL_DEFAULT_OT_THRESHOLD = 30;

export function formatPayrollMoneyInput(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  return v.toFixed(2);
}

function isBlankRate(val) {
  return val === "" || val == null || Number(val) <= 0;
}

function isBlankHours(val) {
  return val === "" || val == null;
}

/** Prefill form fields when worker profile values are null/blank (does not overwrite custom values). */
export function buildPayrollSetupFormDefaults(worker = {}) {
  return {
    default_hourly_rate: isBlankRate(worker.default_hourly_rate)
      ? formatPayrollMoneyInput(PAYROLL_DEFAULT_REGULAR_RATE)
      : worker.default_hourly_rate,
    default_overtime_rate: isBlankRate(worker.default_overtime_rate)
      ? formatPayrollMoneyInput(PAYROLL_DEFAULT_OT_RATE)
      : worker.default_overtime_rate,
    max_hours_per_week: isBlankHours(worker.max_hours_per_week)
      ? PAYROLL_DEFAULT_MAX_HOURS
      : worker.max_hours_per_week,
    overtime_threshold: isBlankHours(worker.overtime_threshold)
      ? PAYROLL_DEFAULT_OT_THRESHOLD
      : worker.overtime_threshold,
  };
}
