import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const ROLE_ORDER = [
  "wash",
  "sort",
  "weigher",
  "fold",
  "pt_washer",
  "pt_sorter",
  "pt_folder",
  "hd_operator",
  "hd_folder",
  "non_rinse_folder",
  "attendant",
];

/** Roles that show scheduled-hour totals in day/week summaries (PT kept separate). */
export const HOUR_TRACKED_ROLES = ["wash", "sort", "fold", "pt_washer", "pt_sorter", "pt_folder"];

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "wash", label: "Wash" },
  { value: "sort", label: "Sort" },
  { value: "weigher", label: "Weigher" },
  { value: "fold", label: "Fold" },
  { value: "pt_washer", label: "PT Washer" },
  { value: "pt_sorter", label: "PT Sorter" },
  { value: "pt_folder", label: "PT Folder" },
  { value: "hd_operator", label: "HD Operator" },
  { value: "hd_folder", label: "HD Folder" },
  { value: "non_rinse_folder", label: "Non-Rinse Folder" },
  { value: "attendant", label: "Attendant" },
];

const ROLE_ORDER_INDEX = Object.fromEntries(ROLE_ORDER.map((role, index) => [role, index]));
const HOUR_TRACKED_ROLE_SET = new Set(HOUR_TRACKED_ROLES);

/** Short labels for tight grid cells and day headers. */
export const ROLE_COMPACT_LABELS = {
  wash: "Wash",
  sort: "Sort",
  weigher: "Weigh",
  fold: "Fold",
  pt_washer: "PT Wash",
  pt_sorter: "PT Sort",
  pt_folder: "PT Fold",
  hd_operator: "HD Op",
  hd_folder: "HD Fold",
  non_rinse_folder: "NR Fold",
  attendant: "Attend",
};

export function roleCompactLabel(roleKey) {
  return ROLE_COMPACT_LABELS[roleKey] || ROLE_STYLES[roleKey]?.label || roleKey;
}

export function sortRoles(roles) {
  return [...(roles || [])].sort(
    (a, b) => (ROLE_ORDER_INDEX[a] ?? 99) - (ROLE_ORDER_INDEX[b] ?? 99),
  );
}

