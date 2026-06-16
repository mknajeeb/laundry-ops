import {
  businessTodayYmd,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";

/** Default weekly pay period (Mon–Sun by maintenance week_starts_on). */
export function defaultPayPeriodRange(weekStartsOn = 0, anchorYmd) {
  const anchor = anchorYmd || businessTodayYmd();
  const start = weekStartFromDate(anchor, weekStartsOn);
  const end = weekEndFromStart(start);
  return { start, end };
}

/** Default custom range: both dates set to today. */
export function defaultRangeSearchDates(anchorYmd) {
  const today = anchorYmd || businessTodayYmd();
  return { start: today, end: today };
}

export const PAYROLL_SEARCH_MODES = [
  { id: "pay_period", label: "Pay period (weekly)" },
  { id: "range", label: "Date range" },
];
