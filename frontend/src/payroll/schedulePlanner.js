/**
 * Client-side schedule planner — real-time summary, gaps, suggestions, worker balance.
 * Mirrors backend/payroll_schedule_planner.py for instant UI updates before save.
 */

import { entryProfileStaleWarning } from "./workerSchedulingProfile";
import {
  addDaysYmd,
  weekStartFromDate,
  weekEndFromStart,
  businessTodayYmd,
  dayOfWeekMon0,
} from "../utils/businessTime";

export { addDaysYmd, weekStartFromDate, weekEndFromStart, businessTodayYmd, dayOfWeekMon0 };

export function parseTimeToMinutes(t) {
  if (!t) return null;
  const s = String(t).slice(0, 5);
  const [h, m] = s.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

export function computeScheduledHours(startTime, endTime, breakMinutes = 0) {
  const st = parseTimeToMinutes(startTime);
  const et = parseTimeToMinutes(endTime);
  if (st == null || et == null) return 0;
  let mins = et - st;
  if (mins <= 0) mins += 24 * 60;
  return Math.max(0, (mins - Number(breakMinutes || 0)) / 60);
}

export function enrichEntry(entry, settings) {
  const shift = (settings?.shifts || []).find((s) => String(s.id) === String(entry.shift_id));
  const stream = (settings?.work_streams || []).find((s) => String(s.id) === String(entry.work_stream_id));
  const role = (settings?.roles || []).find((r) => String(r.id) === String(entry.role_id));
  const worker = (settings?._workers || []).find(
    (w) => String(w.worker_profile_id || w.id) === String(entry.worker_profile_id),
  );
  const hours =
    entry.scheduled_hours != null
      ? Number(entry.scheduled_hours)
      : computeScheduledHours(entry.start_time, entry.end_time, entry.break_minutes);
  const rate = Number(entry.hourly_rate_snapshot || worker?.default_hourly_rate || 0);
  const enriched = {
    ...entry,
    shift_name: entry.shift_name || entry.shift_snapshot || shift?.name,
    work_stream_name: entry.work_stream_name || entry.work_stream_snapshot || stream?.name,
    role_name: entry.role_name || entry.role_snapshot || role?.name,
    worker_name: entry.worker_name || worker?.worker_name || worker?.display_name,
    worker_category: entry.worker_category || entry.worker_category_snapshot || worker?.worker_category,
    worker_category_label:
      entry.worker_category_label ||
      worker?.worker_category_label ||
      formatCategoryLabel(entry.worker_category_snapshot || worker?.worker_category),
    user_id: entry.user_id || worker?.user_id,
    scheduled_hours: hours,
    estimated_cost: entry.estimated_cost != null ? Number(entry.estimated_cost) : rate > 0 ? hours * rate : 0,
    hourly_rate_snapshot: rate || null,
    performance_preview: entry.performance_preview || worker?.performance_preview,
  };
  if (worker && settings?._workers?.length) {
    enriched.warnings = checkEntryProfileWarnings(enriched, worker, settings);
    enriched.profile_gaps = worker.profile_gaps || workerProfileGaps(worker);
    const stale = entryProfileStaleWarning(enriched, worker);
    if (stale?.length) {
      enriched.warnings = [...(enriched.warnings || []), ...stale];
    }
  }
  return enriched;
}

export function formatCategoryLabel(cat) {
  const m = { w2: "W-2", contractor_1099: "1099", temp: "Temp" };
  return m[String(cat || "").toLowerCase()] || cat || "";
}

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
  if (!(worker.availability || []).length) gaps.push("No availability set");
  return gaps;
}

export function eligibleRolesForWorker(worker, settings) {
  const roles = (settings?.roles || []).filter((r) => r.active);
  const skills = (worker?.role_skills || []).filter((s) => s.active !== false);
  if (!skills.length) return roles;
  const ids = new Set(skills.map((s) => String(s.role_id)));
  return roles.filter((r) => ids.has(String(r.id)));
}