/** Role accents — distinct card fills, borders, and chip tints. */
export const ROLE_STYLES = {
  sort: {
    accent: VEEWASH_DASHBOARD.primaryBlueDark,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    hoverBg: "#d9f0f5",
    chipBg: "#e0f4f8",
    cellBg: "#f2fafc",
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
    label: "Sort",
  },
  wash: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.pendingLight,
    hoverBg: "#ffe8cc",
    chipBg: "#fff4e0",
    cellBg: "#fffbf3",
    border: VEEWASH_DASHBOARD.pendingBorder,
    label: "Wash",
  },
  fold: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: VEEWASH_DASHBOARD.tealLight,
    hoverBg: "#d4f2ed",
    chipBg: "#e4f7f3",
    cellBg: "#f3faf8",
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  pt_washer: {
    accent: "#c2410c",
    bg: "#ffedd5",
    hoverBg: "#fed7aa",
    chipBg: "#fff7ed",
    cellBg: "#fffaf5",
    border: "rgba(194, 65, 12, 0.28)",
    label: "PT Washer",
  },
  pt_sorter: {
    accent: "#0369a1",
    bg: "#e0f2fe",
    hoverBg: "#bae6fd",
    chipBg: "#f0f9ff",
    cellBg: "#f8fcff",
    border: "rgba(3, 105, 161, 0.28)",
    label: "PT Sorter",
  },
  pt_folder: {
    accent: "#047857",
    bg: "#d1fae5",
    hoverBg: "#a7f3d0",
    chipBg: "#ecfdf5",
    cellBg: "#f5fdf8",
    border: "rgba(4, 120, 87, 0.28)",
    label: "PT Folder",
  },
  weigher: {
    accent: "#6d28d9",
    bg: "#f3e8ff",
    hoverBg: "#e9d5ff",
    chipBg: "#ede9fe",
    cellBg: "#faf5ff",
    border: "rgba(109, 40, 217, 0.28)",
    label: "Weigher",
  },
  hd_operator: {
    accent: "#be185d",
    bg: "#fce7f3",
    hoverBg: "#fbcfe8",
    chipBg: "#fdf2f8",
    cellBg: "#fff5fa",
    border: "rgba(190, 24, 93, 0.28)",
    label: "HD Operator",
  },
  hd_folder: {
    accent: "#0f766e",
    bg: "#ccfbf1",
    hoverBg: "#99f6e4",
    chipBg: "#d1faf5",
    cellBg: "#ecfdf5",
    border: "rgba(15, 118, 110, 0.28)",
    label: "HD Folder",
  },
  non_rinse_folder: {
    accent: "#4338ca",
    bg: "#e0e7ff",
    hoverBg: "#c7d2fe",
    chipBg: "#eef2ff",
    cellBg: "#f5f7ff",
    border: "rgba(67, 56, 202, 0.28)",
    label: "Non-Rinse Folder",
  },
  attendant: {
    accent: "#b45309",
    bg: "#fef3c7",
    hoverBg: "#fde68a",
    chipBg: "#fff7ed",
    cellBg: "#fffbeb",
    border: "rgba(180, 83, 9, 0.28)",
    label: "Attendant",
  },
  folder: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: VEEWASH_DASHBOARD.tealLight,
    hoverBg: "#d4f2ed",
    chipBg: "#e4f7f3",
    cellBg: "#f3faf8",
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  operator: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.pendingLight,
    hoverBg: "#ffe8cc",
    chipBg: "#fff4e0",
    cellBg: "#fffbf3",
    border: VEEWASH_DASHBOARD.pendingBorder,
    label: "Wash",
  },
};

function normalizeFrontendRole(role) {
  const key = String(role || "").trim().toLowerCase();
  if (key === "folder") return "fold";
  if (key === "operator") return "wash";
  if (key === "pt wash" || key === "pt_wash") return "pt_washer";
  if (key === "pt sort" || key === "pt_sort") return "pt_sorter";
  if (key === "pt fold" || key === "pt_fold") return "pt_folder";
  return key;
}

export function parseEntryRoles(entry) {
  let roles;
  if (Array.isArray(entry?.roles) && entry.roles.length) {
    roles = entry.roles.map((r) => normalizeFrontendRole(r));
  } else {
    const raw = String(entry?.role || "fold");
    roles = raw
      .split(",")
      .map((r) => normalizeFrontendRole(r.trim()))
      .filter(Boolean);
  }
  return sortRoles(roles);
}

/** Format scheduled hours: whole numbers without decimals, otherwise one decimal. */
export function formatRoleHoursLabel(hours) {
  const n = Number(hours || 0);
  if (!Number.isFinite(n) || n <= 0) return "0h";
  const rounded = Math.round(n * 10) / 10;
  return Number.isInteger(rounded) ? `${rounded}h` : `${rounded.toFixed(1)}h`;
}

function entryIntervalMinutes(entry) {
  const start = parseTimeToMinutes(normalizeTimeHm(entry?.start_time));
  let end = parseTimeToMinutes(normalizeTimeHm(entry?.end_time));
  if (start == null || end == null) return null;
  if (end <= start) end += 24 * 60;
  const breakMin = Math.max(0, Number(entry?.break_minutes || 0));
  const hours = Math.max(0, end - start - breakMin) / 60;
  return { start, end, breakMin, hours };
}

function intervalsOverlap(a, b) {
  return a.start < b.end && b.start < a.end;
}

function hasOverlappingIntervals(intervals) {
  for (let i = 0; i < intervals.length; i += 1) {
    for (let j = i + 1; j < intervals.length; j += 1) {
      if (intervalsOverlap(intervals[i], intervals[j])) return true;
    }
  }
  return false;
}

