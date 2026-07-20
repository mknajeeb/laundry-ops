/** Shared OT premium display helpers — presentation only; does not change gross. */

export const DEFAULT_OT_MULTIPLIER = 1.5;

export const OT_PREMIUM_TOOLTIP =
  "OT Premium represents only the additional amount paid above the employee’s regular hourly rate.";

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function resolveOtRate(regularRate, { otRate = null, multiplier = DEFAULT_OT_MULTIPLIER } = {}) {
  const rate = num(regularRate);
  const explicit = num(otRate);
  if (explicit > 0) return explicit;
  const mult = num(multiplier) > 0 ? num(multiplier) : DEFAULT_OT_MULTIPLIER;
  if (rate <= 0) return 0;
  return Math.round(rate * mult * 100) / 100;
}

/**
 * OT Premium = OT Hours × (OT Rate − Regular Rate)
 * For time-and-a-half: OT Hours × Regular Rate × 0.5
 * Never returns a negative amount.
 */
export function computeOvertimePremium(
  otHours,
  regularRate,
  { otRate = null, multiplier = DEFAULT_OT_MULTIPLIER } = {},
) {
  const otH = Math.max(0, num(otHours));
  const rate = Math.max(0, num(regularRate));
  if (otH <= 0 || rate <= 0) return 0;
  const otR = resolveOtRate(rate, { otRate, multiplier });
  const premiumRate = Math.max(0, otR - rate);
  return Math.round(otH * premiumRate * 100) / 100;
}

/**
 * Regular/Base Earnings include OT hours at the regular rate (when OT rate ≥ regular).
 * Reconciliation: base + otPremium + other = gross
 * OT Premium is never negative.
 */
export function computeEarningsBreakdown(line, { multiplier = DEFAULT_OT_MULTIPLIER } = {}) {
  const regH = Math.max(0, num(line?.approved_hours ?? line?.regular_hours));
  const otH = Math.max(0, num(line?.ot_hours));
  const rate = Math.max(0, num(line?.rate ?? line?.regular_rate));
  const rawOt = line?.ot_rate;
  const explicitOt = num(rawOt) > 0 ? rawOt : null;
  const otR =
    otH > 0 && rate > 0 ? resolveOtRate(rate, { otRate: explicitOt, multiplier }) : 0;

  let otPremium = computeOvertimePremium(otH, rate, {
    otRate: otR > 0 ? otR : explicitOt,
    multiplier,
  });
  let baseEarnings;
  if (rate <= 0) {
    // Salaried / non-hourly.
    baseEarnings = 0;
    otPremium = 0;
  } else if (otR > 0 && otR < rate) {
    baseEarnings = Math.round((regH * rate + otH * otR) * 100) / 100;
    otPremium = 0;
  } else {
    baseEarnings = Math.round((regH + otH) * rate * 100) / 100;
  }

  let gross = num(line?.gross_amount ?? line?.total_amount ?? line?.gross_wages ?? line?.gross_pay);
  if (!(gross > 0) && (regH > 0 || otH > 0 || rate > 0)) {
    const otherFields =
      num(line?.sick_pay_amount) +
      num(line?.bonus_tip_amount) +
      num(line?.reimbursement_amount) +
      num(line?.adjustments);
    gross = Math.round((regH * rate + otH * otR + otherFields) * 100) / 100;
  }
  let otherEarnings = Math.round((gross - baseEarnings - otPremium) * 100) / 100;
  if (otherEarnings < 0 && Math.abs(otherEarnings) <= 0.02) {
    baseEarnings = Math.round((baseEarnings + otherEarnings) * 100) / 100;
    otherEarnings = 0;
  }
  if (otPremium < 0) {
    otPremium = 0;
    otherEarnings = Math.round((gross - baseEarnings - otPremium) * 100) / 100;
  }
  return {
    regular_hours: Math.round(regH * 100) / 100,
    ot_hours: Math.round(otH * 100) / 100,
    regular_rate: Math.round(rate * 100) / 100,
    ot_rate: otR,
    base_earnings: baseEarnings,
    ot_premium: Math.max(0, otPremium),
    other_earnings: otherEarnings,
    gross_pay: Math.round(gross * 100) / 100,
  };
}

export function lineGrossAmount(line) {
  return num(line?.gross_amount ?? line?.total_amount ?? line?.gross_wages ?? line?.gross_pay);
}

/** Assert display row reconciles; used by report/register sanity checks. */
export function earningsReconcile(row, eps = 0.02) {
  const base = num(row?.base_earnings);
  const prem = Math.max(0, num(row?.ot_premium));
  const other = num(row?.other_earnings);
  const gross = num(row?.gross_pay);
  return Math.abs(base + prem + other - gross) <= eps;
}
