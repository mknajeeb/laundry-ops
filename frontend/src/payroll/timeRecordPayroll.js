const DEFAULT_OT_THRESHOLD = 40;
const DEFAULT_OT_MULTIPLIER = 1.5;
const WARN_HOURS = 35;

export function formatPayrollMoney(n, { allowZero = false } = {}) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  if (v <= 0 && !allowZero) return "—";
  return `$${v.toFixed(2)}`;
}

export function formatPayrollRate(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v <= 0) return "—";
  return `$${v.toFixed(2)}`;
}

export function workerHoursLevel(totalHours) {
  const h = Number(totalHours) || 0;
  if (h >= DEFAULT_OT_THRESHOLD) return "critical";
  if (h > WARN_HOURS) return "warning";
  return "normal";
}

export function computeSummaryHoursLevel(totalHours, userId, workerTotals = {}) {
  if (userId) {
    return workerHoursLevel(workerTotals[String(userId)] ?? totalHours);
  }
  const uids = Object.keys(workerTotals);
  if (uids.length === 1) {
    return workerHoursLevel(workerTotals[uids[0]]);
  }
  return workerHoursLevel(totalHours);
}

function rateEntryFromSources(uid, cat, regular, calendar, orgOt) {
  const cal = calendar[cat] || calendar.default || {};
  const multiplier = Number(cal.overtime_multiplier || DEFAULT_OT_MULTIPLIER);
  const otThreshold = Number(cal.overtime_threshold_hours ?? orgOt) || DEFAULT_OT_THRESHOLD;
  const otEnabled = regular > 0;
  const otRate = otEnabled ? regular * multiplier : null;
  return {
    regular_rate: regular > 0 ? regular : null,
    ot_rate: otRate,
    ot_enabled: otEnabled,
    ot_threshold: otThreshold,
    worker_category: cat,
  };
}

export function buildWorkerRateMap(
  workers = [],
  scheduleSettings = null,
  calendarBundle = null,
  rows = [],
) {
  const orgOt = Number(
    scheduleSettings?.overtime_threshold_hours
      ?? calendarBundle?.org_schedule_settings?.overtime_threshold_hours
      ?? DEFAULT_OT_THRESHOLD,
  );
  const calendar = calendarBundle?.categories || {};
  const map = {};

  for (const w of workers) {
    const uid = String(w.user_id);
    const cat = w.worker_category || "w2";
    const regular = Number(w.default_hourly_rate || w.hourly_rate || 0);
    map[uid] = rateEntryFromSources(uid, cat, regular, calendar, orgOt);
  }

  for (const r of rows) {
    const uid = String(r.user_id);
    if (map[uid]?.regular_rate) continue;
    const regular = Number(r.hourly_rate || 0);
    if (regular <= 0) continue;
    const cat = r.worker_category || map[uid]?.worker_category || "w2";
    map[uid] = rateEntryFromSources(uid, cat, regular, calendar, orgOt);
  }

  return map;
}

export function enrichTimeRecords(rows = [], rateMap = {}, { userId = "" } = {}) {
  const workerTotals = {};
  for (const r of rows) {
    const uid = String(r.user_id);
    workerTotals[uid] = (workerTotals[uid] || 0) + Number(r.approved_hours || 0);
  }

  const byUser = {};
  for (const r of rows) {
    const uid = String(r.user_id);
    if (!byUser[uid]) byUser[uid] = [];
    byUser[uid].push(r);
  }

  const economicsById = {};
  let totalRegularCost = 0;
  let totalOtCost = 0;

  for (const [uid, userRows] of Object.entries(byUser)) {
    const fallback = rateMap[uid] || {};
    // Group by payroll week so disable_ot only affects that week.
    const byWeek = {};
    for (const r of userRows) {
      const ws = r.payroll_week_start || "_";
      if (!byWeek[ws]) byWeek[ws] = [];
      byWeek[ws].push(r);
    }

    for (const weekRows of Object.values(byWeek)) {
      const sorted = [...weekRows].sort((a, b) =>
        String(a.clock_in_at || "").localeCompare(String(b.clock_in_at || "")),
      );
      const weekOtDisabled = sorted.some((r) => r.ot_week_mode === "disable_ot");
      const otThreshold = Number(fallback.ot_threshold || DEFAULT_OT_THRESHOLD);
      let cumulative = 0;

      for (const r of sorted) {
        const hrs = Number(r.approved_hours || 0);
        const regRate = Number(
          r.resolved_hourly_rate ?? r.hourly_rate ?? fallback.regular_rate ?? 0,
        );
        const multiplier = Number(
          (fallback.ot_rate && fallback.regular_rate
            ? fallback.ot_rate / fallback.regular_rate
            : null) || DEFAULT_OT_MULTIPLIER,
        );
        const otRate = regRate > 0 ? regRate * multiplier : 0;
        const otEnabled = !weekOtDisabled && regRate > 0;
        let regH = hrs;
        let otH = 0;
        if (otEnabled) {
          const room = Math.max(0, otThreshold - cumulative);
          regH = Math.min(hrs, room);
          otH = Math.max(0, hrs - regH);
        }
        cumulative += hrs;
        const baseCost = regRate > 0 ? (regH + otH) * regRate : 0;
        const otPremium =
          otEnabled && otRate > 0 && regRate > 0 ? otH * Math.max(0, otRate - regRate) : 0;
        const rowTotal = baseCost + otPremium;
        totalRegularCost += baseCost;
        totalOtCost += otPremium;
        economicsById[r.id] = {
          regular_rate: regRate > 0 ? regRate : null,
          ot_rate: otEnabled && otRate > 0 ? otRate : null,
          regular_cost: baseCost,
          ot_cost: otPremium,
          ot_premium: otPremium,
          row_total: rowTotal,
          worker_period_hours: workerTotals[uid] || 0,
          hours_level: workerHoursLevel(workerTotals[uid]),
          ot_week_disabled: weekOtDisabled,
        };
      }
    }
  }

  const enriched = rows.map((r) => ({
    ...r,
    ...(economicsById[r.id] || {
      regular_rate: null,
      ot_rate: null,
      regular_cost: 0,
      ot_cost: 0,
      row_total: 0,
      worker_period_hours: workerTotals[String(r.user_id)] || 0,
      hours_level: workerHoursLevel(workerTotals[String(r.user_id)]),
      ot_week_disabled: r.ot_week_mode === "disable_ot",
    }),
  }));

  const totalHours = enriched.reduce((s, r) => s + Number(r.approved_hours || 0), 0);
  const totalCost = totalRegularCost + totalOtCost;
  const summaryHoursLevel = computeSummaryHoursLevel(totalHours, userId, workerTotals);

  return {
    rows: enriched,
    totalHours,
    totalCost,
    totalRegularCost,
    totalOtCost,
    summaryHoursLevel,
    workerTotals,
  };
}

