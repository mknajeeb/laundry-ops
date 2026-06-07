/**
 * Roster board layout + rule-based suggestions (client-side, live with draft edits).
 */

import {
  addDaysYmd,
  checkEntryProfileWarnings,
  computeDayPlan,
  computePlanSummary,
  computeWorkerWeekStats,
  enrichEntry,
  entriesForDate,
  rankShiftSuggestions,
  workerProfileGaps,
} from "./schedulePlanner";
import { formatDateShortLabel } from "../utils/businessTime";

const COVERAGE_STATUS = {
  covered: { label: "Covered", color: "success" },
  short: { label: "Short", color: "error" },
  overstaffed: { label: "Overstaffed", color: "warning" },
};

export function buildWeekDayColumns(weekStart) {
  const days = [];
  for (let i = 0; i < 7; i += 1) {
    const ymd = addDaysYmd(weekStart, i);
    const d = new Date(`${ymd}T12:00:00`);
    days.push({
      ymd,
      label: formatDateShortLabel(ymd),
      shortLabel: d.toLocaleDateString("en-US", { weekday: "short" }),
      dayIndex: i,
    });
  }
  return days;
}

export function buildRosterBoardData({
  entries,
  settings,
  coverageTargets,
  workers,
  weekStart,
  weekEnd,
  focusDate,
}) {
  const settingsWithWorkers = { ...settings, _workers: workers };
  const weekDays = buildWeekDayColumns(weekStart);
  const shifts = (settings?.shifts || [])
    .filter((s) => s.active)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  const daySummaries = {};
  const cells = {};
  const coverageByDay = {};

  for (const day of weekDays) {
    const ymd = day.ymd;
    const dayPlan = computeDayPlan(entries, settingsWithWorkers, coverageTargets, ymd, workers);
    daySummaries[ymd] = dayPlan;
    coverageByDay[ymd] = dayPlan.coverage_gaps || [];
    cells[ymd] = {};
    for (const shift of shifts) {
      const plan = (dayPlan.shift_plans || []).find((p) => String(p.shift_id) === String(shift.id));
      const shiftEntries = (plan?.entries || []).map((e) => {
        const enriched = enrichEntry(e, settingsWithWorkers);
        const w = workers.find((x) => String(x.id) === String(e.worker_profile_id));
        enriched.warnings = checkEntryProfileWarnings(enriched, w, settingsWithWorkers);
        enriched.profile_gaps = w?.profile_gaps || workerProfileGaps(w || {});
        return enriched;
      });
      cells[ymd][shift.id] = {
        shift_id: shift.id,
        shift_name: shift.name,
        entries: shiftEntries,
        by_stream: plan?.by_stream || {},
        people_count: shiftEntries.length,
        total_hours: plan?.total_hours ?? 0,
        estimated_cost: plan?.estimated_cost ?? 0,
        coverage_gaps: (plan?.coverage_gaps || []).map((g) => ({
          ...g,
          badge: COVERAGE_STATUS[g.status] || COVERAGE_STATUS.covered,
        })),
        role_counts: plan?.role_counts || {},
      };
    }
  }

  const weekSummary = computePlanSummary(entries, workers, settings, coverageTargets, { weekStart });
  const uniqueWorkers = new Set(
    (entries || [])
      .filter((e) => !e._deleted && e.status !== "cancelled" && e.status !== "replaced")
      .filter((e) => {
        const wd = String(e.work_date).slice(0, 10);
        return wd >= weekStart && wd <= weekEnd;
      })
      .map((e) => e.worker_profile_id),
  );

  const workerRoster = (workers || [])
    .map((w) => {
      const wpid = w.worker_profile_id || w.id;
      const stats = computeWorkerWeekStats(wpid, entries, settings, weekStart, w);
      const gaps = w.profile_gaps || workerProfileGaps(w);
      const weekEntries = stats.entries || [];
      const estCost = weekEntries.reduce(
        (s, e) => s + Number(e.estimated_cost || 0) || Number(e.scheduled_hours || 0) * Number(w.default_hourly_rate || 0),
        0,
      );
      return {
        ...w,
        worker_profile_id: wpid,
        week_stats: stats,
        profile_gaps: gaps,
        estimated_week_cost: estCost,
        max_hours: w.max_hours_per_week ?? settings?.max_hours_per_week,
      };
    })
    .filter((w) => w.active !== false)
    .sort((a, b) => (b.week_stats?.scheduled_hours || 0) - (a.week_stats?.scheduled_hours || 0));

  const focusDaySummary = focusDate ? daySummaries[focusDate] : null;

  return {
    weekDays,
    shifts,
    cells,
    daySummaries,
    coverageByDay,
    weekSummary: {
      ...weekSummary,
      unique_worker_count: uniqueWorkers.size,
      total_shift_slots: weekSummary.total_people,
    },
    focusDaySummary,
    workerRoster,
    draft_count: weekSummary.draft_count,
    published_count: weekSummary.published_count,
  };
}

