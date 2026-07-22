import { describe, expect, test } from "vitest";
import {
  distinctPayDates,
  distinctPayrollPeriods,
  groupMonthlyPaidRows,
} from "./payrollReportGroups";

describe("groupMonthlyPaidRows", () => {
  const rows = [
    {
      employee_name: "A",
      pay_date: "2026-06-06",
      payroll_period: "2026-05-25 – 2026-05-31",
    },
    {
      employee_name: "B",
      pay_date: "2026-06-13",
      payroll_period: "2026-06-01 – 2026-06-07",
    },
    {
      employee_name: "C",
      pay_date: "2026-06-06",
      payroll_period: "2026-05-25 – 2026-05-31",
    },
    {
      employee_name: "D",
      pay_date: "2026-06-27",
      payroll_period: "2026-06-15 – 2026-06-21",
    },
    {
      employee_name: "E",
      pay_date: "2026-06-20",
      payroll_period: "2026-06-08 – 2026-06-14",
    },
  ];

  test("groups by Payroll Period then Pay Date", () => {
    const groups = groupMonthlyPaidRows(rows);
    expect(groups.map((g) => g.period)).toEqual([
      "2026-05-25 – 2026-05-31",
      "2026-06-01 – 2026-06-07",
      "2026-06-08 – 2026-06-14",
      "2026-06-15 – 2026-06-21",
    ]);
    expect(groups[0].heading).toContain("Payroll Period:");
    expect(groups[0].payDates).toHaveLength(1);
    expect(groups[0].payDates[0].payDate).toBe("2026-06-06");
    expect(groups[0].payDates[0].rows.map((r) => r.employee_name).sort()).toEqual(["A", "C"]);
  });

  test("distinctPayDates lists every Official Pay Date in the month", () => {
    expect(distinctPayDates(rows)).toEqual([
      "2026-06-06",
      "2026-06-13",
      "2026-06-20",
      "2026-06-27",
    ]);
  });

  test("distinctPayrollPeriods lists periods chronologically", () => {
    expect(distinctPayrollPeriods(rows)).toEqual([
      "2026-05-25 – 2026-05-31",
      "2026-06-01 – 2026-06-07",
      "2026-06-08 – 2026-06-14",
      "2026-06-15 – 2026-06-21",
    ]);
  });
});