export function eligibleStreamsForWorker(worker, settings, roleId) {
  const streams = (settings?.work_streams || []).filter((s) => s.active);
  const skills = (worker?.role_skills || []).filter((s) => s.active !== false);
  if (!skills.length) {
    return streams.filter((s) => {
      const n = String(s.name || "").toLowerCase();
      if (n.includes("rinse") && worker?.can_work_rinse === false) return false;
      if (n.includes("drop") && worker?.can_work_drop_off === false) return false;
      return true;
    });
  }
  const streamIds = new Set(
    skills
      .filter((s) => !roleId || String(s.role_id) === String(roleId))
      .map((s) => s.work_stream_id)
      .filter(Boolean)
      .map(String),
  );
  if (!streamIds.size) return streams;
  return streams.filter((s) => streamIds.has(String(s.id)));
}

export function checkEntryProfileWarnings(entry, worker, settings) {
  if (!worker) return [];
  const warnings = [];
  for (const gap of worker.profile_gaps || workerProfileGaps(worker)) {
    warnings.push(gap);
  }
  const workDate = String(entry.work_date || "").slice(0, 10);
  const dow = dayOfWeekMon0(workDate);
  const avail = (worker.availability || []).find((a) => Number(a.day_of_week) === dow);
  if (avail?.unavailable_flag) {
    warnings.push("Worker marked unavailable on this day");
  } else if (avail?.available_from && avail?.available_to && entry.start_time && entry.end_time) {
    const st = parseTimeToMinutes(entry.start_time);
    const et = parseTimeToMinutes(entry.end_time);
    const af = parseTimeToMinutes(avail.available_from);
    const at = parseTimeToMinutes(avail.available_to);
    if (st != null && et != null && af != null && at != null && (st < af || et > at)) {
      warnings.push("Shift times outside worker availability window");
    }
  }
  if (entry.role_id) {
    const hasRole = (worker.role_skills || []).some(
      (s) => s.active !== false && String(s.role_id) === String(entry.role_id),
    );
    if ((worker.role_skills || []).length && !hasRole) {
      warnings.push("Worker has no active skill record for this role");
    }
    if (entry.work_stream_id && hasRole) {
      const hasCombo = (worker.role_skills || []).some(
        (s) =>
          s.active !== false &&
          String(s.role_id) === String(entry.role_id) &&
          (String(s.work_stream_id) === String(entry.work_stream_id) || !s.work_stream_id),
      );
      if (!hasCombo) {
        warnings.push("Worker has no skill record for this role and work stream");
      }
    }
  }
  if (entry.shift_id && worker.preferred_shift_id && String(entry.shift_id) !== String(worker.preferred_shift_id)) {
    warnings.push("Shift differs from worker preferred shift");
  }
  const stream = (settings?.work_streams || []).find((s) => String(s.id) === String(entry.work_stream_id));
  const sn = String(stream?.name || "").toLowerCase();
  if (sn.includes("rinse") && worker.can_work_rinse === false) {
    warnings.push("Worker not flagged for Rinse work stream");
  }
  if (sn.includes("drop") && worker.can_work_drop_off === false) {
    warnings.push("Worker not flagged for Drop Off work stream");
  }
  return [...new Set(warnings)];
}

export function applyWorkerProfileToForm(form, worker, settings) {
  if (!worker) return form;
  const next = { ...form };
  const prefShiftId = worker.preferred_shift_id;
  const dayDow = dayOfWeekMon0(form.work_date || new Date().toISOString().slice(0, 10));
  const dayAvail = (worker.availability || []).find((a) => Number(a.day_of_week) === dayDow);
  const shiftId = dayAvail?.preferred_shift_id || prefShiftId;
  if (shiftId) {
    next.shift_id = shiftId;
    const sh = (settings?.shifts || []).find((s) => String(s.id) === String(shiftId));
    if (sh) {
      next.start_time = sh.start_time_default?.slice(0, 5) || next.start_time;
      next.end_time = sh.end_time_default?.slice(0, 5) || next.end_time;
    }
  }
  if (worker.preferred_role_id && !next.role_id) {
    next.role_id = worker.preferred_role_id;
  }
  const roleId = next.role_id || worker.preferred_role_id;
  const streams = eligibleStreamsForWorker(worker, settings, roleId);
  if (streams.length === 1 && !next.work_stream_id) {
    next.work_stream_id = streams[0].id;
  } else if (!next.work_stream_id) {
    const skillStream = (worker.role_skills || []).find(
      (s) => s.active !== false && (!roleId || String(s.role_id) === String(roleId)) && s.work_stream_id,
    );
    if (skillStream) next.work_stream_id = skillStream.work_stream_id;
  }
  if (!next.role_id) {
    const roles = eligibleRolesForWorker(worker, settings);
    if (roles.length === 1) next.role_id = roles[0].id;
  }
  if (next.break_minutes == null) {
    next.break_minutes = settings?.default_break_minutes || 0;
  }
  return next;
}

