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
    const rateInfo = rateMap[uid] || {};
    const regRate = Number(rateInfo.regular_rate || 0);
    const otRate = Number(rateInfo.ot_rate || 0);
    const otEnabled = !!rateInfo.ot_enabled;
    const otThreshold = Number(rateInfo.ot_threshold || DEFAULT_OT_THRESHOLD);

    const sorted = [...userRows].sort((a, b) =>
      String(a.clock_in_at || "").localeCompare(String(b.clock_in_at || "")),
    );
    let cumulative = 0;

    for (const r of sorted) {
      const hrs = Number(r.approved_hours || 0);
      let regH = hrs;
      let otH = 0;
      if (otEnabled && regRate > 0) {
        const room = Math.max(0, otThreshold - cumulative);
        regH = Math.min(hrs, room);
        otH = Math.max(0, hrs - regH);
      }
      cumulative += hrs;
      // Base earnings include OT hours at the regular rate; ot_cost is premium only.
      const baseCost = regRate > 0 ? (regH + otH) * regRate : 0;
      const otPremium =
        otEnabled && otRate > 0 && regRate > 0 ? otH * Math.max(0, otRate - regRate) : 0;
      const rowTotal = baseCost + otPremium;
      totalRegularCost += baseCost;
      totalOtCost += otPremium;
      economicsById[r.id] = {
        regular_rate: rateInfo.regular_rate,
        ot_rate: rateInfo.ot_rate,
        regular_cost: baseCost,
        ot_cost: otPremium,
        ot_premium: otPremium,
        row_total: rowTotal,
        worker_period_hours: workerTotals[uid] || 0,
        hours_level: workerHoursLevel(workerTotals[uid]),
      };
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
