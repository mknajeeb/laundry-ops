/**
 * Replacement ranking for sick/absent shifts (no location/geofence).
 */

import { computeScheduledHours, rankShiftSuggestions } from "./schedulePlanner";

export function formatReplacementReasons(suggestion, entryHours) {
  const wh = suggestion.week_stats || suggestion.week_hours || {};
  const current = Number(wh.scheduled_hours ?? wh.projected_hours ?? suggestion.current_weekly_hours ?? 0);
  const after = Number(suggestion.projected_hours_after ?? current + entryHours);
  const rate = Number(suggestion.hourly_rate ?? wh.hourly_rate ?? 0);
  const lines = [
    `Available: ${suggestion.available !== false ? "Yes" : "No"}`,
  ];
  const roleName = entryHours?.role_name || suggestion.role_match;
  if (roleName) lines.push(`Role match: ${roleName}`);
  if (suggestion.stream_match || suggestion.work_stream_name) {
    lines.push(`Stream match: ${suggestion.stream_match || suggestion.work_stream_name}`);
  }
  lines.push(`Current weekly hours: ${current.toFixed(1)}`);
  lines.push(`After replacement: ${after.toFixed(1)}`);
  lines.push(`Overtime risk: ${suggestion.overtime_risk_after ? "Yes" : "No"}`);
  const addedCost = entryHours * rate;
  if (rate > 0) lines.push(`Estimated added cost: $${addedCost.toFixed(0)}`);
  return lines;
}

export function rankReplacementsForEntry(entry, { workers, draftEntries, settings }) {
  const workDate = String(entry.work_date).slice(0, 10);
  const hours = Number(entry.scheduled_hours || computeScheduledHours(entry.start_time, entry.end_time, entry.break_minutes));
  const ranked = rankShiftSuggestions({
    workDate,
    shiftId: entry.shift_id,
    workStreamId: entry.work_stream_id,
    roleId: entry.role_id,
    startTime: entry.start_time?.slice?.(0, 5) || entry.start_time,
    endTime: entry.end_time?.slice?.(0, 5) || entry.end_time,
    breakMinutes: entry.break_minutes,
    entries: draftEntries.filter((e) => String(e.id) !== String(entry.id)),
    workers: workers.filter((w) => String(w.id) !== String(entry.worker_profile_id)),
    settings,
  });

  return ranked.map((s) => {
    const rate = Number(s.hourly_rate || 0);
    const after = Number(s.projected_hours_after || 0);
    const current = after - hours;
    return {
      ...s,
      current_weekly_hours: current,
      estimated_added_cost: hours * rate,
      role_match: entry.role_name || "Yes",
      stream_match: entry.work_stream_name || "Yes",
      available: true,
      reasons: s.reasons?.length ? s.reasons : formatReplacementReasons(s, hours),
    };
  });
}

export function normalizeApiReplacement(s, entry) {
  const hours = Number(entry.scheduled_hours || 0);
  const wh = s.week_hours || {};
  const current = Number(wh.scheduled_hours ?? wh.projected_hours ?? 0);
  const after = Number(s.projected_hours_after ?? current + hours);
  const rate = Number(s.hourly_rate || wh.hourly_rate || 0);
  let recommendation = "Good";
  if (s.score >= 120 && !s.overtime_risk_after) recommendation = "Best";
  else if (s.overtime_risk_after) recommendation = "Avoid";

  return {
    ...s,
    worker_name: s.worker_name || s.display_name,
    recommendation,
    current_weekly_hours: current,
    projected_hours_after: after,
    estimated_added_cost: hours * rate,
    reasons: [
      "Available: Yes",
      `Role match: ${entry.role_name || "—"}`,
      `Stream match: ${entry.work_stream_name || "—"}`,
      `Current weekly hours: ${current.toFixed(1)}`,
      `After replacement: ${after.toFixed(1)}`,
      `Overtime risk: ${s.overtime_risk_after ? "Yes" : "No"}`,
      `Estimated added cost: $${(hours * rate).toFixed(0)}`,
    ],
  };
}