export function workerProfileUrl(userId) {
  if (!userId) return null;
  return `/employees/${userId}`;
}

export function activeEntries(entries) {
  return (entries || []).filter(
    (e) => e && !e._deleted && e.status !== "cancelled" && e.status !== "replaced",
  );
}

export function entriesForDate(entries, ymd) {
  return activeEntries(entries).filter((e) => String(e.work_date).slice(0, 10) === ymd);
}

export function entriesForWeek(entries, weekStart) {
  const end = addDaysYmd(weekStart, 6);
  return activeEntries(entries).filter((e) => {
    const d = String(e.work_date).slice(0, 10);
    return d >= weekStart && d <= end;
  });
}

export function workerBalanceLabel(scheduledHours, settings, { available = true, daysScheduled = 0 } = {}) {
  const ot = Number(settings?.overtime_threshold_hours ?? 40);
  const under = Number(settings?.underused_hours_threshold ?? 15);
  const heavy = Number(settings?.heavy_hours_threshold ?? 35);
  const h = Number(scheduledHours || 0);
  if (h > ot) return { label: "Overtime Risk", color: "error" };
  if (h >= heavy) return { label: "Heavy", color: "warning" };
  if (available && h < under && daysScheduled <= 2) return { label: "Underused", color: "info" };
  return { label: "Balanced", color: "success" };
}

export function computeWorkerWeekStats(workerProfileId, entries, settings, weekStart, workerMeta = {}) {
  const weekEntries = entriesForWeek(entries, weekStart).filter(
    (e) => String(e.worker_profile_id) === String(workerProfileId),
  );
  const enriched = weekEntries.map((e) => enrichEntry(e, settings));
  const scheduledHours = enriched.reduce((s, e) => s + Number(e.scheduled_hours || 0), 0);
  const scheduledDays = new Set(enriched.map((e) => String(e.work_date).slice(0, 10))).size;
  const approvedHours = Number(workerMeta.approved_hours ?? 0);
  const otThreshold = Number(
    workerMeta.overtime_threshold ?? settings?.overtime_threshold_hours ?? 40,
  );
  const projected = Math.max(scheduledHours, approvedHours);
  const remaining = Math.max(0, otThreshold - projected);
  const avgPerDay = scheduledDays > 0 ? scheduledHours / scheduledDays : 0;
  const balance = workerBalanceLabel(scheduledHours, settings, {
    available: workerMeta.available !== false,
    daysScheduled: scheduledDays,
  });
  return {
    worker_profile_id: workerProfileId,
    scheduled_hours: scheduledHours,
    scheduled_days: scheduledDays,
    approved_hours: approvedHours,
    projected_hours: projected,
    overtime_threshold: otThreshold,
    hours_remaining_before_overtime: remaining,
    overtime_risk: projected > otThreshold,
    avg_hours_per_day: avgPerDay,
    balance_label: balance.label,
    balance_color: balance.color,
    entries: enriched,
  };
}

export function timesOverlap(a, b) {
  const aSt = parseTimeToMinutes(a.start_time);
  const aEt = parseTimeToMinutes(a.end_time);
  const bSt = parseTimeToMinutes(b.start_time);
  const bEt = parseTimeToMinutes(b.end_time);
  if ([aSt, aEt, bSt, bEt].some((x) => x == null)) return false;
  let aEnd = aEt;
  let bEnd = bEt;
  if (aEnd <= aSt) aEnd += 24 * 60;
  if (bEnd <= bSt) bEnd += 24 * 60;
  return aSt < bEnd && bSt < aEnd;
}

