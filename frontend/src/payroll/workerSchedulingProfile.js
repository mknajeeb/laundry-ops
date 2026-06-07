/** Shared scheduling profile completeness + readiness (mirrors backend/payroll_schedule.py). */

export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export const SKILL_LEVELS = [
  { value: 1, label: "Beginner" },
  { value: 2, label: "Trained" },
  { value: 3, label: "Strong" },
  { value: 4, label: "Lead" },
  { value: 5, label: "Expert" },
];

export function workerProfileGaps(worker) {
  if (!worker) return [];
  const gaps = [];
  if (worker.active === false) gaps.push("Worker inactive");
  if (!worker.worker_category) gaps.push("Payroll category missing");
  if (!Number(worker.default_hourly_rate)) gaps.push("Missing hourly rate");
  const skills = (worker.role_skills || []).filter((s) => s.active !== false);
  if (!skills.length) gaps.push("No role skill assigned");
  const hasStreamSkill = skills.some((s) => s.work_stream_id);
  const streamOk =
    hasStreamSkill || worker.can_work_rinse || worker.can_work_drop_off || worker.can_work_both;
  if (!streamOk) gaps.push("No work stream skill assigned");
  const avail = worker.availability || [];
  if (!avail.length || !avail.some((a) => !a.unavailable_flag)) gaps.push("No availability set");
  if (!worker.preferred_shift_id) gaps.push("No preferred shift");
  return gaps;
}

const COMPLETENESS_CHECKS = [
  { key: "active", label: "Worker inactive", test: (w) => w.active !== false },
  { key: "category", label: "Payroll category missing", test: (w) => !!w.worker_category },
  { key: "rate", label: "Missing hourly rate", test: (w) => Number(w.default_hourly_rate) > 0 },
  {
    key: "role_skill",
    label: "No role skill assigned",
    test: (w) => (w.role_skills || []).some((s) => s.active !== false),
  },
  {
    key: "stream_skill",
    label: "No work stream skill assigned",
    test: (w) => {
      const skills = (w.role_skills || []).filter((s) => s.active !== false);
      return (
        skills.some((s) => s.work_stream_id) ||
        w.can_work_rinse ||
        w.can_work_drop_off ||
        w.can_work_both
      );
    },
  },
  {
    key: "availability",
    label: "No availability set",
    test: (w) => (w.availability || []).some((a) => !a.unavailable_flag),
  },
  { key: "preferred_shift", label: "No preferred shift", test: (w) => !!w.preferred_shift_id },
  {
    key: "performance",
    label: "No performance mapping",
    test: (w) => !!(w.performance_preview || {}).available,
  },
];

export function profileCompleteness(worker) {
  const missing = [];
  let passed = 0;
  for (const chk of COMPLETENESS_CHECKS) {
    if (chk.test(worker || {})) passed += 1;
    else missing.push(chk.label);
  }
  const total = COMPLETENESS_CHECKS.length;
  return { score: total ? Math.round((100 * passed) / total) : 0, missing, passed, total };
}

export function schedulingReadinessBadge(worker) {
  const gaps = worker?.profile_gaps || workerProfileGaps(worker || {});
  if (worker?.active === false) {
    return { label: "Inactive", color: "default", ready: false, gaps };
  }
  const gapSet = new Set(gaps);
  if (gapSet.has("Missing hourly rate")) {
    return { label: "Missing Rate", color: "error", ready: false, gaps };
  }
  if (gapSet.has("No availability set")) {
    return { label: "Missing Availability", color: "warning", ready: false, gaps };
  }
  if (gapSet.has("No role skill assigned")) {
    return { label: "Missing Role", color: "warning", ready: false, gaps };
  }
  if (gapSet.has("No work stream skill assigned")) {
    return { label: "Missing Stream", color: "warning", ready: false, gaps };
  }
  const blocking = gaps.filter(
    (g) =>
      !["No preferred shift", "Payroll category missing"].includes(g),
  );
  if (blocking.length) {
    return { label: "Needs Review", color: "info", ready: false, gaps };
  }
  if (gaps.length) {
    return { label: "Needs Review", color: "info", ready: false, gaps };
  }
  return { label: "Ready for Scheduling", color: "success", ready: true, gaps: [] };
}

export function emptyAvailabilityWeek() {
  return DAY_NAMES.map((_, dow) => ({
    day_of_week: dow,
    unavailable_flag: dow >= 5,
    available_from: dow < 5 ? "07:00" : "",
    available_to: dow < 5 ? "15:00" : "",
    preferred_shift_id: "",
    notes: "",
  }));
}

export function entryProfileStaleWarning(entry, worker) {
  if (!entry || !worker || entry.publish_status === "published") return null;
  const stale = [];
  const rate = Number(worker.default_hourly_rate || 0);
  if (entry.hourly_rate_snapshot != null && rate && Number(entry.hourly_rate_snapshot) !== rate) {
    stale.push("Hourly rate changed in profile since this draft was created");
  }
  if (
    entry.worker_category_snapshot &&
    worker.worker_category &&
    entry.worker_category_snapshot !== worker.worker_category
  ) {
    stale.push("Worker category changed in profile");
  }
  return stale.length ? stale : null;
}
