import { scheduleRoleLabel } from "./weeklyScheduleRoles";

export const BREAKS_VIEW = { EMPLOYEE: "employee", TIME: "time" };
export const BREAK_INTERVAL_OPTIONS = [30, 15];

const DAY_MINUTES = 24 * 60;

function clock(minutes) {
  const h = Math.floor(minutes / 60) % 24;
  return { text: `${h % 12 || 12}:${String(minutes % 60).padStart(2, "0")}`, suffix: h < 12 ? "AM" : "PM" };
}

/** "10:00–10:30 AM", "11:45 AM–12:15 PM"; times past midnight of an overnight day get "(+1)". */
export function intervalLabel(start, end) {
  const a = clock(start);
  const b = clock(end);
  const text = a.suffix === b.suffix ? `${a.text}–${b.text} ${b.suffix}` : `${a.text} ${a.suffix}–${b.text} ${b.suffix}`;
  return start >= DAY_MINUTES ? `${text} (+1)` : text;
}

/** "8:45–9:15" — a person's exact break inside a cell; "(+1)" when it starts after midnight. */
export function breakClockLabel(start, end) {
  return `${clock(start).text}–${clock(end).text}${start >= DAY_MINUTES ? " (+1)" : ""}`;
}

function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const out = [];
  for (const range of sorted) {
    const last = out[out.length - 1];
    if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
    else out.push({ start: range.start, end: range.end });
  }
  return out;
}

/** Most employees on break at the same instant; ranges ending as another starts do not overlap. */
export function peakSimultaneous(rangesByUser) {
  const events = [];
  for (const ranges of rangesByUser) {
    for (const range of ranges) {
      if (range.end <= range.start) continue;
      events.push([range.start, 1], [range.end, -1]);
    }
  }
  events.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let current = 0;
  let peak = 0;
  let at = null;
  for (const [time, delta] of events) {
    current += delta;
    if (current > peak) {
      peak = current;
      at = time;
    }
  }
  return { peak, at };
}

function byName(a, b) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
}

/**
 * Breaks by time: shown days as columns, `interval`-minute rows (30 or 15) in clock order.
 *
 * Uses the same records as the by-employee grid — `breakRanges` (timed) and `unscheduledBreaks` (no time)
 * of each buildHourlyCoverage day, already limited to the selected roles. Each employee's timed breaks
 * are merged first, so a person counts once at any instant. A cell lists everyone whose break touches
 * the interval with their exact break time and the minutes that fall inside it; `hours` counts only that
 * overlap, so a 8:45–9:15 break adds 15 minutes to each of two 30-minute rows and interval hours add up
 * to the day's timed break hours. `count` is everyone breaking in the interval, `peak` the most on break
 * at the same moment (they differ for staggered breaks). Runs of two or more intervals without a break on
 * any shown day collapse into one `gap` row. Breaks without a time are never placed in a row; they stay
 * in each day's `untimed` list. Overnight breaks stay on the day the shift starts (minutes past 24:00).
 */