function mergeIntervalHours(intervals) {
  if (!intervals.length) return 0;
  const sorted = [...intervals].sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [{ start: sorted[0].start, end: sorted[0].end }];
  for (let i = 1; i < sorted.length; i += 1) {
    const cur = sorted[i];
    const last = merged[merged.length - 1];
    if (cur.start < last.end) {
      last.end = Math.max(last.end, cur.end);
    } else {
      merged.push({ start: cur.start, end: cur.end });
    }
  }
  // Overlap path uses merged wall-clock minutes (breaks already ambiguous across overlaps).
  return merged.reduce((sum, iv) => sum + Math.max(0, iv.end - iv.start) / 60, 0);
}

/**
 * Allocate scheduled hours to hour-tracked roles from role segments.
 * Multi-role entries split segment hours evenly across their hour-tracked roles.
 * Overlapping segments for the same employee/day/role are merged (no double-count).
 */
export function allocateRoleHoursByDay(entries) {
  const byDay = Array.from({ length: 7 }, () => {
    const hours = {};
    for (const role of HOUR_TRACKED_ROLES) hours[role] = 0;
    return hours;
  });

  /** @type {Map<string, Array<{start:number,end:number,hours:number}>>} */
  const buckets = new Map();

  for (const entry of entries || []) {
    const uid = Number(entry.user_id);
    const dow = Number(entry.day_of_week || 0);
    if (!Number.isInteger(dow) || dow < 0 || dow > 6) continue;

    const roles = parseEntryRoles(entry);
    const hourRoles = roles.filter((role) => HOUR_TRACKED_ROLE_SET.has(role));
    if (!hourRoles.length) continue;

    const interval = entryIntervalMinutes(entry);
    const segmentHours = interval
      ? interval.hours
      : Math.max(0, Number(entry.hours || 0));
    if (segmentHours <= 0) continue;

    const share = segmentHours / hourRoles.length;
    for (const role of hourRoles) {
      const key = `${uid}|${dow}|${role}`;
      const list = buckets.get(key) || [];
      if (interval) {
        list.push({ start: interval.start, end: interval.end, hours: share });
      } else {
        // No clock range — accumulate share directly via a zero-width placeholder.
        list.push({ start: 0, end: 0, hours: share, direct: true });
      }
      buckets.set(key, list);
    }
  }

  for (const [key, list] of buckets.entries()) {
    const parts = key.split("|");
    const dow = Number(parts[1]);
    const role = parts[2];
    const timed = list.filter((item) => !item.direct);
    const direct = list.filter((item) => item.direct);
    let hours = direct.reduce((sum, item) => sum + item.hours, 0);
    if (timed.length) {
      if (hasOverlappingIntervals(timed)) {
        // Preserve multi-role weight when merging overlaps (all shares equal for a role key).
        const weight = timed[0].hours > 0 && timed[0].end > timed[0].start
          ? timed[0].hours / ((timed[0].end - timed[0].start) / 60)
          : 1;
        hours += mergeIntervalHours(timed) * Math.min(1, weight || 1);
      } else {
        hours += timed.reduce((sum, item) => sum + item.hours, 0);
      }
    }
    byDay[dow][role] += hours;
  }

  return byDay.map((day) => {
    const out = {};
    for (const role of HOUR_TRACKED_ROLES) {
      out[role] = Math.round((day[role] || 0) * 10) / 10;
    }
    return out;
  });
}

export function emptyRoleHourTotals() {
  const out = {};
  for (const role of HOUR_TRACKED_ROLES) out[`${role}_hours`] = 0;
  return out;
}

export function sumRoleHoursAcrossDays(dayRoleHours) {
  const totals = emptyRoleHourTotals();
  for (const day of dayRoleHours || []) {
    for (const role of HOUR_TRACKED_ROLES) {
      totals[`${role}_hours`] = Math.round(((totals[`${role}_hours`] || 0) + Number(day[role] || 0)) * 10) / 10;
    }
  }
  return totals;
}

