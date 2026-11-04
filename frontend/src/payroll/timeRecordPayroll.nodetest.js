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
