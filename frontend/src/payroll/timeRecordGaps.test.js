import { describe, expect, it } from "vitest";
import { formatOnClockUnassignedNote, onClockUnassignedSeconds } from "./timeRecordGaps";

describe("onClockUnassignedSeconds", () => {
  it("counts Gabriela's Nov 1 role gap and not her break", () => {
    const record = {
      clock_in_at: "2026-11-01T05:10:10-05:00",
      clock_out_at: "2026-11-01T14:20:00-05:00",
      role_segments: [
        { started_at: "2026-11-01T05:10:10-05:00", ended_at: "2026-11-01T09:00:11-05:00" },
        { started_at: "2026-11-01T09:25:46-05:00", ended_at: "2026-11-01T10:42:08-05:00" },
        { started_at: "2026-11-01T11:12:23-05:00", ended_at: "2026-11-01T14:20:00-05:00" },
      ],
      breaks: [
        {
          status: "completed",
          break_start_at: "2026-11-01T10:42:08-05:00",
          break_end_at: "2026-11-01T11:12:23-05:00",
        },
      ],
    };
    expect(onClockUnassignedSeconds(record)).toBe(25 * 60 + 35);
    expect(formatOnClockUnassignedNote(record)).toBe("Includes 26 min on the clock with no role");
  });

  it("counts the Oct 31 task gap inside the second session", () => {
    const record = {
      clock_in_at: "2026-10-31T06:45:47-04:00",
      clock_out_at: "2026-10-31T15:20:13-04:00",
      role_segments: [
        { started_at: "2026-10-31T06:45:47-04:00", ended_at: "2026-10-31T09:02:52-04:00" },
        { started_at: "2026-10-31T09:17:47-04:00", ended_at: "2026-10-31T09:18:10-04:00" },
        { started_at: "2026-10-31T09:18:10-04:00", ended_at: "2026-10-31T10:47:01-04:00" },
        { started_at: "2026-10-31T11:17:02-04:00", ended_at: "2026-10-31T15:20:13-04:00" },
      ],
      breaks: [
        {
          status: "completed",
          break_start_at: "2026-10-31T10:47:01-04:00",
          break_end_at: "2026-10-31T11:17:02-04:00",
        },
      ],
    };
    expect(onClockUnassignedSeconds(record)).toBe(14 * 60 + 55);
  });

  it("does not flag a shift that has no role segments", () => {
    expect(
      onClockUnassignedSeconds({
        clock_in_at: "2026-11-01T05:00:00-05:00",
        clock_out_at: "2026-11-01T13:00:00-05:00",
        role_segments: [],
      }),
    ).toBe(0);
  });

  it("covers an overnight shift whose segments meet the clocks", () => {
    expect(
      onClockUnassignedSeconds({
        clock_in_at: "2026-10-27T22:00:00-04:00",
        clock_out_at: "2026-10-28T06:00:00-04:00",
        role_segments: [
          { started_at: "2026-10-27T22:00:00-04:00", ended_at: "2026-10-28T06:00:00-04:00" },
        ],
        breaks: [],
      }),
    ).toBe(0);
  });
});
