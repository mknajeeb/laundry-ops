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

let activeRoleGroups = [];

/** Register the org's operational groups (built-in plus org-created, in display order). */
export function setScheduleRoleGroups(groups) {
  activeRoleGroups = Array.isArray(groups)
    ? [...groups].sort((a, b) => Number(a.display_order || 0) - Number(b.display_order || 0))
    : [];
}

export function scheduleRoleGroups() {
  return activeRoleGroups;
}

export const UNGROUPED_LABEL = "Other";

/**
 * Split role codes into operational groups: groups in display order, roles in catalog order
 * inside each, ungrouped roles last.
 */
export function groupRoleCodes(codes) {
  const order = new Map(activeRoleGroups.map((group, index) => [group.code, index]));
  const buckets = new Map();
  for (const code of sortRoles(codes)) {
    const groupCode = scheduleRoleInfo(code)?.role_group || "";
    const key = order.has(groupCode) ? groupCode : "";
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(code);
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => (order.has(a) ? order.get(a) : 9999) - (order.has(b) ? order.get(b) : 9999))
    .map(([code, roles]) => {
      const group = activeRoleGroups.find((g) => g.code === code);
      return { code, label: group?.label || UNGROUPED_LABEL, active: group?.active !== false, roles };
    });
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

const DAY_MINUTES = 24 * 60;

/** Planned break windows on a shift: [{start_time, end_time}] (HH:MM); invalid or zero-length slots are dropped. */
export function parseBreakSlots(raw) {
  let list = raw;
  if (typeof raw === "string") {
    try {
      list = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const item of list) {
    const start = normalizeTimeHm(item?.start_time);
    const end = normalizeTimeHm(item?.end_time);
    if (start && end && start !== end) out.push({ start_time: start, end_time: end });
  }
  return out;
}

export function entryBreakSlots(entry) {
  return parseBreakSlots(entry?.break_slots);
}

/** Shift start/end in minutes on its start day's timeline; overnight ends run past midnight. */
export function entryShiftInterval(entry) {
  const start = parseTimeToMinutes(normalizeTimeHm(entry?.start_time));
  let end = parseTimeToMinutes(normalizeTimeHm(entry?.end_time));
  if (start == null || end == null) return null;
  if (end <= start) end += DAY_MINUTES;
  return { start, end };
}

/** Break slots placed on the shift timeline and clipped to the shift. */
export function placedBreakRanges(entry, shift = entryShiftInterval(entry)) {
  if (!shift) return [];
  const out = [];
  for (const slot of entryBreakSlots(entry)) {
    const segStart = parseTimeToMinutes(slot.start_time);
    const segEnd = parseTimeToMinutes(slot.end_time);
    if (segStart == null || segEnd == null) continue;
    const placed = placeOnShiftTimeline(segStart, segEnd, shift.start);
    const start = Math.max(placed.start, shift.start);
    const end = Math.min(placed.end, shift.end);
    if (end > start) out.push({ start, end });
  }
  return out;
}

export const MAX_BREAK_SLOTS = 6;

function clockLabel(minutes) {
  const h = Math.floor(minutes / 60) % 24;
  const m = minutes % 60;
  return `${h % 12 || 12}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h < 12 ? "AM" : "PM"}`;
}

/** Same rules as the server: each break inside the shift (overnight included) and no overlaps. */
export function validateBreakSlots(startTime, endTime, slots) {
  const list = slots || [];
  if (list.length > MAX_BREAK_SLOTS) return `At most ${MAX_BREAK_SLOTS} breaks per shift`;
  const shift = entryShiftInterval({ start_time: startTime, end_time: endTime });
  const placed = [];
  for (let i = 0; i < list.length; i += 1) {
    const start = parseTimeToMinutes(normalizeTimeHm(list[i]?.start_time));
    const end = parseTimeToMinutes(normalizeTimeHm(list[i]?.end_time));
    if (start == null || end == null) return `Break ${i + 1}: start and end time are required`;
    if (start === end) return `Break ${i + 1}: end time must be after the start time`;
    if (!shift) return "Timed breaks need the shift start and end times";
    const label = `Break ${clockLabel(start)}–${clockLabel(end)}`;
    const window = placeOnShiftTimeline(start, end, shift.start);
    if (window.end > shift.end) return `${label} must be within the shift`;
    const clash = placed.find((other) => window.start < other.end && other.start < window.end);
    if (clash) return `${label} overlaps ${clash.label}`;
    placed.push({ ...window, label });
  }
  return null;
}

let breakSlotSeq = 0;
/** Editable break row with a stable key for the shift dialog. */
export function makeBreakSlot(partial = {}) {
  breakSlotSeq += 1;
  return { id: `b${breakSlotSeq}`, start_time: "", end_time: "", ...partial };
}

/** "12:00 PM–12:30 PM" for a stored break slot. */
export function formatBreakSlot(slot) {
  const start = parseTimeToMinutes(normalizeTimeHm(slot?.start_time));
  const end = parseTimeToMinutes(normalizeTimeHm(slot?.end_time));
  if (start == null || end == null) return "";
  return `${clockLabel(start)}–${clockLabel(end)}`;
}

/** Per-break display lines: "Break 12 PM–12:30 PM" for timed breaks, "Break 30 min · Not scheduled" otherwise. */
export function entryBreakLines(entry) {
  const lines = entryBreakSlots(entry).map((slot) => `Break ${formatBreakSlot(slot)}`);
  const unscheduled = entryBreakBreakdown(entry).unscheduledBreakMinutes;
  if (unscheduled > 0) lines.push(`Break ${unscheduled} min \u00b7 Not scheduled`);
  return lines;
}

function mergeRanges(ranges) {
  const merged = [];
  for (const range of [...ranges].sort((a, b) => a.start - b.start || a.end - b.end)) {
    const last = merged[merged.length - 1];
    if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
    else merged.push({ start: range.start, end: range.end });
  }
  return merged;
}

function rangesMinutes(ranges) {
  return ranges.reduce((sum, r) => sum + Math.max(0, r.end - r.start), 0);
}

/**
 * Minutes for one shift. `break_minutes` is the total planned deduction; timed slots are the part of
 * it with a known time and the rest is duration-only ("Not scheduled"). A slot never adds to an
 * existing duration-only break: the deduction is the larger of the two.
 */
export function entryBreakBreakdown(entry) {
  const shift = entryShiftInterval(entry);
  if (!shift) return { grossMinutes: 0, breakMinutes: 0, timedBreakMinutes: 0, unscheduledBreakMinutes: 0 };
  const gross = shift.end - shift.start;
  const timed = rangesMinutes(mergeRanges(placedBreakRanges(entry, shift)));
  const total = Math.min(gross, Math.max(Math.max(0, Number(entry?.break_minutes || 0)), timed));
  const timedPart = Math.min(timed, total);
  return { grossMinutes: gross, breakMinutes: total, timedBreakMinutes: timedPart, unscheduledBreakMinutes: total - timedPart };
}

function notTask(role) {
  return !isScheduleTask(role);
}

/**
 * One employee's planned day (all entries share user and day) — the single calculation behind
 * net hours, role hours, the hourly matrix, and the breaks view.
 *
 * Overlapping shifts merge into one span, so their time is counted once. A timed break from any of
 * those shifts takes the person off every role for that time. The duration-only part of a merged span
 * is its largest declared break less the timed break already placed there; it is deducted from net
 * hours but never given an hourly position. Worked pieces carry the roles active in them, and
 * simultaneous roles share a piece evenly. Tasks never count.
 */
export function employeeDayTimeline(entries, { includeRole = notTask } = {}) {
  let directHours = 0;
  const directRoleHours = {};
  const shifts = [];
  for (const entry of entries || []) {
    if (entry?.hours != null && Number(entry.hours || 0) <= 0) continue;
    const shift = entryShiftInterval(entry);
    if (!shift) {
      const hours = Math.max(0, Number(entry?.hours || 0));
      if (hours <= 0) continue;
      directHours += hours;
      const roles = [...new Set(entryRoleAssignments(entry).map((a) => a.role).filter((r) => r && includeRole(r)))];
      for (const role of roles) directRoleHours[role] = (directRoleHours[role] || 0) + hours / roles.length;
      continue;
    }
    shifts.push({ ...shift, entry });
  }
  shifts.sort((a, b) => a.start - b.start || a.end - b.end);

  const clusters = [];
  for (const shift of shifts) {
    const last = clusters[clusters.length - 1];
    if (last && shift.start < last.end) {
      last.end = Math.max(last.end, shift.end);
      last.shifts.push(shift);
    } else {
      clusters.push({ start: shift.start, end: shift.end, shifts: [shift] });
    }
  }

  const segments = [];
  for (const shift of shifts) {
    for (const assignment of entryRoleAssignments(shift.entry)) {
      if (!assignment?.role || !includeRole(assignment.role)) continue;
      let { start, end } = shift;
      const segStart = parseTimeToMinutes(normalizeTimeHm(assignment.start_time));
      const segEnd = parseTimeToMinutes(normalizeTimeHm(assignment.end_time));
      if (assignment.full_shift === false && segStart != null && segEnd != null) {
        const placed = placeOnShiftTimeline(segStart, segEnd, shift.start);
        start = Math.max(placed.start, shift.start);
        end = Math.min(placed.end, shift.end);
      }
      if (end > start) segments.push({ role: assignment.role, start, end, entry: shift.entry });
    }
  }

  let gross = 0;
  let timed = 0;
  let unscheduled = 0;
  const breakRanges = [];
  const unscheduledEntries = [];
  for (const cluster of clusters) {
    const span = cluster.end - cluster.start;
    const perShift = cluster.shifts.map((shift) => ({ shift, ranges: mergeRanges(placedBreakRanges(shift.entry, shift)) }));
    const ranges = mergeRanges(perShift.flatMap((item) => item.ranges));
    const clusterTimed = rangesMinutes(ranges);
    let declared = 0;
    let declaredEntry = null;
    for (const { shift, ranges: own } of perShift) {
      const value = Math.max(Math.max(0, Number(shift.entry?.break_minutes || 0)), rangesMinutes(own));
      if (value > declared) {
        declared = value;
        declaredEntry = shift.entry;
      }
    }
    const deduction = Math.min(span, Math.max(clusterTimed, declared));
    gross += span;
    timed += clusterTimed;
    unscheduled += deduction - clusterTimed;
    if (deduction > clusterTimed) {
      unscheduledEntries.push({ entry: declaredEntry, minutes: deduction - clusterTimed });
    }
    for (const range of ranges) {
      const owner = perShift.find((item) => item.ranges.some((r) => r.start < range.end && range.start < r.end));
      const roles = sortRoles([
        ...new Set(segments.filter((s) => s.start < range.end && range.start < s.end).map((s) => s.role)),
      ]);
      breakRanges.push({ ...range, entry: owner?.shift.entry || cluster.shifts[0].entry, roles });
    }
  }

  const points = [
    ...new Set([
      ...shifts.flatMap((s) => [s.start, s.end]),
      ...segments.flatMap((s) => [s.start, s.end]),
      ...breakRanges.flatMap((r) => [r.start, r.end]),
    ]),
  ].sort((a, b) => a - b);
  const pieces = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const start = points[i];
    const end = points[i + 1];
    const shift = shifts.find((s) => s.start <= start && s.end >= end);
    if (!shift) continue;
    const covering = segments.filter((s) => s.start <= start && s.end >= end);
    pieces.push({
      start,
      end,
      roles: sortRoles([...new Set(covering.map((s) => s.role))]),
      onBreak: breakRanges.some((r) => r.start <= start && r.end >= end),
      entryByRole: Object.fromEntries(covering.map((s) => [s.role, s.entry])),
      entry: shift.entry,
    });
  }

  const breakMinutes = timed + unscheduled;
  return {
    grossHours: gross / 60 + directHours,
    breakHours: breakMinutes / 60,
    timedBreakHours: timed / 60,
    unscheduledBreakHours: unscheduled / 60,
    netHours: (gross - breakMinutes) / 60 + directHours,
    shifts,
    pieces,
    breakRanges,
    unscheduledEntries,
    directHours,
    directRoleHours,
  };
}

/** Day timelines keyed `${user_id}|${day_of_week}` (every user-day with an entry has a key). */
export function scheduleDayTimelines(entries, options) {
  const groups = new Map();
  for (const entry of entries || []) {
    const key = `${Number(entry.user_id)}|${Number(entry.day_of_week || 0)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  const out = new Map();
  for (const [key, group] of groups) {
    const [uid, dow] = key.split("|").map(Number);
    out.set(key, { userId: uid, dow, ...employeeDayTimeline(group, options) });
  }
  return out;
}

/** Role hours from one day timeline: worked pieces off break, split evenly between simultaneous roles. */
export function timelineRoleHours(timeline) {
  const out = new Map();
  for (const piece of timeline.pieces) {
    if (piece.onBreak || !piece.roles.length) continue;
    const share = (piece.end - piece.start) / 60 / piece.roles.length;
    for (const role of piece.roles) out.set(role, (out.get(role) || 0) + share);
  }
  for (const [role, hours] of Object.entries(timeline.directRoleHours || {})) {
    out.set(role, (out.get(role) || 0) + hours);
  }
  return out;
}

/** Shift time that is neither on a timed break nor in any role. */
function timelineNoRoleHours(timeline) {
  const pieces = timeline.pieces
    .filter((piece) => !piece.onBreak && !piece.roles.length)
    .reduce((sum, piece) => sum + (piece.end - piece.start) / 60, 0);
  const directRoles = Object.values(timeline.directRoleHours || {}).reduce((sum, h) => sum + h, 0);
  return pieces + Math.max(0, (timeline.directHours || 0) - directRoles);
}

/** Gross, break (timed + duration-only), and net hours keyed `${user_id}|${day_of_week}`. */
export function scheduledHoursBreakdownByUserDay(entries) {
  const out = new Map();
  for (const [key, t] of scheduleDayTimelines(entries)) {
    out.set(key, {
      gross: t.grossHours,
      break: t.breakHours,
      timedBreak: t.timedBreakHours,
      unscheduledBreak: t.unscheduledBreakHours,
      net: t.netHours,
    });
  }
  return out;
}

/** Net scheduled hours per `${user_id}|${day_of_week}` (gross minus timed and duration-only breaks). */
export function scheduledHoursByUserDay(entries) {
  const out = new Map();
  for (const [key, parts] of scheduledHoursBreakdownByUserDay(entries)) out.set(key, parts.net);
  return out;
}

/** Hour-tracked role hours per day from the shared day timeline. */
export function allocateRoleHoursByDay(entries) {
  const byDay = Array.from({ length: 7 }, () => {
    const hours = {};
    for (const role of HOUR_TRACKED_ROLES) hours[role] = 0;
    return hours;
  });
  for (const timeline of scheduleDayTimelines(entries).values()) {
    if (timeline.dow < 0 || timeline.dow > 6) continue;
    for (const [role, hours] of timelineRoleHours(timeline)) {
      if (HOUR_TRACKED_ROLE_SET.has(role)) byDay[timeline.dow][role] += hours;
    }
  }
  return byDay.map((day) => {
    const out = {};
    for (const role of HOUR_TRACKED_ROLES) out[role] = Math.round((day[role] || 0) * 10) / 10;
    return out;
  });
}

export const ROLE_HOURS_EXPLANATION =
  "Gross hours: shift time; overlapping shifts for the same person and day count once. Break hours: timed " +
  "breaks plus breaks without a time (\u201cNot scheduled\u201d). Net hours = gross \u2212 breaks. Role hours: timed " +
  "breaks are removed first, then time an employee spends on several roles at once is split evenly between " +
  "them. Breaks without a time are not placed in any hour or role, so they appear as a separate deduction. " +
  "Tasks never count toward hours.";

function round2(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

/**
 * Hours per employee (gross, break, net) and per timed role for the summaries, all from the shared
 * day timeline: role hours + shift time without a role − breaks without a time = net hours.
 */
export function summarizeScheduleHours(entries, employeesById = new Map()) {
  const perEmployee = new Map();
  const roleHours = new Map();
  let grossHours = 0;
  let timedBreakHours = 0;
  let unscheduledBreakHours = 0;
  let netHours = 0;
  let noRoleHours = 0;
  for (const timeline of scheduleDayTimelines(entries).values()) {
    const row = perEmployee.get(timeline.userId) || { gross: 0, break: 0, net: 0 };
    row.gross += timeline.grossHours;
    row.break += timeline.breakHours;
    row.net += timeline.netHours;
    perEmployee.set(timeline.userId, row);
    grossHours += timeline.grossHours;
    timedBreakHours += timeline.timedBreakHours;
    unscheduledBreakHours += timeline.unscheduledBreakHours;
    netHours += timeline.netHours;
    noRoleHours += timelineNoRoleHours(timeline);
    for (const [role, hours] of timelineRoleHours(timeline)) roleHours.set(role, (roleHours.get(role) || 0) + hours);
  }
  const employees = [...perEmployee.entries()]
    .map(([uid, row]) => ({
      user_id: uid,
      name: employeesById.get(uid)?.display_name || `User ${uid}`,
      hours: round2(row.net),
      grossHours: round2(row.gross),
      breakHours: round2(row.break),
    }))
    .sort((a, b) => b.hours - a.hours || a.name.localeCompare(b.name));

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
    hours: round2(roleHours.get(role) || 0),
    employees: roleUsers.get(role).size,
  }));
  const roleTotal = round2(roles.reduce((sum, row) => sum + row.hours, 0));
  return {
    employees,
    totalHours: round2(netHours),
    grossHours: round2(grossHours),
    breakHours: round2(timedBreakHours + unscheduledBreakHours),
    timedBreakHours: round2(timedBreakHours),
    unscheduledBreakHours: round2(unscheduledBreakHours),
    roles,
    roleTotal,
    distinctEmployees: employees.length,
    unassignedHours: round2(noRoleHours),
    unassignedLabel: "Shift time without a role",
  };
}

/**
 * Summaries limited to selected roles (null = all): employees holding a selected role, and role rows for
 * the selected roles only. Their other worked time is shown separately so totals still reconcile.
 */
export function summarizeSelectedRoleHours(entries, employeesById = new Map(), roles = null) {
  if (!Array.isArray(roles)) return summarizeScheduleHours(entries, employeesById);
  const selected = new Set(roles);
  const scoped = (entries || []).filter((entry) => entryRoleAssignments(entry).some((a) => selected.has(a.role)));
  const summary = summarizeScheduleHours(scoped, employeesById);
  const roleRows = summary.roles.filter((row) => selected.has(row.role));
  const roleTotal = round2(roleRows.reduce((sum, row) => sum + row.hours, 0));
  return {
    ...summary,
    roles: roleRows,
    roleTotal,
    unassignedHours: Math.max(0, round2(summary.grossHours - summary.timedBreakHours - roleTotal)),
    unassignedLabel: "Shift time in other roles or without a role",
  };
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

const EMPTY_EMPLOYEE_TOTALS = Object.freeze({
  total_hours: 0,
  gross_hours: 0,
  break_hours: 0,
  timed_break_hours: 0,
  unscheduled_break_hours: 0,
  scheduled_days: 0,
  estimated_cost: 0,
});

/**
 * Net hours (`total_hours`), gross and break hours, distinct days, and estimated cost per employee
 * from the given entries, using the shared day timeline (overlapping shifts on a day counted once).
 */
export function employeeTotalsFromEntries(entries, employees = []) {
  const rates = new Map(
    (employees || []).map((e) => [Number(e.user_id), Math.max(0, Number(e.default_hourly_rate || 0))]),
  );
  const out = new Map();
  for (const [key, parts] of scheduledHoursBreakdownByUserDay(entries)) {
    const uid = Number(key.split("|")[0]);
    const row = out.get(uid) || { ...EMPTY_EMPLOYEE_TOTALS };
    row.total_hours = round2(row.total_hours + parts.net);
    row.gross_hours = round2(row.gross_hours + parts.gross);
    row.break_hours = round2(row.break_hours + parts.break);
    row.timed_break_hours = round2(row.timed_break_hours + parts.timedBreak);
    row.unscheduled_break_hours = round2(row.unscheduled_break_hours + parts.unscheduledBreak);
    row.scheduled_days += 1;
    row.estimated_cost = round2(row.estimated_cost + round2(parts.net * (rates.get(uid) || 0)));
    out.set(uid, row);
  }
  return out;
}

export function formatHours(hours) {
  return `${round2(hours)}`;
}

/** "Gross 8 · Break 0.5 · Net 7.5" */
export function formatHoursBreakdown({ gross = 0, breakHours = 0, net = 0 } = {}) {
  return `Gross ${formatHours(gross)} \u00b7 Break ${formatHours(breakHours)} \u00b7 Net ${formatHours(net)}`;
}

/**
 * Employee rows whose hours, days, and cost match the entries on screen. The week payload's
 * totals cover every shift category, so they disagree with a category tab, role, or day filter.
 */
export function withDisplayedTotals(employees, entries) {
  const totals = employeeTotalsFromEntries(entries, employees);
  return (employees || []).map((employee) => ({
    ...employee,
    ...(totals.get(Number(employee.user_id)) || EMPTY_EMPLOYEE_TOTALS),
  }));
}

export function formatEmployeeWeeklySummary(employee, { daysOnly = false, showBreaks = false } = {}) {
  const hours = Number(employee?.total_hours || 0);
  const days = Number(employee?.scheduled_days || 0);
  const dayLabel = days === 1 ? "1 day" : `${days} days`;
  if (daysOnly) return dayLabel;
  const hrsLabel = Number.isInteger(hours) ? `${hours}` : hours.toFixed(1);
  const net = showBreaks && Number(employee?.break_hours || 0) > 0 ? " net" : "";
  return `${hrsLabel}${net} hrs • ${dayLabel}`;
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
  let grossHours = 0;
  let breakHours = 0;
  let timedBreakHours = 0;
  let unscheduledBreakHours = 0;
  let totalDays = 0;
  const roleCounts = Object.fromEntries(ROLE_ORDER.map((role) => [role, 0]));
  const scheduledUserIds = new Set();

  for (const parts of scheduledHoursBreakdownByUserDay(filteredEntries).values()) {
    totalHours += parts.net;
    grossHours += parts.gross;
    breakHours += parts.break;
    timedBreakHours += parts.timedBreak;
    unscheduledBreakHours += parts.unscheduledBreak;
  }

  const scheduledUserDays = new Set();
  for (const entry of filteredEntries) {
    const uid = Number(entry.user_id);
    scheduledUserIds.add(uid);
    scheduledUserDays.add(`${uid}|${Number(entry.day_of_week || 0)}`);
    for (const role of parseEntryRoles(entry)) {
      if (role in roleCounts) roleCounts[role] += 1;
    }
  }
  totalDays = scheduledUserDays.size;
  const displayedTotals = employeeTotalsFromEntries(filteredEntries, data?.employees || []);

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
      estimatedCost += displayedTotals.get(uid)?.estimated_cost || 0;
    }
  }

  return {
    employeesScheduled,
    totalHours,
    grossHours,
    breakHours,
    timedBreakHours,
    unscheduledBreakHours,
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
    gross_hours: 0,
    break_hours: 0,
    timed_break_hours: 0,
    unscheduled_break_hours: 0,
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

  for (const [key, parts] of scheduledHoursBreakdownByUserDay(filteredEntries).entries()) {
    const summary = summaries[Number(key.split("|")[1])];
    if (!summary) continue;
    summary.hours += parts.net;
    summary.gross_hours += parts.gross;
    summary.break_hours += parts.break;
    summary.timed_break_hours += parts.timedBreak;
    summary.unscheduled_break_hours += parts.unscheduledBreak;
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
