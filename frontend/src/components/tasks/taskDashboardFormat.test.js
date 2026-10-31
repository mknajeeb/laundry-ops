import { describe, expect, it } from "vitest";
import {
  formatDashboardDate,
  formatDashboardTime,
  formatDashboardDateTime,
  participationTimeLine,
} from "./taskDashboardFormat";

describe("taskDashboardFormat", () => {
  it("formats dates like Oct 30, 2026", () => {
    expect(formatDashboardDate("2026-10-30")).toBe("Oct 30, 2026");
  });

  it("formats times like 9:32 AM", () => {
    expect(formatDashboardTime("2026-10-30 09:32:06")).toBe("9:32 AM");
    expect(formatDashboardTime("2026-10-30 13:05:00")).toBe("1:05 PM");
  });

  it("combines date and time", () => {
    expect(formatDashboardDateTime("2026-10-30 09:32:06")).toBe(
      "Oct 30, 2026 · 9:32 AM"
    );
  });

  it("shows each employee's own start and finish", () => {
    expect(
      participationTimeLine({
        participation_status: "finished",
        activity: { started_at: "2026-10-30 09:00:00", ended_at: "2026-10-30 09:35:00" },
      })
    ).toBe("Started 9:00 AM, Finished 9:35 AM");
    expect(participationTimeLine({ participation_status: "not_started" })).toBe("Not Started");
    expect(
      participationTimeLine({
        participation_status: "in_progress",
        activity: { started_at: "2026-10-30 09:00:00" },
      })
    ).toBe("Started 9:00 AM");
  });
});
