import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { normalizeTimeHm } from "../datetime/scheduleTimeUi";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const ROLE_ORDER = [
  "wash",
  "sort",
  "weigher",
  "dry",
  "fold",
  "post_weigh",
  "pt_washer",
  "pt_sorter",
  "pt_folder",
  "hd_operator",
  "hd_folder",
  "non_rinse_folder",
  "attendant",
  "lint_cleaning",
  "floor_cleaning",
  "washer_cleaning",
  "drop_off_customer",
  "self_service",
];

/** Roles that show scheduled-hour totals in day/week summaries (PT kept separate). */
export const HOUR_TRACKED_ROLES = ["wash", "sort", "fold", "pt_washer", "pt_sorter", "pt_folder"];

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "wash", label: "Wash" },
  { value: "sort", label: "Sort" },
  { value: "weigher", label: "Weigher" },
  { value: "dry", label: "Dry" },
  { value: "fold", label: "Fold" },
  { value: "post_weigh", label: "Post-Weigh" },
  { value: "pt_washer", label: "PT Washer" },
  { value: "pt_sorter", label: "PT Sorter" },
  { value: "pt_folder", label: "PT Folder" },
  { value: "hd_operator", label: "HD Operator" },
  { value: "hd_folder", label: "HD Folder" },
  { value: "non_rinse_folder", label: "Non-Rinse Folder" },
  { value: "attendant", label: "Attendant" },
  { value: "lint_cleaning", label: "Lint Cleaning" },
  { value: "floor_cleaning", label: "Floor Cleaning" },
  { value: "washer_cleaning", label: "Washer Cleaning" },
  { value: "drop_off_customer", label: "Drop Off Customer" },
  { value: "self_service", label: "Self Service" },
];

const TASK_DEFAULT_ROLES = new Set([
  "lint_cleaning",
  "floor_cleaning",
  "washer_cleaning",
  "drop_off_customer",
  "self_service",
]);
const DEFAULT_ROLE_NAMES = Object.fromEntries(WEEKLY_SCHEDULE_ROLES.map((r) => [r.value, r.label]));

/** Fallback catalog when the week payload has not provided the org's role settings yet. */
export const DEFAULT_ROLE_CATALOG = WEEKLY_SCHEDULE_ROLES.map((role, index) => ({
  code: role.value,
  name: role.label,
  kind: TASK_DEFAULT_ROLES.has(role.value) ? "task" : "role",
  role_group: null,
  display_order: (index + 1) * 10,
  active: true,
  uses_time_slots: !TASK_DEFAULT_ROLES.has(role.value),
  remarks_enabled: TASK_DEFAULT_ROLES.has(role.value),
  builtin: true,
}));

const ROLE_ORDER_INDEX = Object.fromEntries(ROLE_ORDER.map((role, index) => [role, index]));
const HOUR_TRACKED_ROLE_SET = new Set(HOUR_TRACKED_ROLES);

let activeRoleCatalog = null;
let activeRoleIndex = null;
let activeRoleOrder = null;

/** Register the org's role settings (from the week payload) for labels, order, and pickers. */
export function setScheduleRoleCatalog(catalog) {
  if (!Array.isArray(catalog) || !catalog.length) {
    activeRoleCatalog = null;
    activeRoleIndex = null;
    activeRoleOrder = null;
    return;
  }
  activeRoleCatalog = [...catalog].sort(
    (a, b) => Number(a.display_order || 0) - Number(b.display_order || 0)
      || String(a.name || "").localeCompare(String(b.name || "")),
  );
  activeRoleIndex = Object.fromEntries(activeRoleCatalog.map((role) => [role.code, role]));
  activeRoleOrder = Object.fromEntries(activeRoleCatalog.map((role, index) => [role.code, index]));
}

export function scheduleRoleCatalog() {
  return activeRoleCatalog || DEFAULT_ROLE_CATALOG;
}

export function scheduleRoleInfo(code) {
  if (activeRoleIndex) return activeRoleIndex[code] || null;
  return DEFAULT_ROLE_CATALOG.find((role) => role.code === code) || null;
}

