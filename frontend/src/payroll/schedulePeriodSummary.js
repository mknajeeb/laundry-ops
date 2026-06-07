/**
 * Payroll period summaries for Scheduling / Roster Board (schedule-based, not final payroll).
 */

import {
  addDaysYmd,
  businessTodayYmd,
  formatDateShortLabel,
  formatWeekRangeLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";
import { computeFundingForecast, paymentDateForWeek, paymentDayLabel } from "./fundingForecast";

export const SCHEDULE_ESTIMATE_LABEL = "Schedule-based estimate";
export const PROJECTED_PAYROLL_LABEL = "Projected payroll";

export const PERIOD_OPTIONS = [
  { id: "this_week", label: "This Week" },
  { id: "next_week", label: "Next Week" },
  { id: "last_pay_period", label: "Last Payroll Period" },
  { id: "current_pay_period", label: "Current Payroll Period" },
  { id: "next_pay_period", label: "Next Payroll Period" },
];

function filterEntriesInRange(entries, start, end) {
  return (entries || []).filter((e) => {
    if (!e || e._deleted) return false;
    const wd = String(e.work_date).slice(0, 10);
    return wd >= start && wd <= end;
  });
}

/** Work week containing anchor date (parameterized week_starts_on). */
export function workWeekForDate(anchorYmd, weekStartsOn = 0) {
  const start = weekStartFromDate(anchorYmd, weekStartsOn);
  const end = weekEndFromStart(start);
  return {
    start,
    end,
    label: formatWeekRangeLabel(start, end),
    payment_date: null,
  };
}

export function buildCalendarBundle(settings, calendarSettings = null) {
  const cats = calendarSettings?.categories || {};
  const def = cats.default || cats.w2 || {};
  const w2 = cats.w2 || def;
  const c1099 = cats.contractor_1099 || def;
  const temp = cats.temp || def;

  const weekStartsOn = Number(
    def.work_week_start_day ?? settings?.week_starts_on ?? 0,
  );
  const paymentDow = Number(def.payment_day_of_week ?? settings?.payment_day_of_week ?? 5);
  const lag = Number(def.payment_lag_days ?? settings?.payment_lag_days ?? 0);

  return {
    weekStartsOn,
    paymentDow,
    paymentLagDays: lag,
    forecastFlags: {
      includeDraft:
        def.include_draft_schedule_in_forecast ??
        settings?.include_draft_schedule_in_forecast ??
        true,
      includePublished:
        def.include_published_schedule_in_forecast ??
        settings?.include_published_schedule_in_forecast ??
        true,
    },
    categories: {
      default: {
        work_week_start_day: weekStartsOn,
        payment_day_of_week: paymentDow,
        payment_lag_days: lag,
        overtime_threshold_hours:
          def.overtime_threshold_hours ?? settings?.overtime_threshold_hours ?? 40,
      },
      w2: {
        overtime_enabled: w2.overtime_enabled !== false,
        overtime_threshold_hours: w2.overtime_threshold_hours ?? settings?.overtime_threshold_hours ?? 40,
      },
      contractor_1099: {
        overtime_enabled: c1099.overtime_enabled === true || c1099.overtime_enabled === 1,
      },
      temp: {
        overtime_enabled: temp.overtime_enabled === true || temp.overtime_enabled === 1,
      },
    },
  };
}

/**
 * Resolve date range for period chip / card.
 * @param anchorYmd — usually planner selectedDate
 * @param plannerWeek — { start, end } from roster week picker
 */
export function periodDateRange(periodId, { anchorYmd, plannerWeek, weekStartsOn = 0, calendarBundle }) {
  const anchor = anchorYmd || businessTodayYmd();
  const plannerStart = plannerWeek?.start || weekStartFromDate(anchor, weekStartsOn);
  const plannerEnd = plannerWeek?.end || weekEndFromStart(plannerStart);

  const currentPay = workWeekForDate(anchor, weekStartsOn);
  const lastPay = workWeekForDate(addDaysYmd(currentPay.start, -7), weekStartsOn);
  const nextPay = workWeekForDate(addDaysYmd(currentPay.start, 7), weekStartsOn);

  switch (periodId) {
    case "today":
      return { start: anchor, end: anchor, label: formatDateShortLabel(anchor), kind: "day" };
    case "this_week":
      return {
        start: plannerStart,
        end: plannerEnd,
        label: formatWeekRangeLabel(plannerStart, plannerEnd),
        kind: "work_week",
      };
    case "next_week": {
      const s = addDaysYmd(plannerStart, 7);
      const e = addDaysYmd(plannerEnd, 7);
      return { start: s, end: e, label: formatWeekRangeLabel(s, e), kind: "work_week" };
    }
    case "current_pay_period":
      return enrichPayPeriod(currentPay, calendarBundle);
    case "last_pay_period":
      return enrichPayPeriod(lastPay, calendarBundle);
    case "next_pay_period":
      return enrichPayPeriod(nextPay, calendarBundle);
    default:
      return enrichPayPeriod(currentPay, calendarBundle);
  }
}

function enrichPayPeriod(period, calendarBundle) {
  const def = calendarBundle?.categories?.default || {
    work_week_start_day: calendarBundle?.weekStartsOn ?? 0,
    payment_day_of_week: calendarBundle?.paymentDow ?? 5,
    payment_lag_days: calendarBundle?.paymentLagDays ?? 0,
  };
  const paymentDate = paymentDateForWeek(period.start, def);
  return {
    ...period,
    kind: "pay_period",
    payment_date: paymentDate,
    payment_day_label: paymentDayLabel(paymentDate),
  };
}

export function computePeriodMetrics({
  entries,
  workers,
  settings,
  start,
  end,
  calendarBundle,
  includeDraft = true,
  includePublished = true,
  publishedOnlyCost = false,
}) {
  const scoped = filterEntriesInRange(entries, start, end);
  const active = scoped.filter((e) => e.status !== "cancelled" && e.status !== "replaced");

  const forecast = computeFundingForecast({
    entries: active,
    workers,
    settings,
    calendarBundle: calendarBundle.categories ? calendarBundle : { categories: calendarBundle },
    weekStart: start,
    weekEnd: end,
    includeDraft,
    includePublished,
  });

  const cal = calendarBundle.categories?.default || {};
  const paymentDate = paymentDateForWeek(start, {
    work_week_start_day: calendarBundle.weekStartsOn ?? settings?.week_starts_on ?? 0,
    payment_day_of_week: calendarBundle.paymentDow ?? settings?.payment_day_of_week ?? 5,
    payment_lag_days: calendarBundle.paymentLagDays ?? 0,
  });

  const uniqueWorkers = new Set(
    active
      .filter((e) => !["sick", "absent", "no_show"].includes(e.status))
      .filter((e) => {
        if (publishedOnlyCost && e.publish_status !== "published") return false;
        if (!includeDraft && e.publish_status !== "published") return false;
        if (!includePublished && e.publish_status === "published") return false;
        return true;
      })
      .map((e) => e.worker_profile_id),
  );

  const shiftCount = active.filter((e) => {
    if (!["sick", "absent", "no_show"].includes(e.status)) {
      if (publishedOnlyCost && e.publish_status !== "published") return false;
      return true;
    }
    return false;
  }).length;

  const cat = forecast.category_breakdown || {};
  const estCost = publishedOnlyCost
    ? Number(forecast.published_cost || 0)
    : Number(forecast.total_projected_cost || 0);

  const daily = (forecast.daily_breakdown || []).map((d) => ({
    day: d.day,
    date: d.date,
    short_label: d.date ? formatDateShortLabel(d.date) : d.day,
    people_count: d.people_count,
    hours: d.hours,
    cost: d.cost,
  }));

  return {
    total_workers: uniqueWorkers.size,
    total_shifts: shiftCount,
    total_scheduled_hours: forecast.total_scheduled_hours,
    estimated_cost: estCost,
    projected_payroll_cost: Number(forecast.total_projected_cost || 0),
    published_schedule_cost: Number(forecast.published_cost || 0),
    draft_schedule_cost: Number(forecast.draft_cost || 0),
    w2_cost: Number(cat.w2?.cost ?? 0),
    contractor_1099_cost: Number(cat.contractor_1099?.cost ?? 0),
    temp_cost: Number(cat.temp?.cost ?? 0),
    overtime_risk_count: forecast.overtime_risk_count,
    projected_overtime_hours: forecast.projected_overtime_hours,
    draft_cost: forecast.draft_cost,
    published_cost: forecast.published_cost,
    payment_date: paymentDate,
    payment_day_label: paymentDayLabel(paymentDate),
    work_week_start: start,
    work_week_end: end,
    period_range_label: formatWeekRangeLabel(start, end),
    daily_breakdown: daily,
    overtime_risks: forecast.overtime_risks || [],
  };
}

function signedDelta(current, prior) {
  const d = Number(current || 0) - Number(prior || 0);
  if (d === 0) return { value: 0, label: "No change" };
  if (d > 0) return { value: d, label: `+${formatDelta(d)}` };
  return { value: d, label: `-${formatDelta(Math.abs(d))}` };
}

function formatDelta(n) {
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

/** Four-card layout: last pay period, current/upcoming, next week, comparison. */
export function buildPayrollPeriodOverview({
  entries,
  workers,
  settings,
  calendarSettings,
  anchorYmd,
  plannerWeek,
}) {
  const bundle = buildCalendarBundle(settings, calendarSettings);
  const { includeDraft, includePublished } = bundle.forecastFlags;
  const weekStartsOn = bundle.weekStartsOn;

  const rangeOpts = { anchorYmd, plannerWeek, weekStartsOn, calendarBundle: bundle };
  const lastRange = periodDateRange("last_pay_period", rangeOpts);
  const currentRange = periodDateRange("current_pay_period", rangeOpts);
  const nextWeekRange = periodDateRange("next_week", rangeOpts);

  const last = computePeriodMetrics({
    entries,
    workers,
    settings,
    start: lastRange.start,
    end: lastRange.end,
    calendarBundle: bundle,
    includeDraft: false,
    includePublished: true,
    publishedOnlyCost: true,
  });

  const current = computePeriodMetrics({
    entries,
    workers,
    settings,
    start: currentRange.start,
    end: currentRange.end,
    calendarBundle: bundle,
    includeDraft,
    includePublished,
  });

  const nextWeek = computePeriodMetrics({
    entries,
    workers,
    settings,
    start: nextWeekRange.start,
    end: nextWeekRange.end,
    calendarBundle: bundle,
    includeDraft,
    includePublished,
  });

  const costDelta = signedDelta(current.estimated_cost, last.estimated_cost);
  const hoursDelta = signedDelta(current.total_scheduled_hours, last.total_scheduled_hours);
  const workersDelta = signedDelta(current.total_workers, last.total_workers);
  const otDelta = signedDelta(current.overtime_risk_count, last.overtime_risk_count);

  return {
    bundle,
    last: {
      ...last,
      card_title: "Last payroll period cost",
      subtitle: SCHEDULE_ESTIMATE_LABEL,
      note: "From published schedule in the prior work week (parameterized calendar). Not final payroll.",
      period_label: lastRange.label,
      payment_date: paymentDateForWeek(lastRange.start, bundle.categories.default),
      payment_day_label: paymentDayLabel(
        paymentDateForWeek(lastRange.start, bundle.categories.default),
      ),
    },
    current: {
      ...current,
      card_title: "Current / upcoming payroll expected",
      subtitle: PROJECTED_PAYROLL_LABEL,
      note: "Work week for selected date. Includes draft and published per calendar settings.",
      period_label: currentRange.label,
      payment_date: current.payment_date,
      payment_day_label: current.payment_day_label,
    },
    nextWeek: {
      ...nextWeek,
      card_title: "Next week expected",
      subtitle: PROJECTED_PAYROLL_LABEL,
      note: "Planner week after the selected work week.",
      period_label: nextWeekRange.label,
    },
    comparison: {
      last_cost: last.estimated_cost,
      upcoming_cost: current.estimated_cost,
      cost_delta: costDelta,
      hours_delta: hoursDelta,
      workers_delta: workersDelta,
      ot_delta: otDelta,
      subtitle: SCHEDULE_ESTIMATE_LABEL,
    },
  };
}
