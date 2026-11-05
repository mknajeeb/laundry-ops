import assert from "node:assert/strict";
import test from "node:test";
import {
  formatBurdenPercent,
  formatHourlyCost,
  formatOtImpact,
  formatOtImpactPercent,
  burdenEstimateNote,
  hourlyCostTooltipLines,
  targetComparisonText,
} from "./hourlyCostDisplay.js";

test("formats money, burden, and positive overtime impact", () => {
  assert.equal(formatHourlyCost(21.11), "$21.11");
  assert.equal(formatHourlyCost(null), "—");
  assert.equal(formatBurdenPercent(11.674), "11.67%");
  assert.equal(formatOtImpact(2.13), "+$2.13");
  assert.equal(formatOtImpact(0), "$0.00");
  assert.equal(formatOtImpact(-0.5), "-$0.50");
  assert.equal(formatOtImpactPercent(11.22), "+11.2%");
});

test("target comparison and tooltip name the source periods", () => {
  const analysis = {
    gross_pay: 974.02,
    total_employer_cost: 1087.7,
    employer_expenses: 113.68,
    burden_percent: 11.67,
    burden_label: "Estimated",
    burden_status: "estimated",
    burden_sources: [
      { pay_period_start: "2026-10-19", pay_period_end: "2026-10-25", burden_percent: 11.67 },
    ],
    payable_hours: 51.53,
    ot_premium: 98.01,
    formula: "Estimated total employer cost = gross earnings × (1 + historical burden).",
    labor_cost_target: 19,
    target_delta_per_hour: 2.11,
    target_status: "above",
    effective_cost_per_hour: 21.11,
  };
  assert.match(targetComparisonText(analysis), /Above target \+\$2\.11\/hr/);
  const lines = hourlyCostTooltipLines(analysis);
  assert.ok(lines.some((line) => line.includes("11.67%")));
  assert.ok(lines.some((line) => line.includes("2026-10-19")));
  assert.ok(lines.some((line) => line.includes("Estimated")));
  assert.ok(lines.some((line) => line.includes("Payable hours")));
});

test("configured burden is not described as a historical estimate", () => {
  const note = burdenEstimateNote({
    burden_status: "configured",
    method: "configured_burden",
  });
  assert.match(note, /Configured employer burden/);
  assert.equal(/prior finalized payroll/.test(note), false);
  const historical = burdenEstimateNote({ burden_status: "estimated", method: "historical_burden" });
  assert.match(historical, /prior finalized payroll/);
});

test("below-target copy stays compact", () => {
  const text = targetComparisonText({
    target_status: "at_or_below",
    target_delta_per_hour: -1,
    labor_cost_target: 19,
    effective_cost_per_hour: 18,
  });
  assert.match(text, /Below target -\$1\.00\/hr/);
});
