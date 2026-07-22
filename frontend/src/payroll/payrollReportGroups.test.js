import { describe, expect, test } from "vitest";
import { distinctPayDates, groupMonthlyPaidRows } from "./payrollReportGroups";

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
  ];

  test("groups full June month into one section per pay date / period", () => {
    const groups = groupMonthlyPaidRows(rows);
    expect(groups).toHaveLength(3);
    expect(groups.map((g) => g.payDate)).toEqual([
      "2026-06-06",
      "2026-06-13",
      "2026-06-27",
    ]);
    expect(groups[0].rows.map((r) => r.employee_name).sort()).toEqual(["A", "C"]);
    expect(groups[0].heading).toContain("Pay Date: 2026-06-06");
    expect(groups[0].heading).toContain("2026-05-25 – 2026-05-31");
  });

  test("distinctPayDates lists every Official Pay Date in the month", () => {
    expect(distinctPayDates(rows)).toEqual([
      "2026-06-06",
      "2026-06-13",
      "2026-06-27",
    ]);
  });
});
