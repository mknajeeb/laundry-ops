import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const ROLE_ORDER = ["wash", "sort", "weigher", "fold", "hd_operator", "hd_folder"];

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "wash", label: "Wash" },
  { value: "sort", label: "Sort" },
  { value: "weigher", label: "Weigher" },
  { value: "fold", label: "Fold" },
  { value: "hd_operator", label: "HD Operator" },
  { value: "hd_folder", label: "HD Folder" },
];

const ROLE_ORDER_INDEX = Object.fromEntries(ROLE_ORDER.map((role, index) => [role, index]));

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

export function parseEntryRoles(entry) {
  let roles;
  if (Array.isArray(entry?.roles) && entry.roles.length) {
    roles = entry.roles.map((r) => (r === "folder" ? "fold" : r));
  } else {
    const raw = String(entry?.role || "fold");
    roles = raw
      .split(",")
      .map((r) => r.trim())
      .map((r) => (r === "folder" ? "fold" : r))
      .filter(Boolean);
  }
  return sortRoles(roles);
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
  let sortCount = 0;
  let washCount = 0;
  let weigherCount = 0;
  let foldCount = 0;
  let hdOperatorCount = 0;
  let hdFolderCount = 0;
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
      if (role === "sort") sortCount += 1;
      else if (role === "wash") washCount += 1;
      else if (role === "weigher") weigherCount += 1;
      else if (role === "fold") foldCount += 1;
      else if (role === "hd_operator") hdOperatorCount += 1;
      else if (role === "hd_folder") hdFolderCount += 1;
    }
  }

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
    sortCount,
    washCount,
    weigherCount,
    foldCount,
    hdOperatorCount,
    hdFolderCount,
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
    hd_operator: 0,
    hd_folder: 0,
  }));
  const peopleByDay = Array.from({ length: 7 }, () => new Set());

  for (const entry of sourceEntries) {
    const uid = Number(entry.user_id);
    if (allowed && !allowed.has(uid)) continue;
    const employee = (data?.employees || []).find((e) => Number(e.user_id) === uid);
    if (employee?.excluded && !includeExcluded) continue;

    const dow = Number(entry.day_of_week || 0);
    const hours = Number(entry.hours || 0);
    summaries[dow].hours += hours;
    peopleByDay[dow].add(uid);

    const roles = parseEntryRoles(entry);
    const countedRoles = roles.length ? roles : ["fold"];
    for (const role of countedRoles) {
      if (role === "sort") summaries[dow].sort += 1;
      else if (role === "wash") summaries[dow].wash += 1;
      else if (role === "weigher") summaries[dow].weigher += 1;
      else if (role === "fold") summaries[dow].fold += 1;
      else if (role === "hd_operator") summaries[dow].hd_operator += 1;
      else if (role === "hd_folder") summaries[dow].hd_folder += 1;
    }
  }

  return summaries.map((summary, dow) => ({
    ...summary,
    people: peopleByDay[dow].size,
    hours: summary.hours,
  }));
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
