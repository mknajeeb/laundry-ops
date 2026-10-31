import { describe, expect, it } from "vitest";
import {
  formatDashboardDate,
  formatDashboardTime,
  formatDashboardDateTime,
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
});