export function scheduleRoleLabel(code) {
  return scheduleRoleInfo(code)?.name || ROLE_STYLES[code]?.label || code;
}

/** Tasks are assigned by day with instructions only — no times, hours, or attendance window. */
export function isScheduleTask(code) {
  return scheduleRoleInfo(code)?.uses_time_slots === false;
}

function roleOrderIndex(code) {
  if (activeRoleOrder) return activeRoleOrder[code] ?? 999;
  return ROLE_ORDER_INDEX[code] ?? 99;
}

/** Short labels for tight grid cells and day headers. */
export const ROLE_COMPACT_LABELS = {
  wash: "Wash",
  sort: "Sort",
  weigher: "Weigh",
  dry: "Dry",
  fold: "Fold",
  post_weigh: "Post-Wt",
  pt_washer: "PT Wash",
  pt_sorter: "PT Sort",
  pt_folder: "PT Fold",
  hd_operator: "HD Op",
  hd_folder: "HD Fold",
  non_rinse_folder: "NR Fold",
  attendant: "Attend",
  lint_cleaning: "Lint",
  floor_cleaning: "Floor",
  washer_cleaning: "Washer Cl",
  drop_off_customer: "Drop Off",
  self_service: "Self Svc",
};

export function roleCompactLabel(roleKey) {
  const name = scheduleRoleInfo(roleKey)?.name;
  if (name && name !== DEFAULT_ROLE_NAMES[roleKey]) return name;
  return ROLE_COMPACT_LABELS[roleKey] || name || ROLE_STYLES[roleKey]?.label || roleKey;
}

export function sortRoles(roles) {
  return [...(roles || [])].sort((a, b) => roleOrderIndex(a) - roleOrderIndex(b));
}

/** Neutral styling for org-defined roles without a dedicated palette. */
export const CUSTOM_ROLE_STYLE = {
  accent: "#475569",
  bg: "#f1f5f9",
  hoverBg: "#e2e8f0",
  chipBg: "#f8fafc",
  cellBg: "#f8fafc",
  border: "rgba(71, 85, 105, 0.28)",
  label: "Role",
};

