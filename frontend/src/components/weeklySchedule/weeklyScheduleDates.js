import { businessTodayYmd } from "../../utils/businessTime";

export const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function ymdFromLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function normalizeWeekStart(isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  const dow = d.getDay();
  d.setDate(d.getDate() - dow);
  return ymdFromLocalDate(d);
}

/** Current Sunday-start week in America/New_York (not UTC). */
export function currentWeekStart() {
  return normalizeWeekStart(businessTodayYmd());
}

export function shiftWeek(isoDate, deltaWeeks) {
  const d = new Date(`${isoDate}T12:00:00`);
  d.setDate(d.getDate() + deltaWeeks * 7);
  return normalizeWeekStart(ymdFromLocalDate(d));
}

export function formatWeekRange(weekStart) {
  const start = new Date(`${weekStart}T12:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const fmt = (dt) =>
    dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  return `${fmt(start)} – ${fmt(end)}`;
}

export function formatDayDate(weekStart, dayOfWeek) {
  const d = new Date(`${weekStart}T12:00:00`);
  d.setDate(d.getDate() + Number(dayOfWeek));
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
