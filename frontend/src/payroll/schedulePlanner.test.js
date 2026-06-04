/** @jest-environment node */
import {
  computeDayPlan,
  computePlanSummary,
  computeScheduledHours,
  detectCoverageGaps,
  previewHoursAfterAssignment,
  rankShiftSuggestions,
  weekStartFromDate,
  workerProfileGaps,
  applyWorkerProfileToForm,
  checkEntryProfileWarnings,
} from "./schedulePlanner.js";

const settings = {
  week_starts_on: 0,
  overtime_threshold_hours: 40,
  underused_hours_threshold: 15,
  heavy_hours_threshold: 35,
  shifts: [
    { id: 1, name: "Morning", active: true, start_time_default: "07:00:00", end_time_default: "15:00:00" },
    { id: 2, name: "Afternoon", active: true, start_time_default: "15:00:00", end_time_default: "23:00:00" },
  ],
  work_streams: [
    { id: 10, name: "Rinse", active: true },
    { id: 11, name: "Drop Off", active: true },
  ],
  roles: [
    { id: 20, name: "Operator", active: true },
    { id: 21, name: "Folder", active: true },
  ],
};

const workers = [
  {
    id: 1,
    worker_profile_id: 1,
    display_name: "Ana",
    worker_name: "Ana",
    worker_category_label: "W-2",
    default_hourly_rate: 20,
    active: true,
    role_skills: [{ role_id: 21, work_stream_id: 10, active: true }],
    performance_preview: { available: true, avg_bags_per_hour: 5 },
  },
];

describe("schedulePlanner", () => {
  test("computeScheduledHours", () => {
    expect(computeScheduledHours("07:00", "15:00", 0)).toBe(8);
  });

  test("day plan recalculates totals", () => {
    const entries = [
      {
        id: 1,
        work_date: "2026-05-21",
        shift_id: 1,
        work_stream_id: 10,
        role_id: 21,
        worker_profile_id: 1,
        start_time: "07:00:00",
        end_time: "15:00:00",
        status: "scheduled",
      },
    ];
    const targets = [
      {
        active: true,
        shift_id: 1,
        work_stream_id: 10,
        role_id: 21,
        required_count: 2,
        shift_name: "Morning",
        work_stream_name: "Rinse",
        role_name: "Folder",
      },
    ];
    const plan = computeDayPlan(entries, settings, targets, "2026-05-21", workers);
    expect(plan.total_people).toBe(1);
    expect(plan.total_scheduled_hours).toBe(8);
    expect(plan.open_coverage_gaps).toBe(1);
  });

  test("coverage gap detection", () => {
    const gaps = detectCoverageGaps([], settings, settings, "2026-05-21");
    expect(Array.isArray(gaps)).toBe(true);
  });

  test("rankShiftSuggestions prefers lower hours", () => {
    const suggestions = rankShiftSuggestions({
      workDate: "2026-05-21",
      shiftId: 1,
      workStreamId: 10,
      roleId: 21,
      startTime: "07:00",
      endTime: "15:00",
      entries: [],
      workers,
      settings,
    });
    expect(suggestions.length).toBe(1);
    expect(suggestions[0].worker_name).toBe("Ana");
  });

  test("previewHoursAfterAssignment flags overtime before save", () => {
    const weekStart = weekStartFromDate("2026-05-21", 0);
    const entries = Array.from({ length: 5 }, (_, i) => ({
      id: i + 1,
      work_date: `2026-05-${19 + i}`,
      shift_id: 1,
      worker_profile_id: 1,
      scheduled_hours: 8,
      status: "scheduled",
    }));
    const preview = previewHoursAfterAssignment(1, entries, settings, weekStart, workers[0], 8);
    expect(preview.after).toBe(48);
    expect(preview.overtime_risk).toBe(true);
    expect(preview.threshold).toBe(40);
  });

  test("workerProfileGaps lists missing profile fields", () => {
    const gaps = workerProfileGaps({ active: true, worker_category: "w2", default_hourly_rate: 0, role_skills: [], availability: [] });
    expect(gaps).toContain("Missing hourly rate");
    expect(gaps).toContain("No role skill assigned");
  });

  test("applyWorkerProfileToForm uses preferred shift and role", () => {
    const worker = {
      ...workers[0],
      preferred_shift_id: 1,
      preferred_role_id: 21,
      role_skills: [{ role_id: 21, work_stream_id: 10, active: true }],
    };
    const form = applyWorkerProfileToForm({ work_date: "2026-05-21" }, worker, settings);
    expect(String(form.shift_id)).toBe("1");
    expect(String(form.role_id)).toBe("21");
  });

  test("checkEntryProfileWarnings flags role mismatch", () => {
    const worker = { ...workers[0], role_skills: [{ role_id: 21, work_stream_id: 10, active: true }] };
    const warnings = checkEntryProfileWarnings(
      { work_date: "2026-05-21", role_id: 99, shift_id: 1, start_time: "07:00", end_time: "15:00" },
      worker,
      { ...settings, _workers: [worker] },
    );
    expect(warnings.some((w) => /role/i.test(w))).toBe(true);
  });
});