function roundMoney(value) {
  return Math.round(Number(value) * 100) / 100;
}

/** Sum employer-cost analyses. Dollars and hours are added before any rate is divided. */
export function combineHourlyAnalyses(analyses, laborCostTarget = 19) {
  const list = (analyses || []).filter((item) => item && item.payable_hours != null);
  if (!list.length) return null;
  if (list.length === 1) return list[0];
  const sum = (key) => list.reduce((acc, item) => acc + Number(item[key] || 0), 0);
  const hours = sum("payable_hours");
  const gross = sum("gross_pay");
  const totalKnown = list.every((item) => item.total_employer_cost != null);
  const straightKnown = list.every((item) => item.straight_time_employer_cost != null);
  const total = totalKnown ? sum("total_employer_cost") : null;
  const straight = straightKnown ? sum("straight_time_employer_cost") : null;
  const extra = totalKnown ? sum("employer_expenses") : null;
  const burden = totalKnown && gross > 0.005 ? roundMoney((extra / gross) * 100) : null;
  const effective = total != null && hours > 0.005 ? roundMoney(total / hours) : null;
  const base = straight != null && hours > 0.005 ? roundMoney(straight / hours) : null;
  const impact = effective != null && base != null ? roundMoney(effective - base) : null;
  const wageNum = list.reduce((acc, item) => {
    const wage = Number(item.base_wage);
    const itemHours = Number(item.payable_hours || 0);
    return Number.isFinite(wage) ? acc + wage * itemHours : acc;
  }, 0);
  const target = Number(laborCostTarget) > 0 ? Number(laborCostTarget) : 19;
  const delta = effective == null ? null : roundMoney(effective - target);
  const applicable = list.every((item) => item.burden_status === "not_applicable");
  const active = list
    .map((item) => item.burden_status)
    .filter((status) => status && status !== "not_applicable");
  let burdenStatus = "estimated";
  let burdenLabel = "Mixed";
  if (!totalKnown) {
    burdenStatus = "unavailable";
    burdenLabel = "Unavailable";
  } else if (applicable) {
    burdenStatus = "not_applicable";
    burdenLabel = "N/A";
  } else if (active.every((status) => status === "configured")) {
    burdenStatus = "configured";
    burdenLabel = "Configured";
  } else if (active.every((status) => status === "actual")) {
    burdenStatus = "actual";
    burdenLabel = "Actual";
  } else if (active.every((status) => status === "estimated")) {
    burdenStatus = "estimated";
    burdenLabel = "Estimated";
  }
  return {
    worker_category: "mixed",
    cost_basis: "estimated_time_records",
    burden_status: burdenStatus,
    burden_label: burdenLabel,
    burden_percent: !totalKnown || applicable ? null : burden,
    base_wage: hours > 0.005 ? roundMoney(wageNum / hours) : null,
    base_wage_blended: new Set(list.map((item) => Number(item.base_wage))).size > 1,
    payable_hours: roundMoney(hours),
    regular_hours: roundMoney(sum("regular_hours")),
    ot_hours: roundMoney(sum("ot_hours")),
    gross_pay: roundMoney(gross),
    ot_premium: roundMoney(sum("ot_premium")),
    employer_expenses: extra == null ? null : roundMoney(extra),
    total_employer_cost: total == null ? null : roundMoney(total),
    straight_time_employer_cost: straight == null ? null : roundMoney(straight),
    base_cost_per_hour: base,
    effective_cost_per_hour: effective,
    ot_impact_per_hour: impact,
    ot_impact_percent: base ? roundMoney((impact / base) * 100) : impact === 0 ? 0 : null,
    labor_cost_target: target,
    target_delta_per_hour: delta,
    target_status: delta == null ? "unavailable" : delta > 0.005 ? "above" : "at_or_below",
    record_costs: list.flatMap((item) => item.record_costs || []),
    notes: ["Employer burden is weighted across the selected records."],
  };
}