export function detectCoverageGaps(entries, coverageTargets, settings, workDate) {
  const dow = new Date(`${workDate}T12:00:00`).getDay();
  const monDow = dow === 0 ? 6 : dow - 1;
  const dayEntries = entriesForDate(entries, workDate).map((e) => enrichEntry(e, settings));
  const gaps = [];
  for (const target of coverageTargets || []) {
    if (!target.active) continue;
    if (target.day_of_week != null && Number(target.day_of_week) !== monDow) continue;
    const scheduled = dayEntries.filter(
      (e) =>
        String(e.shift_id) === String(target.shift_id) &&
        String(e.work_stream_id) === String(target.work_stream_id) &&
        String(e.role_id) === String(target.role_id),
    ).length;
    const required = Number(target.required_count || 0);
    let status = "covered";
    if (scheduled < required) status = "short";
    else if (scheduled > required) status = "overstaffed";
    if (status !== "covered" || required > 0) {
      gaps.push({
        ...target,
        shift_name: target.shift_name || settings?.shifts?.find((s) => s.id === target.shift_id)?.name,
        work_stream_name:
          target.work_stream_name ||
          settings?.work_streams?.find((s) => s.id === target.work_stream_id)?.name,
        role_name: target.role_name || settings?.roles?.find((r) => r.id === target.role_id)?.name,
        scheduled_count: scheduled,
        required_count: required,
        gap_count: required - scheduled,
        status,
      });
    }
  }
  return gaps;
}

export function previewHoursAfterAssignment(
  workerProfileId,
  entries,
  settings,
  weekStart,
  workerMeta,
  newHours,
  excludeEntryId = null,
) {
  const stats = computeWorkerWeekStats(workerProfileId, entries, settings, weekStart, workerMeta);
  let base = stats.scheduled_hours;
  if (excludeEntryId) {
    const ex = activeEntries(entries).find((e) => String(e.id) === String(excludeEntryId));
    if (ex && String(ex.worker_profile_id) === String(workerProfileId)) {
      base -= Number(ex.scheduled_hours || 0);
    }
  }
  const after = base + Number(newHours || 0);
  return {
    after,
    overtime_risk: after > stats.overtime_threshold,
    hours_remaining: Math.max(0, stats.overtime_threshold - after),
    threshold: stats.overtime_threshold,
  };
}

export function computeDayPlan(entries, settings, coverageTargets, workDate, workers = []) {
  const settingsWithWorkers = { ...settings, _workers: workers };
  const dayEntries = entriesForDate(entries, workDate).map((e) =>
    enrichEntry(e, settingsWithWorkers),
  );
  const weekStart = weekStartFromDate(workDate, settings?.week_starts_on ?? 0);
  const shifts = (settings?.shifts || []).filter((s) => s.active);
  const streams = (settings?.work_streams || []).filter((s) => s.active);

  const shiftPlans = shifts.map((shift) => {
    const shiftEntries = dayEntries.filter((e) => String(e.shift_id) === String(shift.id));
    const byStream = {};
    for (const stream of streams) {
      byStream[stream.name] = shiftEntries.filter(
        (e) => String(e.work_stream_id) === String(stream.id),
      );
    }
    const roleCounts = {};
    for (const e of shiftEntries) {
      const rn = e.role_name || "Unassigned";
      roleCounts[rn] = (roleCounts[rn] || 0) + 1;
    }
    const totalHours = shiftEntries.reduce((s, e) => s + Number(e.scheduled_hours || 0), 0);
    const totalCost = shiftEntries.reduce((s, e) => s + Number(e.estimated_cost || 0), 0);
    let otRisk = 0;
    for (const e of shiftEntries) {
      const wh = computeWorkerWeekStats(
        e.worker_profile_id,
        entries,
        settings,
        weekStart,
        workers.find((w) => String(w.worker_profile_id || w.id) === String(e.worker_profile_id)) || {},
      );
      if (wh.overtime_risk) otRisk += 1;
    }
    const gaps = detectCoverageGaps(entries, coverageTargets, settings, workDate).filter(
      (g) => String(g.shift_id) === String(shift.id),
    );
    return {
      shift_id: shift.id,
      shift_name: shift.name,
      people_count: shiftEntries.length,
      total_hours: totalHours,
      estimated_cost: totalCost,
      by_stream: byStream,
      role_counts: roleCounts,
      overtime_risk_count: otRisk,
      coverage_gaps: gaps,
      entries: shiftEntries,
    };
  });

  const gaps = detectCoverageGaps(entries, coverageTargets, settings, workDate);
  return computePlanSummary(entries, workers, settings, coverageTargets, {
    workDate,
    shiftPlans,
    open_coverage_gaps: gaps.filter((g) => g.status === "short").length,
  });
}

