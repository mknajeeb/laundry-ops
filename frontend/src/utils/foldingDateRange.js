import { isoDateInput } from "./foldingFormat";
import {
  defaultWeekRangeEastern,
  easternIsoDate,
  lastNDaysRangeEastern,
  monthRangeEastern,
  todayRangeEastern,
  yesterdayRangeEastern,
} from "./foldingEasternDate";

/** Monday-based week containing `d` (Eastern calendar). */
export function defaultWeekRange(d = new Date()) {
  return defaultWeekRangeEastern(d);
}

export function todayRange() {
  return todayRangeEastern();
}

export function yesterdayRange() {
  return yesterdayRangeEastern();
}

export function last7DaysRange() {
  return lastNDaysRangeEastern(7);
}

export function last30DaysRange() {
  return lastNDaysRangeEastern(30);
}

export function monthRange(d = new Date()) {
  return monthRangeEastern(d);
}

/** API query params for folding endpoints. */
export function foldingRangeParams({ dateStart, dateEnd, dateField = "folding_work_date" }) {
  return {
    date_start: dateStart,
    date_end: dateEnd,
    date_field: dateField,
    timezone: "America/New_York",
  };
}

export { easternIsoDate };
