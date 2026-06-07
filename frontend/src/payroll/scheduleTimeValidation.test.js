import { describe, expect, it } from "vitest";
import { validateScheduleTimes } from "./scheduleTimeValidation";

describe("validateScheduleTimes", () => {
  it("requires start and end", () => {
    const { errors } = validateScheduleTimes({ startTime: "", endTime: "15:00" });
    expect(errors).toContain("Start time is required");
  });

  it("rejects end before start without overnight", () => {
    const { errors } = validateScheduleTimes({ startTime: "15:00", endTime: "07:00" });
    expect(errors.some((e) => e.includes("after start time"))).toBe(true);
  });

  it("detects overlap", () => {
    const { errors } = validateScheduleTimes({
      startTime: "07:00",
      endTime: "15:00",
      workDate: "2026-06-10",
      workerProfileId: 1,
      draftEntries: [
        {
          id: 2,
          worker_profile_id: 1,
          work_date: "2026-06-10",
          start_time: "10:00",
          end_time: "14:00",
          status: "scheduled",
        },
      ],
    });
    expect(errors).toContain("This overlaps another shift for the same worker");
  });
});