export function computePlanSummary(entries, workers, settings, coverageTargets, opts = {}) {
  const weekStart = opts.weekStart || weekStartFromDate(opts.workDate || new Date().toISOString().slice(0, 10), settings?.week_starts_on ?? 0);
  const scopeEntries = opts.workDate
    ? entriesForDate(entries, opts.workDate)
    : entriesForWeek(entries, weekStart);
  const enriched = scopeEntries.map((e) => enrichEntry(e, { ...settings, _workers: workers }));

  const countShift = (kw) =>
    enriched.filter((e) => String(e.shift_name || "").toLowerCase().includes(kw)).length;
  const countStream = (kw) =>
    enriched.filter((e) => String(e.work_stream_name || "").toLowerCase().includes(kw)).length;
  const countRole = (kw) =>
    enriched.filter((e) => String(e.role_name || "").toLowerCase().includes(kw)).length;

  const totalHours = enriched.reduce((s, e) => s + Number(e.scheduled_hours || 0), 0);
  const totalCost = enriched.reduce((s, e) => s + Number(e.estimated_cost || 0), 0);

  const workerStats = (workers || []).map((w) => {
    const wpid = w.worker_profile_id || w.id;
    const stats = computeWorkerWeekStats(wpid, entries, settings, weekStart, w);
    const weekEntries = entriesForWeek(entries, weekStart);
    const isScheduled = weekEntries.some((e) => String(e.worker_profile_id) === String(wpid));
    return { ...w, week_stats: stats, is_scheduled_this_week: isScheduled };
  });

  const overtimeRiskCount = workerStats.filter((w) => w.week_stats?.overtime_risk).length;
  const underused = workerStats.filter((w) => w.week_stats?.balance_label === "Underused");
  const heavy = workerStats.filter(
    (w) => w.week_stats?.balance_label === "Heavy" || w.week_stats?.balance_label === "Overtime Risk",
  );
  const unscheduledAvailable = workerStats.filter(
    (w) => w.active !== false && !w.is_scheduled_this_week,
  );

  const gaps =
    opts.workDate != null
      ? detectCoverageGaps(entries, coverageTargets, settings, opts.workDate)
      : [];

  return {
    total_people: enriched.length,
    morning_count: countShift("morning"),
    afternoon_count: countShift("afternoon"),
    evening_count: countShift("evening"),
    night_count: countShift("night"),
    rinse_count: countStream("rinse") + countStream("both"),
    drop_off_count: countStream("drop") + countStream("both"),
    operator_count: countRole("operator"),
    folder_count: countRole("folder"),
    total_scheduled_hours: totalHours,
    estimated_payroll_cost: totalCost,
    overtime_risk_count: overtimeRiskCount,
    open_coverage_gaps: opts.open_coverage_gaps ?? gaps.filter((g) => g.status === "short").length,
    coverage_gaps: gaps,
    underused_workers: underused,
    heavy_workers: heavy,
    unscheduled_available: unscheduledAvailable,
    worker_stats: workerStats,
    shift_plans: opts.shiftPlans || [],
    has_unsaved_changes: (entries || []).some((e) => e._dirty || String(e.id || "").startsWith("tmp-")),
    draft_count: (entries || []).filter((e) => e.publish_status === "draft" && !e._deleted).length,
    published_count: (entries || []).filter((e) => e.publish_status === "published" && !e._deleted).length,
  };
}

