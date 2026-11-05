import assert from "node:assert/strict";
import test from "node:test";
import { combineHourlyAnalyses, enrichTimeRecords } from "./timeRecordPayroll.js";

test("a category change does not restart weekly overtime", () => {
  const rows = [
    { id: 1, user_id: 7, approved_hours: 30, clock_in_at: "2026-11-02 08:00:00", worker_category: "temp" },
    { id: 2, user_id: 7, approved_hours: 20, clock_in_at: "2026-11-03 08:00:00", worker_category: "w2" },
  ];
  const rateMap = { 7: { regular_rate: 20, ot_rate: 30, ot_enabled: true, ot_threshold: 40 } };
  const enriched = enrichTimeRecords(rows, rateMap);
  const byId = Object.fromEntries(enriched.rows.map((row) => [row.id, row]));
  assert.equal(byId[2].ot_premium, 100);
  assert.equal(enriched.totalCost, 1100);
});

test("a disabled overtime week stays regular across classifications", () => {
  const rows = [
    {
      id: 1,
      user_id: 7,
      approved_hours: 30,
      clock_in_at: "2026-11-02 08:00:00",
      worker_category: "w2",
      payroll_week_start: "2026-11-02",
      ot_week_mode: "disable_ot",
    },
    {
      id: 2,
      user_id: 7,
      approved_hours: 20,
      clock_in_at: "2026-11-03 08:00:00",
      worker_category: "temp",
      payroll_week_start: "2026-11-02",
      ot_week_mode: "disable_ot",
    },
  ];
  const rateMap = { 7: { regular_rate: 20, ot_rate: 30, ot_threshold: 40 } };
  const enriched = enrichTimeRecords(rows, rateMap);
  const byId = Object.fromEntries(enriched.rows.map((row) => [row.id, row]));
  assert.equal(byId[1].ot_premium, 0);
  assert.equal(byId[2].ot_premium, 0);
  assert.equal(byId[1].ot_week_disabled, true);
  assert.equal(enriched.totalOtCost, 0);
  assert.equal(enriched.totalCost, 1000);
});

test("an enabled week keeps overtime and the next disabled week does not", () => {
  const rows = [
    {
      id: 1,
      user_id: 7,
      approved_hours: 45,
      clock_in_at: "2026-11-02 08:00:00",
      worker_category: "w2",
      payroll_week_start: "2026-11-02",
      ot_week_mode: "default",
    },
    {
      id: 2,
      user_id: 7,
      approved_hours: 45,
      clock_in_at: "2026-11-09 08:00:00",
      worker_category: "temp",
      payroll_week_start: "2026-11-09",
      ot_week_mode: "disable_ot",
    },
  ];
  const rateMap = { 7: { regular_rate: 20, ot_rate: 30, ot_threshold: 40 } };
  const enriched = enrichTimeRecords(rows, rateMap);
  const byId = Object.fromEntries(enriched.rows.map((row) => [row.id, row]));
  assert.equal(byId[1].ot_premium, 50);
  assert.equal(byId[2].ot_premium, 0);
  assert.equal(byId[2].regular_cost, 900);
  assert.equal(enriched.totalOtCost, 50);
});

test("Jasanpreet's disabled week stays straight time at both rates", () => {
  const sessions = [
    [2006, "2026-10-26", 8.77, 21],
    [2007, "2026-10-27", 12.14, 17],
    [2057, "2026-10-28", 9.99, 21],
    [2077, "2026-10-29", 8.42, 17],
    [2081, "2026-10-30", 11.71, 17],
    [2111, "2026-10-31", 6.38, 21],
  ];
  const rows = sessions.map(([id, day, hours, rate]) => ({
    id,
    user_id: 28,
    approved_hours: hours,
    clock_in_at: `${day} 08:00:00`,
    worker_category: "temp",
    payroll_week_start: "2026-10-26",
    ot_week_mode: "disable_ot",
    resolved_hourly_rate: rate,
  }));
  const enriched = enrichTimeRecords(rows, { 28: { regular_rate: 17, ot_rate: 25.5, ot_threshold: 40 } });
  assert.equal(enriched.totalOtCost, 0);
  assert.equal(enriched.totalCost, enriched.totalRegularCost);
  assert.ok(enriched.rows.every((row) => row.ot_premium === 0 && row.ot_week_disabled === true));
});

test("combined analyses add dollars and hours before dividing", () => {
  const combined = combineHourlyAnalyses([
    {
      payable_hours: 30,
      regular_hours: 30,
      ot_hours: 0,
      gross_pay: 600,
      ot_premium: 0,
      employer_expenses: 0,
      total_employer_cost: 600,
      straight_time_employer_cost: 600,
      base_wage: 20,
      burden_status: "not_applicable",
      record_costs: [{ id: 1, total_employer_cost: 600 }],
    },
    {
      payable_hours: 20,
      regular_hours: 10,
      ot_hours: 10,
      gross_pay: 500,
      ot_premium: 100,
      employer_expenses: 50,
      total_employer_cost: 550,
      straight_time_employer_cost: 440,
      base_wage: 20,
      burden_status: "configured",
      record_costs: [{ id: 2, total_employer_cost: 550 }],
    },
  ]);
  assert.equal(combined.payable_hours, 50);
  assert.equal(combined.ot_hours, 10);
  assert.equal(combined.total_employer_cost, 1150);
  assert.equal(combined.effective_cost_per_hour, 23);
  assert.equal(combined.base_cost_per_hour, 20.8);
  assert.equal(combined.ot_impact_per_hour, 2.2);
  assert.equal(combined.burden_percent, 4.55);
  assert.equal(combined.burden_status, "configured");
  assert.equal(combined.target_delta_per_hour, 4);
  assert.equal(combined.record_costs.length, 2);
});
