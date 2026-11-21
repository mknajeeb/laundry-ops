/**
 * Eastern business-day ranges for the supervisor Issues screen.
 * Dates are YYYY-MM-DD America/New_York calendar days.
 */
import {
  addDaysYmd,
  businessTodayYmd,
  formatDateShortLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";

export const PIN_ISSUES_VIEW_KEY = "pinIssuesView.v1";

export function dayRange(anchor) {
  const day = String(anchor || "").slice(0, 10);
  return { mode: "day", anchor: day, from: day, to: day };
}

export function weekRange(anchor) {
  const day = String(anchor || "").slice(0, 10);
  const from = weekStartFromDate(day, 0);
  return { mode: "week", anchor: day, from, to: weekEndFromStart(from) };
}

export function customRange(from, to) {
  const a = String(from || "").slice(0, 10);
  const b = String(to || from || "").slice(0, 10);
  const start = a <= b ? a : b;
  const end = a <= b ? b : a;
  return { mode: "custom", anchor: start, from: start, to: end };
}

function clampToToday(range, today) {
  if (!range?.to || range.to <= today) return range;
  if (range.mode === "day" || range.from > today) return dayRange(today);
  return { ...range, to: today, anchor: range.from };
}

export function rangeFor(mode, anchor, from, to, today = businessTodayYmd()) {
  const day = anchor || today;
  if (mode === "week") return clampToToday(weekRange(day), today);
  if (mode === "custom") return clampToToday(customRange(from || day, to || from || day), today);
  return clampToToday(dayRange(day), today);
}

function inclusiveSpan(from, to) {
  const [y1, m1, d1] = String(from).split("-").map((n) => parseInt(n, 10));
  const [y2, m2, d2] = String(to).split("-").map((n) => parseInt(n, 10));
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86400000);
}

export function shiftRange(range, direction, today = businessTodayYmd()) {
  const step = direction < 0 ? -1 : 1;
  if (range?.mode === "week") {
    return rangeFor("week", addDaysYmd(range.anchor || range.from, 7 * step), null, null, today);
  }
  if (range?.mode === "custom") {
    const span = Math.max(0, inclusiveSpan(range.from, range.to));
    const delta = (span + 1) * step;
    const nextFrom = addDaysYmd(range.from, delta);
    const nextTo = addDaysYmd(range.to, delta);
    return rangeFor("custom", nextFrom, nextFrom, nextTo, today);
  }
  return rangeFor("day", addDaysYmd(range?.anchor || today, step), null, null, today);
}

export function canGoNext(range, today = businessTodayYmd()) {
  return Boolean(range?.to) && range.to < today;
}

export function rangeIncludesToday(range, today = businessTodayYmd()) {
  return Boolean(range?.from && range?.to) && range.from <= today && range.to >= today;
}

export function rangeLabel(range, today = businessTodayYmd()) {
  if (!range?.from) return "";
  if (range.mode === "day") {
    if (range.from === today) return "Today";
    if (range.from === addDaysYmd(today, -1)) return "Yesterday";
    return formatDateShortLabel(range.from);
  }
  if (range.from === range.to) return formatDateShortLabel(range.from);
  return `${formatDateShortLabel(range.from)} – ${formatDateShortLabel(range.to)}`;
}

export function loadPinIssuesView() {
  try {
    const raw = sessionStorage.getItem(PIN_ISSUES_VIEW_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function savePinIssuesView(view) {
  try {
    sessionStorage.setItem(PIN_ISSUES_VIEW_KEY, JSON.stringify(view));
  } catch {
    /* ignore */
  }
}

export function statusesForIssue(issue) {
  if (issue?.source === "rinse") return ["open", "investigating", "resolved", "excluded"];
  if (issue?.category === "orphan" || issue?.report_category === "orphan") {
    return ["new", "under_review", "returned", "stored", "resolved"];
  }
  return ["new", "under_review", "resolved"];
}

export function isClosedStatus(source, status) {
  const code = String(status || "").toLowerCase();
  if (source === "rinse") return code === "resolved" || code === "excluded";
  return code === "resolved" || code === "returned" || code === "stored";
}
