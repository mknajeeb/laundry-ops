import { describe, expect, it } from "vitest";
import { addDaysYmd } from "../utils/businessTime";
import {
  buildCalendarBundle,
  buildPayrollPeriodOverview,
  periodDateRange,
  workWeekForDate,
} from "./schedulePeriodSummary";
import { paymentDateForWeek } from "./fundingForecast";

describe("schedulePeriodSummary", () => {
  it("resolves work week from calendar settings (not hard-coded Mon–Sun)", () => {
    const week = workWeekForDate("2026-05-21", 6);
    expect(week.start).toBe("2026-05-17");
    expect(week.end).toBe("2026-05-23");
  });

  it("maps payment day from calendar bundle", () => {
    const bundle = buildCalendarBundle(
      { week_starts_on: 0, payment_day_of_week: 5 },
      {
        categories: {
          default: {
            work_week_start_day: 0,
            payment_day_of_week: 5,
            payment_lag_days: 1,
          },
        },
      },
    );
    const pay = paymentDateForWeek("2026-05-19", bundle.categories.default);
    expect(pay).toBe("2026-05-25");
  });

  it("resolves last and current pay periods from anchor date", () => {
    const bundle = buildCalendarBundle({ week_starts_on: 0 }, null);
    const currentWeek = workWeekForDate("2026-05-21", bundle.weekStartsOn);
    const last = periodDateRange("last_pay_period", {
      anchorYmd: "2026-05-21",
      plannerWeek: { start: "2026-05-19", end: "2026-05-25" },
      weekStartsOn: bundle.weekStartsOn,
      calendarBundle: bundle,
    });
    const current = periodDateRange("current_pay_period", {
      anchorYmd: "2026-05-21",
      plannerWeek: { start: "2026-05-19", end: "2026-05-25" },
      weekStartsOn: bundle.weekStartsOn,
      calendarBundle: bundle,
    });
    expect(last.start).toBe(workWeekForDate(addDaysYmd(currentWeek.start, -7), bundle.weekStartsOn).start);
    expect(current.start).toBe(currentWeek.start);
    expect(current.end).toBe(currentWeek.end);
    expect(last.payment_date).toBeTruthy();
  });

  it("builds comparison from schedule entries", () => {
    const workers = [{ id: 1, worker_category: "w2", default_hourly_rate: 20 }];
    const mk = (date, hours, pub) => ({
      id: `${date}-${pub}`,
      work_date: date,
      worker_profile_id: 1,
      worker_name: "A",
      status: "scheduled",
      publish_status: pub,
      scheduled_hours: hours,
      shift_name: "Day",
    });
    const entries = [
      ...["2026-05-12", "2026-05-13"].map((d) => mk(d, 8, "published")),
      ...["2026-05-19", "2026-05-20"].map((d) => mk(d, 8, "draft")),
    ];
    const overview = buildPayrollPeriodOverview({
      entries,
      workers,
      settings: { week_starts_on: 0, overtime_threshold_hours: 40 },
      anchorYmd: "2026-05-20",
      plannerWeek: { start: "2026-05-19", end: "2026-05-25" },
    });
    expect(overview.last.estimated_cost).toBeGreaterThan(0);
    expect(overview.current.estimated_cost).toBeGreaterThan(0);
    expect(overview.comparison.cost_delta.value).not.toBeNaN();
  });
});