export function rankShiftSuggestions({
  workDate,
  shiftId,
  workStreamId,
  roleId,
  startTime,
  endTime,
  breakMinutes,
  entries,
  workers,
  settings,
}) {
  const weekStart = weekStartFromDate(workDate, settings?.week_starts_on ?? 0);
  const shiftHours = computeScheduledHours(startTime, endTime, breakMinutes);
  const dow = new Date(`${workDate}T12:00:00`).getDay();
  const monDow = dow === 0 ? 6 : dow - 1;
  const dayEntries = entriesForDate(entries, workDate);

  const candidates = [];
  for (const w of workers || []) {
    if (w.active === false) continue;
    const wpid = w.worker_profile_id || w.id;
    const reasons = [];
    let score = 0;

    const sameDay = dayEntries.filter((e) => String(e.worker_profile_id) === String(wpid));
    const probe = { start_time: startTime, end_time: endTime, work_date: workDate };
    if (sameDay.some((e) => timesOverlap(probe, e))) {
      continue;
    }
    reasons.push("Available: Yes");
    score += 50;

    const roleSkills = w.role_skills || [];
    const hasRole = roleSkills.some((s) => String(s.role_id) === String(roleId) && s.active !== false);
    if (roleId && hasRole) {
      score += 30;
      reasons.push("Role Match: Yes");
    } else if (roleId) {
      score -= 15;
      reasons.push("Role Match: No");
    }

    const streamSkills = roleSkills.filter((s) => String(s.work_stream_id) === String(workStreamId));
    if (workStreamId && streamSkills.length) {
      score += 20;
      reasons.push("Work Stream Match: Yes");
    }

    const wh = computeWorkerWeekStats(wpid, entries, settings, weekStart, w);
    const after = wh.scheduled_hours + shiftHours;
    const otThreshold = wh.overtime_threshold;
    const otRisk = after > otThreshold;
    reasons.push(`Current Weekly Hours: ${wh.scheduled_hours.toFixed(1)}`);
    reasons.push(`After This Shift: ${after.toFixed(1)}`);
    reasons.push(`Overtime Risk: ${otRisk ? "Yes" : "No"}`);
    if (otRisk) score -= 50;
    else score += Math.min(20, Math.floor(wh.hours_remaining_before_overtime));

    const perf = w.performance_preview;
    if (perf?.available) {
      score += 10;
      reasons.push("Performance: Strong");
    } else {
      reasons.push("Performance: No data yet");
    }

    if (w.availability) {
      const dayAvail = w.availability.find((a) => Number(a.day_of_week) === monDow);
      if (dayAvail?.unavailable_flag) continue;
    }

    const rate = Number(w.default_hourly_rate || 0);
    if (rate > 0) score -= rate * 0.5;

    let recommendation = "Good";
    if (score >= 80 && !otRisk) recommendation = "Best";
    else if (otRisk) recommendation = "Avoid unless necessary";

    candidates.push({
      worker_profile_id: wpid,
      user_id: w.user_id,
      worker_name: w.worker_name || w.display_name,
      worker_category_label: w.worker_category_label,
      score,
      recommendation,
      reasons,
      week_stats: wh,
      projected_hours_after: after,
      overtime_risk_after: otRisk,
      hourly_rate: rate,
      performance_preview: perf,
    });
  }

  candidates.sort((a, b) => b.score - a.score);
  return candidates.slice(0, 10);
}

export function newTempEntry(partial) {
  return {
    id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    publish_status: "draft",
    status: "scheduled",
    _dirty: true,
    ...partial,
  };
}

export function upsertLocalEntry(entries, entry) {
  const idx = entries.findIndex((e) => e.id === entry.id);
  const next = { ...entry, _dirty: true, publish_status: entry.publish_status || "draft" };
  if (idx >= 0) {
    const copy = [...entries];
    copy[idx] = next;
    return copy;
  }
  return [...entries, next];
}

export function removeLocalEntry(entries, entryId) {
  return entries.map((e) =>
    String(e.id) === String(entryId) ? { ...e, _deleted: true, _dirty: true } : e,
  );
}
