import { addDaysYmd, businessTodayYmd, weekEndFromStart, weekStartFromDate } from "../../utils/businessTime";

/** Inclusive business days. A full year, including leap day, still fits. */
export const MAX_TASK_RANGE_DAYS = 366;

export const TASK_RANGE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "this_week", label: "This Week" },
  { id: "last_week", label: "Last Week" },
  { id: "last_7", label: "Last 7 Days" },
  { id: "last_30", label: "Last 30 Days" },
  { id: "month", label: "This Month" },
  { id: "custom", label: "Custom" },
];

export function inclusiveSpanDays(start, end) {
  if (!start || !end) return 0;
  const [ys, ms, ds] = String(start).slice(0, 10).split("-").map((part) => parseInt(part, 10));
  const [ye, me, de] = String(end).slice(0, 10).split("-").map((part) => parseInt(part, 10));
  const from = Date.UTC(ys, ms - 1, ds);
  const to = Date.UTC(ye, me - 1, de);
  return Math.floor((to - from) / 86400000) + 1;
}

function monthBounds(ymd) {
  const [year, month] = String(ymd).slice(0, 10).split("-").map((part) => parseInt(part, 10));
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const start = `${String(ymd).slice(0, 8)}01`;
  const end = `${String(ymd).slice(0, 8)}${String(last).padStart(2, "0")}`;
  return { start, end };
}

/**
 * Task Dashboard ranges use America/New_York calendar dates.
 * This Week and Last Week are Monday through Sunday, the same week the Weekly Schedule shows.
 */
export function taskDashboardRange(preset, anchorYmd, customStart, customEnd) {
  const anchor = anchorYmd || businessTodayYmd();
  if (preset === "yesterday") {
    const day = addDaysYmd(anchor, -1);
    return { start: day, end: day };
  }
  if (preset === "this_week") {
    const start = weekStartFromDate(anchor, 0);
    return { start, end: weekEndFromStart(start) };
  }
  if (preset === "last_week") {
    const start = addDaysYmd(weekStartFromDate(anchor, 0), -7);
    return { start, end: weekEndFromStart(start) };
  }
  if (preset === "last_7" || preset === "7") {
    return { start: addDaysYmd(anchor, -6), end: anchor };
  }
  if (preset === "last_30" || preset === "30") {
    return { start: addDaysYmd(anchor, -29), end: anchor };
  }
  if (preset === "month") return monthBounds(anchor);
  if (preset === "custom") {
    let start = customStart || anchor;
    let end = customEnd || anchor;
    if (end < start) {
      const swap = start;
      start = end;
      end = swap;
    }
    return { start, end };
  }
  return { start: anchor, end: anchor };
}
