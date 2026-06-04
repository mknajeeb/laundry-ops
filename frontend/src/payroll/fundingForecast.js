/** Client-side payroll funding forecast — mirrors backend for instant scheduling updates. */

const INCLUDE = new Set(["scheduled", "completed", "clocked_in"]);
const EXCLUDE = new Set(["cancelled", "replaced", "absent", "no_show"]);
const SICK = new Set(["sick"]);
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const CAT_LABELS = { w2: "W-2", contractor_1099: "1099", temp: "Temp" };

export function addDaysYmd(ymd, n) {
  const d = new Date(`${ymd}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export function paymentDateForWeek(weekStart, calendar = {}) {
  const paymentDow = Number(calendar.payment_day_of_week ?? 5);
  const weekStartsOn = Number(calendar.work_week_start_day ?? 0);
  const lag = Number(calendar.payment_lag_days ?? 0);
  const start = new Date(`${weekStart}T12:00:00`);
  const offset = (paymentDow - weekStartsOn + 7) % 7;
  start.setDate(start.getDate() + offset + lag);
  return start.toISOString().slice(0, 10);
}

export function paymentDayLabel(isoDate) {
  try {
    return new Date(`${isoDate}T12:00:00`).toLocaleDateString(undefined, { weekday: "long" });
  } catch {
    return "Payment day";
  }
}

function rateForEntry(entry, workers) {
  const snap = Number(entry.hourly_rate_snapshot);
  if (snap > 0) return snap;
  const w = workers.find((x) => String(x.id) === String(entry.worker_profile_id));
  return Number(w?.default_hourly_rate || 0);
}

function catForEntry(entry, workers) {
  if (entry.worker_category_snapshot) return entry.worker_category_snapshot;
  const w = workers.find((x) => String(x.id) === String(entry.worker_profile_id));
  return w?.worker_category || "w2";
}

function costForEntry(entry, workers) {
  const c = Number(entry.estimated_cost);
  if (c > 0) return c;
  const hrs = Number(entry.scheduled_hours || 0);
  const rate = rateForEntry(entry, workers);
  return hrs * rate;
}

function calendarForCategory(calendarBundle, category) {
  const cats = calendarBundle?.categories || calendarBundle || {};
  return cats[category] || cats.default || {};
}

export function computeFundingForecast({
  entries = [],
  workers = [],
  settings = {},
  calendarBundle = {},
  weekStart,
  weekEnd,
  includeDraft = true,
  includePublished = true,
}) {
  const defaultCal = calendarForCategory(calendarBundle, "default");
  const paymentDate = paymentDateForWeek(weekStart, defaultCal);
  const dayLabel = paymentDayLabel(paymentDate);

  const daily = Object.fromEntries(
    DAY_NAMES.map((name, i) => [
      name,
      { date: addDaysYmd(weekStart, i), people: new Set(), hours: 0, cost: 0 },
    ]),
  );
  const byShift = {};
  const byStream = {};
  const byRole = {};
  const byCategory = {
    w2: { label: "W-2", hours: 0, cost: 0, draft_cost: 0, published_cost: 0 },
    contractor_1099: { label: "1099", hours: 0, cost: 0, draft_cost: 0, published_cost: 0 },
    temp: { label: "Temp", hours: 0, cost: 0, draft_cost: 0, published_cost: 0 },
  };
  const workerAcc = {};
  let totalCost = 0;
  let totalHours = 0;
  let draftCost = 0;
  let publishedCost = 0;
  let sickHours = 0;

  const active = (entries || []).filter(
    (e) => e && !e._deleted && e.work_date >= weekStart && e.work_date <= weekEnd,
  );

  for (const entry of active) {
    const status = entry.status || "scheduled";
    if (EXCLUDE.has(status)) continue;
    if (SICK.has(status)) {
      sickHours += Number(entry.scheduled_hours || 0);
      continue;
    }
    if (!INCLUDE.has(status)) continue;
    const pub = entry.publish_status || "draft";
    if (pub === "published" && !includePublished) continue;
    if (pub !== "published" && !includeDraft) continue;

    const hrs = Number(entry.scheduled_hours || 0);
    const cost = costForEntry(entry, workers);
    const cat = catForEntry(entry, workers);
    const catKey = byCategory[cat] ? cat : "w2";

    totalHours += hrs;
    totalCost += cost;
    if (pub === "published") publishedCost += cost;
    else draftCost += cost;

    byCategory[catKey].hours += hrs;
    byCategory[catKey].cost += cost;
    if (pub === "published") byCategory[catKey].published_cost += cost;
    else byCategory[catKey].draft_cost += cost;

    const wd = String(entry.work_date).slice(0, 10);
    const dayIdx = Math.round((new Date(`${wd}T12:00:00`) - new Date(`${weekStart}T12:00:00`)) / 86400000);
    if (dayIdx >= 0 && dayIdx < 7) {
      const dn = DAY_NAMES[dayIdx];
      daily[dn].people.add(entry.worker_profile_id);
      daily[dn].hours += hrs;
      daily[dn].cost += cost;
    }

    const shiftName = entry.shift_name || entry.shift_snapshot || "Shift";
    const streamName = entry.work_stream_name || entry.work_stream_snapshot || "—";
    const roleName = entry.role_name || entry.role_snapshot || "—";
    for (const [bucket, key] of [
      [byShift, shiftName],
      [byStream, streamName],
      [byRole, roleName],
    ]) {
      if (!bucket[key]) bucket[key] = { hours: 0, cost: 0, people: new Set() };
      bucket[key].hours += hrs;
      bucket[key].cost += cost;
      bucket[key].people.add(entry.worker_profile_id);
    }

    const wpid = entry.worker_profile_id;
    if (!workerAcc[wpid]) {
      workerAcc[wpid] = {
        worker_profile_id: wpid,
        worker_name: entry.worker_name,
        worker_category: cat,
        worker_category_label: CAT_LABELS[cat] || cat,
        hourly_rate: rateForEntry(entry, workers),
        scheduled_hours: 0,
        scheduled_days: new Set(),
        projected_cost: 0,
        role_tags: new Set(),
        stream_tags: new Set(),
      };
    }
    workerAcc[wpid].scheduled_hours += hrs;
    workerAcc[wpid].projected_cost += cost;
    workerAcc[wpid].scheduled_days.add(wd);
    if (roleName !== "—") workerAcc[wpid].role_tags.add(roleName);
    if (streamName !== "—") workerAcc[wpid].stream_tags.add(streamName);
  }

  const overtimeRisks = [];
  let totalOtHours = 0;
  const orgOt = Number(settings.overtime_threshold_hours ?? 40);

  const workerBreakdown = Object.values(workerAcc)
    .map((w) => {
      const cal = calendarForCategory(calendarBundle, w.worker_category);
      const otEnabled = cal.overtime_enabled !== false && cal.overtime_enabled !== 0;
      const threshold = Number(cal.overtime_threshold_hours ?? orgOt);
      const hrs = w.scheduled_hours;
      const otHrs = otEnabled ? Math.max(0, hrs - threshold) : 0;
      totalOtHours += otHrs;
      const heavy = Number(settings.heavy_hours_threshold ?? 35);
      const under = Number(settings.underused_hours_threshold ?? 15);
      let balance = "Balanced";
      if (otHrs > 0) balance = "Overtime Risk";
      else if (hrs >= heavy) balance = "Heavy";
      else if (hrs < under && w.scheduled_days.size <= 2) balance = "Underused";

      const row = {
        ...w,
        scheduled_hours: hrs,
        scheduled_days: w.scheduled_days.size,
        projected_cost: w.projected_cost,
        regular_hours: otEnabled ? Math.min(hrs, threshold) : hrs,
        overtime_hours: otHrs,
        overtime_threshold: threshold,
        overtime_risk: otHrs > 0,
        balance_label: balance,
        role_tags: [...w.role_tags],
        stream_tags: [...w.stream_tags],
      };
      if (otHrs > 0) {
        overtimeRisks.push({
          worker_profile_id: w.worker_profile_id,
          worker_name: w.worker_name,
          scheduled_hours: hrs,
          overtime_hours: otHrs,
        });
      }
      return row;
    })
    .sort((a, b) => b.projected_cost - a.projected_cost);

  const serializeBucket = (bucket) =>
    Object.entries(bucket).map(([name, v]) => ({
      name,
      hours: v.hours,
      cost: v.cost,
      people_count: v.people?.size ?? 0,
    }));

  return {
    estimated: true,
    disclaimer: "Projected funding estimate from schedule — not final payroll.",
    payment_date: paymentDate,
    payment_day_label: dayLabel,
    card_title: `Payroll Needed for ${dayLabel}`,
    work_week_start: weekStart,
    work_week_end: weekEnd,
    total_projected_cost: totalCost,
    total_scheduled_hours: totalHours,
    draft_cost: draftCost,
    published_cost: publishedCost,
    category_breakdown: byCategory,
    daily_breakdown: DAY_NAMES.map((day) => ({
      day,
      date: daily[day].date,
      people_count: daily[day].people.size,
      hours: daily[day].hours,
      cost: daily[day].cost,
    })),
    shift_breakdown: serializeBucket(byShift),
    stream_breakdown: serializeBucket(byStream),
    role_breakdown: serializeBucket(byRole),
    worker_breakdown: workerBreakdown,
    overtime_risks: overtimeRisks,
    overtime_risk_count: overtimeRisks.length,
    projected_overtime_hours: totalOtHours,
    sick_hours: sickHours,
  };
}
