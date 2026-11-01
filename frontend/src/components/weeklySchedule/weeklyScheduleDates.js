import { businessTodayYmd } from "../../utils/businessTime";

/** Storage indexes: 0=Sunday … 6=Saturday. Do not reorder; columns use DISPLAY_DAY_ORDER. */
export const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Monday through Sunday, still addressed by the stored weekday index. */
export const DISPLAY_DAY_ORDER = [1, 2, 3, 4, 5, 6, 0];

function ymdFromLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Days from the Monday week start to this stored weekday. Sunday is the last column. */
export function dayOffset(dayOfWeek) {
  const dow = Number(dayOfWeek);
  return dow === 0 ? 6 : dow - 1;
}

/** Monday of the Monday–Sunday week that contains this calendar date. */
export function normalizeWeekStart(isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  const dow = d.getDay();
  d.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
  return ymdFromLocalDate(d);
}

/**
 * Week the schedule opens on in America/New_York.
 * Sunday opens the following Monday. Every other day opens the week that contains it.
 */
export function currentWeekStart() {
  const today = businessTodayYmd();
  const d = new Date(`${today}T12:00:00`);
  if (d.getDay() === 0) {
    d.setDate(d.getDate() + 1);
    return ymdFromLocalDate(d);
  }
  return normalizeWeekStart(today);
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
  d.setDate(d.getDate() + dayOffset(dayOfWeek));
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
