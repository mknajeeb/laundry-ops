import assert from "node:assert/strict";
import test from "node:test";
import { formatComparisonChange, laborCostCsv } from "./laborCostExport.js";

test("percentage-point changes are not labeled as a relative percent", () => {
  assert.equal(
    formatComparisonChange({
      change_kind: "percentage_points",
      difference: 2.5,
      percent_change: null,
    }),
    "+2.50 percentage points",
  );
  assert.equal(
    formatComparisonChange({ change_kind: "percent", difference: 10, percent_change: null }),
    "N/A",
  );
});

test("csv quotes employee names that contain commas", () => {
  const csv = laborCostCsv([
    {
      employee_name: "Shah, Varun",
      classification_label: "W-2",
      payable_hours: 49.41,
      ot_premium: 79.99,
      total_employer_cost: 1027.36,
    },
  ]);
  assert.match(csv.split("\n")[0], /Employee,Classification/);
  assert.match(csv, /"Shah, Varun"/);
  assert.match(csv, /OT Premium \(\$\)/);
});