export function primaryRoleStyle(entry) {
  const roles = parseEntryRoles(entry);
  const key = roles[0] || "fold";
  return ROLE_STYLES[key] || ROLE_STYLES.fold;
}

function blendRoleColors(colors, direction = "135deg") {
  if (!colors.length) return ROLE_STYLES.fold.bg;
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map((color, i) => `${color} ${i * step}%, ${color} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(${direction}, ${stops})`;
}

/** Shift card fill, border, and stripe styling from one or more roles. */
export function entryRoleCardStyle(entryOrRoles) {
  const roles = Array.isArray(entryOrRoles) ? sortRoles(entryOrRoles) : parseEntryRoles(entryOrRoles);
  const keys = roles.length ? roles : ["fold"];
  const styles = keys.map((key) => ROLE_STYLES[key] || ROLE_STYLES.fold);
  const primary = styles[0];

  if (styles.length === 1) {
    return {
      bg: primary.bg,
      hoverBg: primary.hoverBg,
      border: primary.border,
      accent: primary.accent,
      stripe: primary.accent,
      multiRole: false,
    };
  }

  return {
    bg: blendRoleColors(styles.map((style) => style.bg)),
    hoverBg: blendRoleColors(styles.map((style) => style.hoverBg)),
    border: blendRoleColors(styles.map((style) => style.border), "90deg"),
    accent: primary.accent,
    stripe: roleStripeGradient(keys),
    multiRole: true,
  };
}

export function roleStripeGradient(roles) {
  const keys = sortRoles(roles.length ? roles : ["fold"]);
  const colors = keys.map((k) => (ROLE_STYLES[k] || ROLE_STYLES.fold).accent);
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map((c, i) => `${c} ${i * step}%, ${c} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(180deg, ${stops})`;
}

export function roleLabels(roles) {
  return sortRoles(roles).map((r) => ROLE_STYLES[r]?.label || r).join(" · ");
}

/** Morning vs afternoon card styling — classified by shift start time (before 2 PM = morning). */
export const SHIFT_PERIOD_STYLES = {
  morning: {
    bg: "#e8f4fc",
    hoverBg: "#dceefb",
    border: "rgba(59, 130, 246, 0.32)",
    accent: "#2563eb",
    label: "Morning",
  },
  afternoon: {
    bg: "#fff4eb",
    hoverBg: "#ffe8d9",
    border: "rgba(234, 88, 12, 0.32)",
    accent: "#ea580c",
    label: "Afternoon",
  },
};

const AFTERNOON_START_MINUTES = 14 * 60;

export function shiftPeriodKey(entry) {
  const mins = parseTimeToMinutes(normalizeTimeHm(entry?.start_time));
  if (mins == null) return "morning";
  return mins >= AFTERNOON_START_MINUTES ? "afternoon" : "morning";
}

export function shiftPeriodStyle(entry) {
  return SHIFT_PERIOD_STYLES[shiftPeriodKey(entry)] || SHIFT_PERIOD_STYLES.morning;
}

/** Count each role assignment for an employee across the week (multi-role shifts count each role). */
export function employeeWeeklyRoleCounts(userId, entries) {
  const counts = {};
  for (const entry of entries || []) {
    if (Number(entry.user_id) !== Number(userId)) continue;
    for (const roleKey of parseEntryRoles(entry)) {
      counts[roleKey] = (counts[roleKey] || 0) + 1;
    }
  }
  return sortRoles(Object.keys(counts)).map((key) => ({
    key,
    label: ROLE_STYLES[key]?.label || key,
    count: counts[key],
    style: ROLE_STYLES[key] || ROLE_STYLES.fold,
  }));
}

/** Unique roles assigned to an employee across their week entries, in Wash · Sort · Fold order. */
export function employeeScheduleRoles(userId, entries) {
  const seen = new Set();
  for (const entry of entries || []) {
    if (Number(entry.user_id) !== Number(userId)) continue;
    for (const roleKey of parseEntryRoles(entry)) {
      seen.add(roleKey);
    }
  }
  return sortRoles([...seen]);
}

/** Primary role for an employee row — most frequent role across their week entries. */
export function deriveEmployeePrimaryRole(userId, entries) {
  const counts = {};
  for (const entry of entries || []) {
    if (Number(entry.user_id) !== Number(userId)) continue;
    for (const roleKey of parseEntryRoles(entry)) {
      counts[roleKey] = (counts[roleKey] || 0) + 1;
    }
  }
  const ranked = Object.entries(counts).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return (ROLE_ORDER_INDEX[a[0]] ?? 99) - (ROLE_ORDER_INDEX[b[0]] ?? 99);
  });
  return ranked[0]?.[0] || null;
}

