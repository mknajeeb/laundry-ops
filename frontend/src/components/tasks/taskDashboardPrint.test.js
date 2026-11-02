import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildTaskDashboardPrintDocument, deliverTaskDashboardPrint, printTaskDashboard } from "./taskDashboardPrint";

const SAMPLE = {
  rangeStart: "2026-11-01",
  rangeEnd: "2026-11-01",
  categoryLabel: "All",
  groupBy: "daily",
  hideLabor: false,
  rows: [
    {
      role_label: "Floor & Washer",
      assigned_employees: ["Gabriela", "Yesenia"],
      timing_label: "Anytime",
      business_date: "2026-11-01",
      completion_status: "completed",
      verification_status: "waiting",
      overall_status: "pending_verification",
      shared: true,
      instructions: "Check washers, then broom the floor.",
      employees_finished: 2,
      employees_assigned: 2,
      checklist_done: 2,
      checklist_required: 2,
      shared_checklist_items: [
        {
          task_name: "Check Washer Residue",
          responsibility_label: "Anyone on Team",
          status: "completed",
          completed_by_name: "Gabriela",
          completed_at: "2026-11-01 09:24:00",
          input_schema: [{ id: "residue", type: "text", label: "Residue" }],
          completion_input: { values: { residue: "light" }, remarks: "Residue was light." },
        },
        {
          task_name: "Floor Brooming",
          section_label: "Facility",
          section_order: 20,
          status: "pending_verification",
          completed_by_name: "Yesenia",
          completed_at: "2026-11-01 09:40:00",
        },
      ],
      contributions: [
        {
          employee_name: "Gabriela",
          participation_status: "finished",
          activity: {
            started_at: "2026-11-01 09:10:00",
            ended_at: "2026-11-01 09:45:00",
            duration_seconds: 2100,
            employee_remark: { text: "Done for the morning." },
          },
        },
        {
          employee_name: "Yesenia",
          participation_status: "finished",
          activity: {
            started_at: "2026-11-01 09:12:00",
            ended_at: "2026-11-01 09:50:00",
            duration_seconds: 2280,
            supervisor_remark: { text: "Verified the floor." },
          },
        },
      ],
    },
  ],
};

describe("task dashboard print document", () => {
  it("prints the selected date, people, status, and checklist on letter", () => {
    const html = buildTaskDashboardPrintDocument(SAMPLE);
    expect(html).toContain("@page { size: letter portrait;");
    expect(html).toContain("VeeWash Task Dashboard");
    expect(html).toContain("Nov 1, 2026 ET");
    expect(html).toContain("Floor &amp; Washer");
    expect(html).toContain("Gabriela, Yesenia");
    expect(html).toContain("Completion: Completed");
    expect(html).toContain("Verification: Pending Verification");
    expect(html).toContain("Overall: Pending Verification");
    expect(html).toContain("Check Washer Residue");
    expect(html).toContain("Floor Brooming");
    expect(html).toContain("Facility");
    expect(html).toContain("Residue: light");
    expect(html).toContain("Notes: Residue was light.");
    expect(html).toContain("Checked off");
    expect(html).toContain("Waiting for Verification");
    expect(html).toContain("9:24 AM");
    expect(html).toContain("Finished");
    expect(html).toContain("Employee remark: Done for the morning.");
    expect(html).toContain("Supervisor remark: Verified the floor.");
    expect(html).toContain("Activities assigned");
    expect(html).not.toContain("window.print");
    expect(html).not.toContain("<button");
    expect(html).not.toContain("Manage tasks");
    expect(html).not.toContain("ManagementHubNav");
  });

  it("still prints a report header when the selected range has no assignments", () => {
    const html = buildTaskDashboardPrintDocument({
      rangeStart: "2026-11-01",
      rangeEnd: "2026-11-07",
      categoryLabel: "End of Day",
      groupBy: "weekly",
      rows: [],
    });
    expect(html).toContain("Nov 1, 2026 – Nov 7, 2026 ET");
    expect(html).toContain("End of Day");
    expect(html).toContain("Weekly");
    expect(html).toContain("No assignments in this range.");
    expect(html.length).toBeGreaterThan(500);
  });

  it("omits labor duration when the dashboard hides labor", () => {
    const shown = buildTaskDashboardPrintDocument(SAMPLE);
    const hidden = buildTaskDashboardPrintDocument({ ...SAMPLE, hideLabor: true });
    expect(shown).toContain("Total time");
    expect(shown).toContain("35m");
    expect(hidden).not.toContain("Total time");
    expect(hidden).not.toContain("35m");
  });

  it("writes the report into a child document and does not print the app window", () => {
    let parentPrinted = false;
    const written = [];
    let childPrinted = false;
    const fakeWindow = {
      document: {
        readyState: "complete",
        open() {},
        write(html) {
          written.push(html);
        },
        close() {},
      },
      focus() {},
      print() {
        childPrinted = true;
      },
      onload: null,
    };
    const result = printTaskDashboard(SAMPLE, {
      openWindow: () => fakeWindow,
      scheduleChildPrint: (win) => win.print(),
      parentPrint: () => {
        parentPrinted = true;
      },
    });
    expect(result).toBe("window");
    expect(written[0]).toContain("VeeWash Task Dashboard");
    expect(written[0]).toContain("Gabriela");
    expect(childPrinted).toBe(true);
    expect(parentPrinted).toBe(false);
  });

  it("uses a hidden frame when a popup is blocked, still not the app window", () => {
    let framed = "";
    const result = deliverTaskDashboardPrint("<html><body>VeeWash Task Dashboard</body></html>", {
      openWindow: () => null,
      printFrame: (html) => {
        framed = html;
      },
    });
    expect(result).toBe("frame");
    expect(framed).toContain("VeeWash Task Dashboard");
  });

  it("keeps the dashboard button on the isolated print path", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const page = readFileSync(resolve(here, "../../pages/ManagementTasksPage.jsx"), "utf8");
    const printer = readFileSync(resolve(here, "./taskDashboardPrint.js"), "utf8");
    expect(page).toContain("printTaskDashboard");
    expect(page).not.toContain("window.print");
    expect(printer).not.toContain("window.print");
    expect(printer).toContain("letter portrait");
    expect(printer).toContain("printHtmlInHiddenFrame");
  });
});