export function buildBreaksByTime({ days = [], dayIndices = [0, 1, 2, 3, 4, 5, 6], interval = 30, includeBreaks = true } = {}) {
  const step = BREAK_INTERVAL_OPTIONS.includes(Number(interval)) ? Number(interval) : 30;
  const dayByDow = new Map((days || []).map((day) => [day.dow, day]));
  const perDay = dayIndices.map((dow) => {
    const day = includeBreaks ? dayByDow.get(dow) : null;
    const users = new Map();
    for (const range of day?.breakRanges || []) {
      if (!(range.end > range.start)) continue;
      if (!users.has(range.userId)) users.set(range.userId, { userId: range.userId, name: range.name, ranges: [] });
      users.get(range.userId).ranges.push(range);
    }
    const people = [...users.values()].map((user) => ({ ...user, merged: mergeRanges(user.ranges) }));
    const timedMinutes = people.reduce((sum, p) => sum + p.merged.reduce((s, r) => s + (r.end - r.start), 0), 0);
    const untimed = [...(day?.unscheduledBreaks || [])].sort(byName);
    return {
      dow,
      people,
      untimed,
      timedBreakHours: timedMinutes / 60,
      untimedBreakHours: untimed.reduce((sum, item) => sum + Number(item.hours || 0), 0),
      ...peakSimultaneous(people.map((p) => p.merged)),
    };
  });

  let first = null;
  let last = null;
  for (const day of perDay) {
    for (const person of day.people) {
      for (const range of person.merged) {
        first = first == null ? range.start : Math.min(first, range.start);
        last = last == null ? range.end : Math.max(last, range.end);
      }
    }
  }

  const slots = [];
  if (first != null) {
    for (let start = Math.floor(first / step) * step; start < last; start += step) {
      const end = start + step;
      const cells = {};
      let any = false;
      for (const day of perDay) {
        const list = [];
        let minutes = 0;
        for (const person of day.people) {
          const clipped = person.merged
            .map((r) => ({ start: Math.max(r.start, start), end: Math.min(r.end, end) }))
            .filter((r) => r.end > r.start);
          if (!clipped.length) continue;
          const inside = clipped.reduce((sum, r) => sum + (r.end - r.start), 0);
          minutes += inside;
          const touching = person.ranges.filter((r) => r.start < end && r.end > start).sort((a, b) => a.start - b.start);
          list.push({
            userId: person.userId,
            name: person.name,
            minutes: inside,
            clipped,
            breaks: touching.map((r) => ({
              start: r.start,
              end: r.end,
              label: breakClockLabel(r.start, r.end),
              fullLabel: r.label,
              entry: r.entry,
              roles: r.roles || [],
            })),
            partial: touching.some((r) => r.start < start || r.end > end),
          });
        }
        list.sort(byName);
        const { peak } = peakSimultaneous(list.map((p) => p.clipped));
        if (list.length) any = true;
        cells[day.dow] = { people: list, count: list.length, hours: minutes / 60, peak };
      }
      slots.push({ start, end, label: intervalLabel(start, end), cells, empty: !any });
    }
  }

  const rows = [];
  for (let i = 0; i < slots.length; ) {
    if (!slots[i].empty) {
      rows.push(slots[i]);
      i += 1;
      continue;
    }
    let j = i;
    while (j < slots.length && slots[j].empty) j += 1;
    if (j - i >= 2) {
      rows.push({ gap: true, start: slots[i].start, end: slots[j - 1].end, label: intervalLabel(slots[i].start, slots[j - 1].end), cells: {} });
    } else {
      rows.push(slots[i]);
    }
    i = j;
  }

  const columns = perDay.map((day) => ({
    dow: day.dow,
    timedBreakHours: day.timedBreakHours,
    untimedBreakHours: day.untimedBreakHours,
    breakHours: day.timedBreakHours + day.untimedBreakHours,
    intervalHours: slots.reduce((sum, slot) => sum + (slot.cells[day.dow]?.hours || 0), 0),
    peak: day.peak,
    peakAt: day.at,
    peopleCount: day.people.length,
    untimed: day.untimed,
  }));
  const week = columns.reduce(
    (acc, c) => ({
      timedBreakHours: acc.timedBreakHours + c.timedBreakHours,
      untimedBreakHours: acc.untimedBreakHours + c.untimedBreakHours,
      intervalHours: acc.intervalHours + c.intervalHours,
      peak: Math.max(acc.peak, c.peak),
    }),
    { timedBreakHours: 0, untimedBreakHours: 0, intervalHours: 0, peak: 0 },
  );
  return { interval: step, columns, rows, week, hasTimed: slots.length > 0 };
}

function hoursNumber(hours) {
  return Math.round(Number(hours || 0) * 100) / 100;
}

/** "1.5 break-hours" / "1 break-hour". */
export function breakHoursText(hours) {
  const value = hoursNumber(hours);
  return `${value} ${value === 1 ? "break-hour" : "break-hours"}`;
}

/**
 * Cell headline: "3 on break · 1.5 break-hours" when everyone listed is on break together at some moment,
 * otherwise "3 take a break · max 2 at once · 1 break-hour" so the list does not read as one overlap.
 */
export function slotHeadline(cell) {
  if (!cell?.count) return "";
  if (cell.peak === cell.count) return `${cell.count} on break \u00b7 ${breakHoursText(cell.hours)}`;
  return `${cell.count} take a break \u00b7 max ${cell.peak} at once \u00b7 ${breakHoursText(cell.hours)}`;
}

/** "8:45–9:15 · 15 min here" — exact break plus the part inside the interval when it crosses rows. */
export function slotPersonDetail(person) {
  const times = person.breaks.map((b) => b.label).join(", ");
  return person.partial ? `${times} \u00b7 ${person.minutes} min here` : times;
}

/** Day header: "Scheduled 1.5h · Not scheduled 0.5h · Peak 3 at once". */
export function byTimeDayHeaderText(column, formatHours) {
  const parts = [`Scheduled ${formatHours(column.timedBreakHours)}`];
  if (column.untimedBreakHours > 0.0001) parts.push(`Not scheduled ${formatHours(column.untimedBreakHours)}`);
  parts.push(column.peak ? `Peak ${column.peak} at once` : "No timed breaks");
  return parts.join(" \u00b7 ");
}

/** "Amna · 30 min · Fold" for the Not scheduled row; "not allocated to a role" on multi-role shifts. */
export function untimedPersonText(item) {
  const parts = [item.name, `${Math.round(Number(item.hours || 0) * 60)} min`];
  const roles = (item.roles || []).map((role) => scheduleRoleLabel(role));
  if (roles.length) parts.push(roles.join("/"));
  if (item.unallocated) parts.push("not allocated to a role");
  return parts.join(" \u00b7 ");
}

/** Shading strength 0..1 for a cell, from its simultaneous peak against the week's highest peak. */
export function peakIntensity(peak, weekPeak) {
  if (!peak || !weekPeak) return 0;
  return peak / weekPeak;
}