export function formatEmployeeWeeklySummary(employee, { daysOnly = false } = {}) {
  const hours = Number(employee?.total_hours || 0);
  const days = Number(employee?.scheduled_days || 0);
  const dayLabel = days === 1 ? "1 day" : `${days} days`;
  if (daysOnly) return dayLabel;
  const hrsLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  return `${hrsLabel} hrs • ${dayLabel}`;
}

export function computeWeekSummary(data, { includeExcluded = false, userIds = null, entries = null, daysOnly = false } = {}) {
  const allowed = userIds ? new Set(userIds.map(Number)) : null;
  const sourceEntries = entries ?? data?.entries ?? [];
  const filteredEntries = sourceEntries.filter((entry) => {
    const uid = Number(entry.user_id);
    if (allowed && !allowed.has(uid)) return false;
    const employee = (data?.employees || []).find((e) => Number(e.user_id) === uid);
    if (employee?.excluded && !includeExcluded) return false;
    return true;
  });

  let totalHours = 0;
  let totalDays = 0;
  const roleCounts = Object.fromEntries(ROLE_ORDER.map((role) => [role, 0]));
  const scheduledUserIds = new Set();

  for (const entry of filteredEntries) {
    const uid = Number(entry.user_id);
    scheduledUserIds.add(uid);
    totalDays += 1;
    const hours = Number(entry.hours || 0);
    totalHours += hours;
    const roles = parseEntryRoles(entry);
    const countedRoles = roles.length ? roles : ["fold"];
    for (const role of countedRoles) {
      if (role in roleCounts) roleCounts[role] += 1;
    }
  }

  const roleHoursByDay = allocateRoleHoursByDay(filteredEntries);
  const roleHourTotals = sumRoleHoursAcrossDays(roleHoursByDay);

  let employeesScheduled = 0;
  let estimatedCost = 0;
  for (const employee of data?.employees || []) {
    const uid = Number(employee.user_id);
    if (allowed && !allowed.has(uid)) continue;
    if (employee.excluded && !includeExcluded) continue;
    if (scheduledUserIds.has(uid)) employeesScheduled += 1;
    if (!employee.excluded) {
      estimatedCost += Number(employee.estimated_cost || 0);
    }
  }

  return {
    employeesScheduled,
    totalHours,
    totalDays,
    daysOnly,
    sortCount: roleCounts.sort,
    washCount: roleCounts.wash,
    weigherCount: roleCounts.weigher,
    foldCount: roleCounts.fold,
    ptWasherCount: roleCounts.pt_washer,
    ptSorterCount: roleCounts.pt_sorter,
    ptFolderCount: roleCounts.pt_folder,
    hdOperatorCount: roleCounts.hd_operator,
    hdFolderCount: roleCounts.hd_folder,
    nonRinseFolderCount: roleCounts.non_rinse_folder,
    attendantCount: roleCounts.attendant,
    washHours: roleHourTotals.wash_hours,
    sortHours: roleHourTotals.sort_hours,
    foldHours: roleHourTotals.fold_hours,
    ptWasherHours: roleHourTotals.pt_washer_hours,
    ptSorterHours: roleHourTotals.pt_sorter_hours,
    ptFolderHours: roleHourTotals.pt_folder_hours,
    estimatedCost,
  };
}