export function computeRosterSuggestions({
  boardData,
  entries,
  workers,
  settings,
  coverageTargets,
  weekStart,
}) {
  const items = [];
  const settingsWithWorkers = { ...settings, _workers: workers };

  for (const day of boardData.weekDays || []) {
    const gaps = (boardData.coverageByDay[day.ymd] || []).filter((g) => g.status === "short");
    for (const gap of gaps) {
      const shift = (settings?.shifts || []).find((s) => String(s.id) === String(gap.shift_id));
      const ranked = rankShiftSuggestions({
        workDate: day.ymd,
        shiftId: gap.shift_id,
        workStreamId: gap.work_stream_id,
        roleId: gap.role_id,
        startTime: shift?.start_time_default?.slice(0, 5),
        endTime: shift?.end_time_default?.slice(0, 5),
        entries,
        workers,
        settings,
      });
      const best = ranked[0];
      items.push({
        id: `gap-${day.ymd}-${gap.shift_id}-${gap.role_id}`,
        type: "coverage_gap",
        severity: "error",
        title: `${day.shortLabel} ${gap.shift_name} ${gap.work_stream_name} ${gap.role_name} is short by ${gap.gap_count || 1}`,
        subtitle: best
          ? `Best candidate: ${best.worker_name}. ${(best.reasons || []).slice(0, 4).join(", ")}`
          : "No qualified worker found",
        work_date: day.ymd,
        gap,
        suggestion: best,
        action: "fill_gap",
      });
    }

    const over = (boardData.coverageByDay[day.ymd] || []).filter((g) => g.status === "overstaffed");
    for (const g of over) {
      items.push({
        id: `over-${day.ymd}-${g.shift_id}-${g.role_id}`,
        type: "overstaffed",
        severity: "warning",
        title: `${day.shortLabel} ${g.shift_name} ${g.work_stream_name} ${g.role_name} may be overstaffed`,
        subtitle: `Scheduled ${g.scheduled_count} vs required ${g.required_count}`,
        work_date: day.ymd,
        gap: g,
        action: "review",
      });
    }
  }

  for (const w of boardData.workerRoster || []) {
    const stats = w.week_stats;
    if (!stats) continue;
    if (stats.overtime_risk) {
      items.push({
        id: `ot-${w.worker_profile_id}`,
        type: "overtime",
        severity: "warning",
        title: `${w.worker_name || w.display_name} — overtime risk (${stats.scheduled_hours.toFixed(1)}h)`,
        subtitle: `Threshold ${stats.overtime_threshold}h · ${stats.hours_remaining_before_overtime.toFixed(1)}h remaining`,
        worker_profile_id: w.worker_profile_id,
        action: "review_worker",
      });
    } else if (stats.balance_label === "Underused") {
      items.push({
        id: `under-${w.worker_profile_id}`,
        type: "underused",
        severity: "info",
        title: `${w.worker_name || w.display_name} is underused`,
        subtitle: `${stats.scheduled_days} day(s) · ${stats.scheduled_hours.toFixed(1)}h this week`,
        worker_profile_id: w.worker_profile_id,
        action: "assign_more",
      });
    }
    if ((w.profile_gaps || []).length) {
      items.push({
        id: `prof-${w.worker_profile_id}`,
        type: "profile",
        severity: "warning",
        title: `${w.worker_name || w.display_name} — profile needs setup`,
        subtitle: w.profile_gaps.slice(0, 3).join(" · "),
        worker_profile_id: w.worker_profile_id,
        action: "open_profile",
      });
    }
  }

  for (const day of boardData.weekDays || []) {
    const dayEntries = entriesForDate(entries, day.ymd).map((e) => enrichEntry(e, settingsWithWorkers));
    for (const e of dayEntries) {
      const warnings = e.warnings || [];
      const availWarn = warnings.find((x) => x.toLowerCase().includes("availability"));
      if (availWarn) {
        items.push({
          id: `avail-${e.id}`,
          type: "availability",
          severity: "warning",
          title: `${e.worker_name} assigned outside availability`,
          subtitle: `${day.shortLabel} ${e.shift_name} · ${availWarn}`,
          entry: e,
          action: "edit_entry",
        });
      }
    }
  }

  const order = { error: 0, warning: 1, info: 2 };
  items.sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return items.slice(0, 25);
}

export function categoryCostsFromForecast(forecast) {
  const b = forecast?.category_breakdown || {};
  return {
    w2: Number(b.w2?.cost ?? 0),
    contractor_1099: Number(b.contractor_1099?.cost ?? 0),
    temp: Number(b.temp?.cost ?? 0),
  };
}

export { COVERAGE_STATUS };
