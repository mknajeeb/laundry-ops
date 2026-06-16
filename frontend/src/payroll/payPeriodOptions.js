import {
  addDaysYmd,
  businessTodayYmd,
  formatWeekRangeLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";

/** Weekly pay period options for dropdowns (past + future weeks). */
export function buildPayPeriodOptions(weekStartsOn = 0, { weeksBack = 78, weeksForward = 8 } = {}) {
  const today = businessTodayYmd();
  const currentStart = weekStartFromDate(today, weekStartsOn);
  const options = [];
  for (let offset = weeksForward; offset >= -weeksBack; offset -= 1) {
    const start = addDaysYmd(currentStart, offset * 7);
    const end = weekEndFromStart(start);
    options.push({
      start,
      end,
      key: `${start}|${end}`,
      label: formatWeekRangeLabel(start, end),
    });
  }
  return options;
}

export function findPayPeriodOption(options, start, end) {
  const key = `${start}|${end}`;
  return options.find((o) => o.key === key) || null;
}