export function computeFilteredDaySummaries(data, { userIds = null, includeExcluded = false, entries = null } = {}) {
  const allowed = userIds ? new Set(userIds.map(Number)) : null;
  const sourceEntries = entries ?? data?.entries ?? [];
  const summaries = Array.from({ length: 7 }, () => ({
    people: 0,
    hours: 0,
    sort: 0,
    wash: 0,
    weigher: 0,
    fold: 0,
    pt_washer: 0,
    pt_sorter: 0,
    pt_folder: 0,
    hd_operator: 0,
    hd_folder: 0,
    non_rinse_folder: 0,
    attendant: 0,
    wash_hours: 0,
    sort_hours: 0,
    fold_hours: 0,
    pt_washer_hours: 0,
    pt_sorter_hours: 0,
    pt_folder_hours: 0,
  }));
  const peopleByDay = Array.from({ length: 7 }, () => new Set());
  const filteredEntries = [];

  for (const entry of sourceEntries) {
    const uid = Number(entry.user_id);
    if (allowed && !allowed.has(uid)) continue;
    const employee = (data?.employees || []).find((e) => Number(e.user_id) === uid);
    if (employee?.excluded && !includeExcluded) continue;

    filteredEntries.push(entry);
    const dow = Number(entry.day_of_week || 0);
    const hours = Number(entry.hours || 0);
    summaries[dow].hours += hours;
    peopleByDay[dow].add(uid);

    const roles = parseEntryRoles(entry);
    const countedRoles = roles.length ? roles : ["fold"];
    for (const role of countedRoles) {
      if (role in summaries[dow]) summaries[dow][role] += 1;
    }
  }

  const roleHoursByDay = allocateRoleHoursByDay(filteredEntries);
  return summaries.map((summary, dow) => {
    const roleHours = roleHoursByDay[dow] || {};
    return {
      ...summary,
      people: peopleByDay[dow].size,
      hours: summary.hours,
      wash_hours: roleHours.wash || 0,
      sort_hours: roleHours.sort || 0,
      fold_hours: roleHours.fold || 0,
      pt_washer_hours: roleHours.pt_washer || 0,
      pt_sorter_hours: roleHours.pt_sorter || 0,
      pt_folder_hours: roleHours.pt_folder || 0,
    };
  });
}

const DROP_TARGET_OVERLAY = "rgba(0, 151, 178, 0.08)";

/** Subtle grid-cell tint from shift roles — lighter than shift card fills. */
export function cellRoleBackground(entries) {
  if (!entries?.length) return null;

  const roleCounts = {};
  for (const entry of entries) {
    for (const roleKey of parseEntryRoles(entry)) {
      const key = ROLE_STYLES[roleKey] ? roleKey : "fold";
      roleCounts[key] = (roleCounts[key] || 0) + 1;
    }
  }

  const roles = sortRoles(
    Object.entries(roleCounts)
      .sort((a, b) => {
        if (b[1] !== a[1]) return b[1] - a[1];
        return (ROLE_ORDER_INDEX[a[0]] ?? 99) - (ROLE_ORDER_INDEX[b[0]] ?? 99);
      })
      .map(([key]) => key),
  );
  if (!roles.length) return null;

  if (roles.length === 1) {
    return (ROLE_STYLES[roles[0]] || ROLE_STYLES.fold).cellBg;
  }

  const colors = roles.map((key) => (ROLE_STYLES[key] || ROLE_STYLES.fold).cellBg);
  const step = 100 / colors.length;
  const stops = colors.map((color, i) => `${color} ${i * step}%, ${color} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(135deg, ${stops})`;
}

export function scheduleCellBackground({ entries, excluded, isDropTarget }) {
  if (excluded) return "#fafafa";
  const base = "#fafbfc";
  if (isDropTarget) {
    return `linear-gradient(${DROP_TARGET_OVERLAY}, ${DROP_TARGET_OVERLAY}), ${base}`;
  }
  const roleBg = cellRoleBackground(entries);
  if (roleBg) return roleBg;
  return base;
}
