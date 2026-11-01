import React from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import WeeklyScheduleCopyShiftDialog from "./WeeklyScheduleCopyShiftDialog";

describe("Copy shift dialog", () => {
  it("shows the source shift, employee search, days, and conflict choices", () => {
    const html = renderToString(
      <WeeklyScheduleCopyShiftDialog
        open
        inline
        entry={{
          id: 4,
          user_id: 1,
          day_of_week: 1,
          start_time: "08:00",
          end_time: "16:00",
          break_minutes: 30,
          break_slots: [{ start_time: "12:00", end_time: "12:30" }],
          assignments: [
            { role: "wash", full_shift: false, start_time: "08:00", end_time: "12:00", remarks: "Early wash" },
            { role: "fold", full_shift: false, start_time: "12:00", end_time: "16:00" },
          ],
        }}
        employeeName="Ana Ruiz"
        responsibilities={[
          {
            id: 9,
            user_id: 1,
            day_of_week: 1,
            role: "lint_cleaning",
            remarks: "Front machines",
            timing_mode: "specific_time",
            start_time: "10:00",
            checklist_items: [{ task_code: "lint", task_name: "Lint traps", responsibility_label: "Ana Ruiz" }],
          },
        ]}
        employees={[
          { user_id: 2, display_name: "Ben Ortiz" },
          { user_id: 3, display_name: "Cara Diaz" },
        ]}
        onClose={() => {}}
        onPreview={async () => ({})}
        onCopy={async () => ({})}
      />,
    );
    expect(html).toContain("Copy shift");
    expect(html).toContain("Ana Ruiz");
    expect(html).toContain("Assign to");
    expect(html).toContain("Select all");
    expect(html).toContain("Clear all");
    expect(html).toContain("Skip existing shifts");
    expect(html).toContain("Replace existing shifts");
    expect(html).toContain("Early wash");
    expect(html).toContain("Lint traps");
    expect(html).toContain("Copy shifts");
  });
});
