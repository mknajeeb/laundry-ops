import { isoDateInput } from "./foldingFormat";

/** Monday-based week containing `d` (inclusive Mon–Sun). */
export function defaultWeekRange(d = new Date()) {
  const day = d.getDay();
  const mondayOffset = (day + 6) % 7;
  const start = new Date(d);
  start.setDate(d.getDate() - mondayOffset);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return { start: isoDateInput(start), end: isoDateInput(end) };
}

export function todayRange() {
  const t = isoDateInput();
  return { start: t, end: t };
}

export function monthRange(d = new Date()) {
  const start = new Date(d.getFullYear(), d.getMonth(), 1);
  const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return { start: isoDateInput(start), end: isoDateInput(end) };
}

/** API query params for folding endpoints. */
export function foldingRangeParams({ dateStart, dateEnd, dateField = "folding_work_date" }) {
  return {
    date_start: dateStart,
    date_end: dateEnd,
    date_field: dateField,
  };
}