export function roleStyle(roleKey) {
  return ROLE_STYLES[roleKey] || CUSTOM_ROLE_STYLE;
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
  dry: {
    accent: "#b91c1c",
    bg: "#fee2e2",
    hoverBg: "#fecaca",
    chipBg: "#fef2f2",
    cellBg: "#fff7f7",
    border: "rgba(185, 28, 28, 0.28)",
    label: "Dry",
  },
  post_weigh: {
    accent: "#7c3aed",
    bg: "#ede9fe",
    hoverBg: "#ddd6fe",
    chipBg: "#f5f3ff",
    cellBg: "#faf8ff",
    border: "rgba(124, 58, 237, 0.28)",
    label: "Post-Weigh",
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
  lint_cleaning: {
    accent: "#57534e",
    bg: "#f5f5f4",
    hoverBg: "#e7e5e4",
    chipBg: "#fafaf9",
    cellBg: "#fafaf9",
    border: "rgba(87, 83, 78, 0.28)",
    label: "Lint Cleaning",
  },
  floor_cleaning: {
    accent: "#4d7c0f",
    bg: "#ecfccb",
    hoverBg: "#d9f99d",
    chipBg: "#f7fee7",
    cellBg: "#fbfef3",
    border: "rgba(77, 124, 15, 0.28)",
    label: "Floor Cleaning",
  },
  washer_cleaning: {
    accent: "#0e7490",
    bg: "#cffafe",
    hoverBg: "#a5f3fc",
    chipBg: "#ecfeff",
    cellBg: "#f5feff",
    border: "rgba(14, 116, 144, 0.28)",
    label: "Washer Cleaning",
  },
  drop_off_customer: {
    accent: "#9d174d",
    bg: "#fce7f3",
    hoverBg: "#fbcfe8",
    chipBg: "#fdf2f8",
    cellBg: "#fff5fa",
    border: "rgba(157, 23, 77, 0.28)",
    label: "Drop Off Customer",
  },
  self_service: {
    accent: "#a16207",
    bg: "#fef9c3",
    hoverBg: "#fef08a",
    chipBg: "#fefce8",
    cellBg: "#fffef2",
    border: "rgba(161, 98, 7, 0.28)",
    label: "Self Service",
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
  if (Array.isArray(entry?.roles) && (entry.roles.length || entry.role === "")) {
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
 * Role assignments inside a shift. Each has its own time range; `full_shift` ones span the shift.
 * Older payloads without `assignments` treat every role as covering the whole shift.
 */
export function entryRoleAssignments(entry) {
  if (Array.isArray(entry?.assignments) && entry.assignments.length) {
    return entry.assignments.filter((a) => a?.role);
  }
  return parseEntryRoles(entry).map((role) => ({
    role,
    start_time: entry?.start_time || null,
    end_time: entry?.end_time || null,
    remarks: null,
    full_shift: true,
  }));
}

/** Place a wall-clock range on the shift timeline (shift end may run past midnight). */
export function placeOnShiftTimeline(segStart, segEnd, shiftStart) {
  const start = segStart < shiftStart ? segStart + 24 * 60 : segStart;
  let end = segEnd;
  while (end <= start) end += 24 * 60;
  return { start, end };
}

/**
 * Paid scheduled hours per `${user_id}|${day_of_week}`.
 * Overlapping shifts for the same employee/day count their combined span once (largest break).
 */
export function scheduledHoursByUserDay(entries) {
  const out = new Map();
  const timed = new Map();
  for (const entry of entries || []) {
    const key = `${Number(entry.user_id)}|${Number(entry.day_of_week || 0)}`;
    const hours = Math.max(0, Number(entry.hours || 0));
    const interval = hours > 0 ? entryIntervalMinutes(entry) : null;
    if (!interval) {
      out.set(key, (out.get(key) || 0) + hours);
      continue;
    }
    const list = timed.get(key) || [];
    list.push({ start: interval.start, end: interval.end, breakMin: interval.breakMin, hours });
    timed.set(key, list);
  }
  for (const [key, items] of timed.entries()) {
    items.sort((a, b) => a.start - b.start || a.end - b.end);
    const clusters = [];
    for (const item of items) {
      const last = clusters[clusters.length - 1];
      if (last && item.start < Math.max(...last.map((c) => c.end))) last.push(item);
      else clusters.push([item]);
    }
    let total = out.get(key) || 0;
    for (const cluster of clusters) {
      if (cluster.length === 1) {
        total += cluster[0].hours;
        continue;
      }
      const span = Math.max(...cluster.map((c) => c.end)) - cluster[0].start;
      total += Math.max(0, span - Math.max(...cluster.map((c) => c.breakMin))) / 60;
    }
    out.set(key, total);
  }
  return out;
}

/**
 * Allocate scheduled hours to hour-tracked roles.
 * Each role assignment counts over its own range inside the shift; concurrent hour-tracked
 * assignments split that time evenly and the shift break is pro-rated.
 * Overlapping time for the same employee/day/role across entries is merged (no double-count).
 */
export function allocateRoleHoursByDay(entries) {
  const byDay = Array.from({ length: 7 }, () => {
    const hours = {};
    for (const role of HOUR_TRACKED_ROLES) hours[role] = 0;
    return hours;
  });

  for (const [key, hours] of roleHourBuckets(entries, (role) => HOUR_TRACKED_ROLE_SET.has(role))) {
    const [, dow, role] = key.split("|");
    byDay[Number(dow)][role] += hours;
  }

  return byDay.map((day) => {
    const out = {};
    for (const role of HOUR_TRACKED_ROLES) {
      out[role] = Math.round((day[role] || 0) * 10) / 10;
    }
    return out;
  });
}

export const ROLE_HOURS_EXPLANATION =
  "Employee hours: shift time minus the break; overlapping shifts for the same person and day count once. " +
  "Role hours: when an employee holds several roles at the same time, that time is split evenly between them, " +
  "and the break is deducted from each role in proportion to its share of the shift. Shift time without a role " +
  "is not attributed to any role. Tasks never count toward hours.";

/**
 * Hours per employee and per timed role for the summaries above the time-and-role view.
 * Employee hours use the scheduled-hours rules (break deducted, overlapping shifts once).
 * Role hours use the role allocation rules; tasks never count.
 */
export function summarizeScheduleHours(entries, employeesById = new Map()) {
  const employeeHours = new Map();
  for (const [key, hours] of scheduledHoursByUserDay(entries)) {
    const uid = Number(key.split("|")[0]);
    employeeHours.set(uid, (employeeHours.get(uid) || 0) + hours);
  }
  const employees = [...employeeHours.entries()]
    .map(([uid, hours]) => ({
      user_id: uid,
      name: employeesById.get(uid)?.display_name || `User ${uid}`,
      hours: Math.round(hours * 100) / 100,
    }))
    .sort((a, b) => b.hours - a.hours || a.name.localeCompare(b.name));
  const totalHours = employees.reduce((sum, row) => sum + row.hours, 0);

  const roleHours = new Map();
  for (const [key, hours] of roleHourBuckets(entries, (role) => !isScheduleTask(role))) {
    const role = key.split("|")[2];
    roleHours.set(role, (roleHours.get(role) || 0) + hours);
  }
  const roleUsers = new Map();
  for (const entry of entries || []) {
    for (const a of entryRoleAssignments(entry)) {
      if (isScheduleTask(a.role)) continue;
      const set = roleUsers.get(a.role) || new Set();
      set.add(Number(entry.user_id));
      roleUsers.set(a.role, set);
    }
  }
  const roles = sortRoles([...roleUsers.keys()]).map((role) => ({
    role,
    label: scheduleRoleLabel(role),
    hours: Math.round((roleHours.get(role) || 0) * 100) / 100,
    employees: roleUsers.get(role).size,
  }));
  const roleTotal = roles.reduce((sum, row) => sum + row.hours, 0);
  return {
    employees,
    totalHours: Math.round(totalHours * 100) / 100,
    roles,
    roleTotal: Math.round(roleTotal * 100) / 100,
    distinctEmployees: employees.length,
    unassignedHours: Math.max(0, Math.round((totalHours - roleTotal) * 100) / 100),
  };
}

/** Allocated hours keyed `${user_id}|${day}|${role}` for roles passing `includeRole`. */
function roleHourBuckets(entries, includeRole) {
  /** @type {Map<string, Array<{start:number,end:number,hours:number,direct?:boolean}>>} */
  const buckets = new Map();
  const push = (key, item) => {
    const list = buckets.get(key) || [];
    list.push(item);
    buckets.set(key, list);
  };

  for (const entry of entries || []) {
    const uid = Number(entry.user_id);
    const dow = Number(entry.day_of_week || 0);
    if (!Number.isInteger(dow) || dow < 0 || dow > 6) continue;

    const assignments = entryRoleAssignments(entry).filter((a) => includeRole(a.role));
    if (!assignments.length) continue;

    const interval = entryIntervalMinutes(entry);
    if (!interval) {
      const segmentHours = Math.max(0, Number(entry.hours || 0));
      if (segmentHours <= 0) continue;
      const roles = [...new Set(assignments.map((a) => a.role))];
      for (const role of roles) {
        push(`${uid}|${dow}|${role}`, { start: 0, end: 0, hours: segmentHours / roles.length, direct: true });
      }
      continue;
    }

    const wall = interval.end - interval.start;
    if (interval.hours <= 0 || wall <= 0) continue;
    const paidRatio = (interval.hours * 60) / wall;
    const ranges = [];
    for (const a of assignments) {
      const segStart = parseTimeToMinutes(normalizeTimeHm(a.start_time));
      const segEnd = parseTimeToMinutes(normalizeTimeHm(a.end_time));
      if (a.full_shift !== false || segStart == null || segEnd == null) {
        ranges.push({ role: a.role, start: interval.start, end: interval.end });
        continue;
      }
      const placed = placeOnShiftTimeline(segStart, segEnd, interval.start);
      const start = Math.max(placed.start, interval.start);
      const end = Math.min(placed.end, interval.end);
      if (end > start) ranges.push({ role: a.role, start, end });
    }
    const bounds = [...new Set(ranges.flatMap((r) => [r.start, r.end]))].sort((x, y) => x - y);
    for (let i = 0; i < bounds.length - 1; i += 1) {
      const left = bounds[i];
      const right = bounds[i + 1];
      const active = [...new Set(ranges.filter((r) => r.start <= left && r.end >= right).map((r) => r.role))];
      if (!active.length) continue;
      const share = (((right - left) / 60) * paidRatio) / active.length;
      for (const role of active) push(`${uid}|${dow}|${role}`, { start: left, end: right, hours: share });
    }
  }

  const out = new Map();
  for (const [key, list] of buckets.entries()) {
    const timed = list.filter((item) => !item.direct);
    const direct = list.filter((item) => item.direct);
    let hours = direct.reduce((sum, item) => sum + item.hours, 0);
    if (timed.length) {
      if (hasOverlappingIntervals(timed)) {
        const span = timed.reduce((sum, item) => sum + (item.end - item.start) / 60, 0);
        const weight = span > 0 ? timed.reduce((sum, item) => sum + item.hours, 0) / span : 1;
        hours += mergeIntervalHours(timed) * Math.min(1, weight || 1);
      } else {
        hours += timed.reduce((sum, item) => sum + item.hours, 0);
      }
    }
    out.set(key, hours);
  }
  return out;
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
  return roleStyle(roles[0] || "fold");
}

function blendRoleColors(colors, direction = "135deg") {
  if (!colors.length) return ROLE_STYLES.fold.bg;
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map((color, i) => `${color} ${i * step}%, ${color} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(${direction}, ${stops})`;
}

export const NO_ROLE_LABEL = "No role";

const NO_ROLE_CARD_STYLE = {
  bg: "#f8fafc",
  hoverBg: "#f1f5f9",
  border: "#cbd5e1",
  accent: "#64748b",
  stripe: "#94a3b8",
  multiRole: false,
};

/** Shift card fill, border, and stripe styling from one or more roles. */
export function entryRoleCardStyle(entryOrRoles) {
  const roles = Array.isArray(entryOrRoles) ? sortRoles(entryOrRoles) : parseEntryRoles(entryOrRoles);
  if (!roles.length) return { ...NO_ROLE_CARD_STYLE };
  const keys = roles;
  const styles = keys.map((key) => roleStyle(key));
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
  const colors = keys.map((k) => roleStyle(k).accent);
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map((c, i) => `${c} ${i * step}%, ${c} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(180deg, ${stops})`;
}

export function roleLabels(roles) {
  return sortRoles(roles).map((r) => scheduleRoleLabel(r)).join(" · ");
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
    label: scheduleRoleLabel(key),
    count: counts[key],
    style: roleStyle(key),
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
    return roleOrderIndex(a[0]) - roleOrderIndex(b[0]);
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

  for (const hours of scheduledHoursByUserDay(filteredEntries).values()) {
    totalHours += hours;
  }

  for (const entry of filteredEntries) {
    const uid = Number(entry.user_id);
    scheduledUserIds.add(uid);
    totalDays += 1;
    for (const role of parseEntryRoles(entry)) {
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
    peopleByDay[dow].add(uid);

    for (const role of parseEntryRoles(entry)) {
      if (role in summaries[dow]) summaries[dow][role] += 1;
    }
  }

  for (const [key, hours] of scheduledHoursByUserDay(filteredEntries).entries()) {
    const dow = Number(key.split("|")[1]);
    if (summaries[dow]) summaries[dow].hours += hours;
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
      roleCounts[roleKey] = (roleCounts[roleKey] || 0) + 1;
    }
  }

  const roles = sortRoles(
    Object.entries(roleCounts)
      .sort((a, b) => {
        if (b[1] !== a[1]) return b[1] - a[1];
        return roleOrderIndex(a[0]) - roleOrderIndex(b[0]);
      })
      .map(([key]) => key),
  );
  if (!roles.length) return null;

  if (roles.length === 1) {
    return roleStyle(roles[0]).cellBg;
  }

  const colors = roles.map((key) => roleStyle(key).cellBg);
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
