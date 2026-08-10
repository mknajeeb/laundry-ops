/**
 * Management planner helpers.
 * Frontend validates for immediate feedback; backend remains authoritative.
 * Does not recreate staffing normalization or DES logic.
 */

import {
  DEFAULT_PROCESS_PARAMS,
  MANAGEMENT_HYBRIDS,
  MANAGEMENT_ROLES,
  PERSISTED_PLANNER_PARAM_KEYS,
  ROLE_LABEL,
  SESSION_PLANNER_PARAM_KEYS,
} from "./managementConstants";

const HYBRID_IDS = new Set(MANAGEMENT_HYBRIDS.map((h) => h.id));

const ROLE_ALIAS = {
  weigh: "weigher",
  weigher: "weigher",
  sort: "sorter",
  sorter: "sorter",
  wash: "washer",
  washer: "washer",
  dry: "dryer",
  dryer: "dryer",
  fold: "folder",
  folder: "folder",
};

/** Parse clock text to seconds from midnight; null if invalid. */
export function parseClockToSec(raw) {
  if (raw == null || raw === "") return null;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw > 24 * 60 ? Math.round(raw) : Math.round(raw) * 60;
  }
  const text = String(raw).trim();
  const m = text.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);
  if (!m) return null;
  let h = Number(m[1]);
  const min = Number(m[2]);
  const sec = m[3] != null ? Number(m[3]) : 0;
  const ampm = m[4] ? m[4].toUpperCase() : null;
  if (!Number.isFinite(h) || !Number.isFinite(min) || min > 59 || sec > 59) return null;
  if (ampm) {
    if (h < 1 || h > 12) return null;
    if (ampm === "AM") h = h === 12 ? 0 : h;
    else h = h === 12 ? 12 : h + 12;
  } else if (h > 23) {
    return null;
  }
  return h * 3600 + min * 60 + sec;
}

/** Format seconds-from-midnight as "9:00 AM". */
export function formatClockFromSec(sec) {
  if (sec == null || !Number.isFinite(sec)) return "";
  const total = ((Math.round(sec) % 86400) + 86400) % 86400;
  const h24 = Math.floor(total / 3600);
  const minute = Math.floor((total % 3600) / 60);
  const ampm = h24 >= 12 ? "PM" : "AM";
  let h12 = h24 % 12;
  if (h12 === 0) h12 = 12;
  return `${h12}:${String(minute).padStart(2, "0")} ${ampm}`;
}

/** Convert "9:00 AM" → "09:00" for PlanningTimePicker. */
export function clockToHm(raw) {
  const sec = parseClockToSec(raw);
  if (sec == null) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Convert "09:00" → "9:00 AM". */
export function hmToClock(hm) {
  const sec = parseClockToSec(hm);
  return sec == null ? "" : formatClockFromSec(sec);
}

export function normalizeRole(role) {
  const key = String(role || "").trim().toLowerCase();
  return ROLE_ALIAS[key] || null;
}

/** Half-open overlap: [aStart, aEnd) vs [bStart, bEnd). */
export function intervalsOverlap(aStart, aEnd, bStart, bEnd) {
  return aStart < bEnd && bStart < aEnd;
}

/**
 * Client-side planning blocks from start → target finish.
 * Matches management horizon (no separate shift-end).
 */
export function buildPlanningBlocks(startTime, targetTime, blockSizeMin) {
  const start = parseClockToSec(startTime);
  const end = parseClockToSec(targetTime);
  const sizeSec = (Number(blockSizeMin) || 60) * 60;
  if (start == null || end == null || end <= start || sizeSec <= 0) return [];
  const blocks = [];
  let t = start;
  while (t < end) {
    const next = Math.min(t + sizeSec, end);
    blocks.push({
      block_start: formatClockFromSec(t),
      block_end: formatClockFromSec(next),
      start_sec: t,
      end_sec: next,
    });
    t = next;
  }
  return blocks;
}

/**
 * Base people for a planning block / role.
 * Prefer headcount covering block start (what +/- edits).
 * If none, fall back to max BASE headcount overlapping the block so mid-block
 * base intervals are not invisible capacity.
 */
export function getBasePeopleForBlock(intervals, roleId, blockStart, blockEnd = null) {
  const bs = parseClockToSec(blockStart);
  if (bs == null) return 0;
  let atStart = 0;
  let maxOverlap = 0;
  const be = blockEnd != null ? parseClockToSec(blockEnd) : null;
  for (const row of intervals || []) {
    if (normalizeRole(row.role) !== roleId) continue;
    if (String(row.mode || "base").toLowerCase() === "additional") continue;
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null) continue;
    const people = Number(row.people) || 0;
    if (s <= bs && bs < e) atStart = Math.max(atStart, people);
    if (be != null && intervalsOverlap(s, e, bs, be)) {
      maxOverlap = Math.max(maxOverlap, people);
    }
  }
  if (atStart > 0) return atStart;
  return be != null ? maxOverlap : 0;
}

/** Index block_positions by block_end only (never by block_start — keys collide). */
export function indexBlockPositionsByEnd(blockPositions) {
  const map = {};
  (blockPositions || []).forEach((b) => {
    if (b && b.block_end != null) map[b.block_end] = b;
  });
  return map;
}

/** Additional intervals that overlap a block. */
export function getAdditionalForBlock(intervals, roleId, blockStart, blockEnd) {
  const bs = parseClockToSec(blockStart);
  const be = parseClockToSec(blockEnd);
  if (bs == null || be == null) return [];
  return (intervals || []).filter((row) => {
    if (normalizeRole(row.role) !== roleId) return false;
    if (String(row.mode || "base").toLowerCase() !== "additional") return false;
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null) return false;
    return intervalsOverlap(s, e, bs, be);
  });
}

/** Hybrid headcount for a planning block (base coverage at start, else max overlap). */
export function getHybridPeopleForBlock(intervals, hybridId, blockStart, blockEnd = null) {
  const bs = parseClockToSec(blockStart);
  if (bs == null || !HYBRID_IDS.has(hybridId)) return 0;
  let atStart = 0;
  let maxOverlap = 0;
  const be = blockEnd != null ? parseClockToSec(blockEnd) : null;
  for (const row of intervals || []) {
    if (String(row.hybrid || row.hybrid_type || "") !== hybridId) continue;
    if (String(row.mode || "base").toLowerCase() === "additional") continue;
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null) continue;
    const people = Number(row.people) || 0;
    if (s <= bs && bs < e) atStart = Math.max(atStart, people);
    if (be != null && intervalsOverlap(s, e, bs, be)) {
      maxOverlap = Math.max(maxOverlap, people);
    }
  }
  if (atStart > 0) return atStart;
  return be != null ? maxOverlap : 0;
}

/** Set hybrid base headcount for one planning block. */
export function setHybridPeopleForBlock(intervals, hybridId, blockStart, blockEnd, people) {
  const bs = parseClockToSec(blockStart);
  const be = parseClockToSec(blockEnd);
  const peopleN = Math.max(0, Math.floor(Number(people) || 0));
  if (bs == null || be == null || be <= bs || !HYBRID_IDS.has(hybridId)) {
    return intervals || [];
  }
  const next = [];
  for (const row of intervals || []) {
    if (String(row.hybrid || row.hybrid_type || "") !== hybridId) {
      next.push(row);
      continue;
    }
    if (String(row.mode || "base").toLowerCase() === "additional") {
      next.push(row);
      continue;
    }
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null || !intervalsOverlap(s, e, bs, be)) {
      next.push(row);
      continue;
    }
    if (s < bs) {
      next.push({ ...row, id: `${row.id}-L-${bs}`, end: formatClockFromSec(bs) });
    }
    if (be < e) {
      next.push({ ...row, id: `${row.id}-R-${be}`, start: formatClockFromSec(be) });
    }
  }
  if (peopleN >= 1) {
    next.push({
      id: `hy-${hybridId}-${blockStart}-${blockEnd}-${peopleN}`.replace(/\s+/g, ""),
      hybrid: hybridId,
      people: peopleN,
      start: blockStart,
      end: blockEnd,
      mode: "base",
    });
  }
  return next;
}

/**
 * Set base staffing for one block: splits any overlapping base for the role,
 * then inserts [blockStart, blockEnd) when people >= 1.
 */
export function setBasePeopleForBlock(intervals, roleId, blockStart, blockEnd, people) {
  const bs = parseClockToSec(blockStart);
  const be = parseClockToSec(blockEnd);
  const peopleN = Math.max(0, Math.floor(Number(people) || 0));
  if (bs == null || be == null || be <= bs) return intervals || [];

  const next = [];
  for (const row of intervals || []) {
    if (
      normalizeRole(row.role) !== roleId
      || String(row.mode || "base").toLowerCase() === "additional"
    ) {
      next.push(row);
      continue;
    }
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null || !intervalsOverlap(s, e, bs, be)) {
      next.push(row);
      continue;
    }
    if (s < bs) {
      next.push({
        ...row,
        id: `${row.id}-L-${bs}`,
        end: formatClockFromSec(bs),
      });
    }
    if (be < e) {
      next.push({
        ...row,
        id: `${row.id}-R-${be}`,
        start: formatClockFromSec(be),
      });
    }
  }
  if (peopleN >= 1) {
    next.push({
      id: `si-${roleId}-base-${blockStart}-${blockEnd}-${peopleN}`.replace(/\s+/g, ""),
      role: roleId,
      people: peopleN,
      start: blockStart,
      end: blockEnd,
      mode: "base",
    });
  }
  return next;
}

/**
 * Copy one role's base people count from the first planning block into every later block.
 * Does not touch other roles, additional/temp intervals, or the first block itself.
 */
export function fillRestBasePeopleForRole(intervals, roleId, planBlocks, people) {
  const blocks = Array.isArray(planBlocks) ? planBlocks : [];
  if (blocks.length < 2) return intervals || [];
  const peopleN = Math.max(0, Math.floor(Number(people) || 0));
  let next = intervals || [];
  for (let i = 1; i < blocks.length; i += 1) {
    const block = blocks[i];
    next = setBasePeopleForBlock(next, roleId, block.block_start, block.block_end, peopleN);
  }
  return next;
}

/**
 * Client-side validation of authored intervals.
 * Horizon = start → target finish (mapped as endTime).
 */
export function validateStaffingIntervals(intervals, { startTime, endTime } = {}) {
  const errors = [];
  const planStart = parseClockToSec(startTime);
  const planEnd = parseClockToSec(endTime);
  const rows = Array.isArray(intervals) ? intervals : [];

  rows.forEach((row) => {
    const role = normalizeRole(row.role);
    if (!role) {
      errors.push({ message: `Unsupported role “${row.role}”.`, intervalId: row.id });
      return;
    }
    const people = Number(row.people);
    if (!Number.isFinite(people) || !Number.isInteger(people)) {
      errors.push({ message: "People must be a whole number.", intervalId: row.id });
      return;
    }
    if (people < 1) {
      errors.push({ message: "People must be at least 1 (remove the row for zero staffing).", intervalId: row.id });
      return;
    }
    const start = parseClockToSec(row.start);
    const end = parseClockToSec(row.end);
    if (start == null || end == null) {
      errors.push({ message: "Enter a valid start and end time.", intervalId: row.id });
      return;
    }
    if (end <= start) {
      errors.push({ message: "End must be after start.", intervalId: row.id });
      return;
    }
    if (planStart != null && planEnd != null && (start < planStart || end > planEnd)) {
      errors.push({
        message: "Staffing must stay within the plan start and target finish.",
        intervalId: row.id,
      });
    }
  });

  const bases = rows.filter((r) => String(r.mode || "base").toLowerCase() === "base");
  for (let i = 0; i < bases.length; i += 1) {
    for (let j = i + 1; j < bases.length; j += 1) {
      const a = bases[i];
      const b = bases[j];
      if (normalizeRole(a.role) !== normalizeRole(b.role)) continue;
      const aStart = parseClockToSec(a.start);
      const aEnd = parseClockToSec(a.end);
      const bStart = parseClockToSec(b.start);
      const bEnd = parseClockToSec(b.end);
      if (aStart == null || aEnd == null || bStart == null || bEnd == null) continue;
      if (intervalsOverlap(aStart, aEnd, bStart, bEnd)) {
        const label = ROLE_LABEL[normalizeRole(a.role)] || a.role;
        errors.push({
          message: `${label} base staffing already covers part of this time range.`,
          intervalId: b.id || a.id,
        });
      }
    }
  }

  return { ok: errors.length === 0, errors };
}

export function buildManagementPayload(inputs) {
  const dedicated = (inputs.staffing_intervals || []).map((row) => ({
    role: normalizeRole(row.role) || row.role,
    people: Number(row.people),
    start: row.start,
    end: row.end,
    mode: String(row.mode || "base").toLowerCase() === "additional" ? "additional" : "base",
  }));
  const hybrids = (inputs.hybrid_intervals || [])
    .filter((row) => HYBRID_IDS.has(String(row.hybrid || row.hybrid_type || "")))
    .map((row) => ({
      hybrid: String(row.hybrid || row.hybrid_type),
      people: Number(row.people),
      start: row.start,
      end: row.end,
      mode: String(row.mode || "base").toLowerCase() === "additional" ? "additional" : "base",
    }));
  const intervals = [...dedicated, ...hybrids];

  // Horizon = start → target finish. Backend still accepts end_time; map it internally.
  const target = inputs.target_time;

  const avgLbs = Number(inputs.avg_lbs_per_bag);
  const washSplit = Number(inputs.two_washer_split_pct);
  const drySplit = Number(inputs.two_dryer_split_pct);

  return {
    engine: "bag_des_v2",
    management_mode: true,
    start_time: inputs.start_time,
    target_time: target,
    end_time: target,
    planning_block_size_min: Number(inputs.planning_block_size_min) || 60,
    summary_interval_min: Number(inputs.planning_block_size_min) || 60,
    bag_count: Number(inputs.bag_count) || 1,
    avg_lbs_per_bag: Number.isFinite(avgLbs) && avgLbs > 0 ? avgLbs : 20,
    two_washer_split_pct: Number.isFinite(washSplit) ? washSplit : 80,
    two_dryer_split_pct: Number.isFinite(drySplit) ? drySplit : 80,
    washer_count: Number(inputs.washer_count) || 4,
    dryer_count: Number(inputs.dryer_count) || 4,
    batch_size: Number(inputs.batch_size) || 8,
    weigh_sec_per_bag: Number(inputs.weigh_sec_per_bag) || 45,
    sort_min_per_bag: Number(inputs.sort_min_per_bag) || 5,
    load_washer_min: Number(inputs.load_washer_min) || 3,
    wash_cycle_min: Number(inputs.wash_cycle_min) || 30,
    load_dryer_min: Number(inputs.load_dryer_min) || 3,
    dry_cycle_min: Number(inputs.dry_cycle_min) || 45,
    fold_min_per_bag: Number(inputs.fold_min_per_bag) || 6,
    fold_rate_mode: "minutes_per_bag",
    staffing_plan: { intervals },
    _skip_recommendations: true,
  };
}

/** Pick org-persisted planner parameter keys from an inputs object. */
export function pickPersistedPlannerParams(inputs = {}) {
  const out = {};
  for (const key of PERSISTED_PLANNER_PARAM_KEYS) {
    if (inputs[key] !== undefined && inputs[key] !== null) out[key] = inputs[key];
  }
  return out;
}

/** Snapshot of locked strip fields (persisted + session-only). */
export function pickEditablePlannerParamSnapshot(inputs = {}) {
  const out = pickPersistedPlannerParams(inputs);
  for (const key of SESSION_PLANNER_PARAM_KEYS) {
    if (inputs[key] !== undefined && inputs[key] !== null) out[key] = inputs[key];
  }
  return out;
}

/** Merge saved persisted params into full inputs (staffing untouched). */
export function applyPersistedPlannerParams(inputs, saved) {
  return {
    ...inputs,
    ...pickPersistedPlannerParams(saved || {}),
  };
}

/**
 * Validate org-persisted planner params before Save.
 * Does not mutate saved state; returns { ok, errors, normalized? }.
 */
export function validatePersistedPlannerParams(inputs) {
  const errors = [];
  const bag = Number(inputs.bag_count);
  if (!Number.isFinite(bag) || bag < 1 || !Number.isInteger(bag)) {
    errors.push({ message: "Target bags must be a whole number >= 1." });
  }
  const startSec = parseClockToSec(inputs.start_time);
  const targetSec = parseClockToSec(inputs.target_time);
  if (startSec == null) errors.push({ message: "Start time is invalid." });
  if (targetSec == null) errors.push({ message: "Target finish is invalid." });
  if (startSec != null && targetSec != null && targetSec <= startSec) {
    errors.push({ message: "Target finish must be after start time." });
  }
  const block = Number(inputs.planning_block_size_min);
  if (![30, 45, 60].includes(block)) {
    errors.push({ message: "Block size must be 30, 45, or 60 minutes." });
  }
  for (const [key, label] of [
    ["washer_count", "Washers"],
    ["dryer_count", "Dryers"],
  ]) {
    const n = Number(inputs[key]);
    if (!Number.isFinite(n) || n < 1 || !Number.isInteger(n)) {
      errors.push({ message: `${label} must be a whole number >= 1.` });
    }
  }
  const weigh = Number(inputs.weigh_sec_per_bag);
  if (!Number.isFinite(weigh) || weigh <= 0) {
    errors.push({ message: "Weigh seconds must be greater than 0." });
  }
  for (const [key, label, minExclusive] of [
    ["sort_min_per_bag", "Sort minutes", false],
    ["load_washer_min", "Wash labor minutes", false],
    ["wash_cycle_min", "Wash cycle minutes", true],
    ["load_dryer_min", "Dry labor minutes", false],
    ["dry_cycle_min", "Dry cycle minutes", true],
    ["fold_min_per_bag", "Fold minutes", false],
  ]) {
    const n = Number(inputs[key]);
    if (!Number.isFinite(n) || n < 0 || (minExclusive && n <= 0)) {
      errors.push({
        message: minExclusive
          ? `${label} must be greater than 0.`
          : `${label} must be >= 0.`,
      });
    }
  }
  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    errors: [],
    normalized: {
      bag_count: bag,
      start_time: String(inputs.start_time).trim(),
      target_time: String(inputs.target_time).trim(),
      planning_block_size_min: block,
      washer_count: Number(inputs.washer_count),
      dryer_count: Number(inputs.dryer_count),
      weigh_sec_per_bag: weigh,
      sort_min_per_bag: Number(inputs.sort_min_per_bag),
      load_washer_min: Number(inputs.load_washer_min),
      wash_cycle_min: Number(inputs.wash_cycle_min),
      load_dryer_min: Number(inputs.load_dryer_min),
      dry_cycle_min: Number(inputs.dry_cycle_min),
      fold_min_per_bag: Number(inputs.fold_min_per_bag),
    },
  };
}

/** Client-side checks for Plan/Machine parameters (backend remains authoritative). */
export function validateManagementPlanInputs(inputs) {
  const errors = [];
  const persisted = validatePersistedPlannerParams(inputs);
  if (!persisted.ok) errors.push(...persisted.errors);
  const avg = Number(inputs.avg_lbs_per_bag);
  if (!Number.isFinite(avg) || avg <= 0) {
    errors.push({ message: "Avg bag weight must be greater than 0." });
  }
  for (const [key, label] of [
    ["two_washer_split_pct", "2-Washer Split"],
    ["two_dryer_split_pct", "2-Dryer Split"],
  ]) {
    const pct = Number(inputs[key]);
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) {
      errors.push({ message: `${label} must be between 0 and 100.` });
    }
  }
  return { ok: errors.length === 0, errors };
}

export function formatPeople(n) {
  const count = Number(n) || 0;
  return count === 1 ? "1 person" : `${count} people`;
}

export function formatIntervalLine(row) {
  const people = Number(row.people) || 0;
  const range = `${row.start}–${row.end}`;
  if (String(row.mode).toLowerCase() === "additional") {
    return `+${people} · ${range}`;
  }
  return `${formatPeople(people)} · ${range}`;
}

/** Compact staffing summary for a block from backend block_positions[].staffing */
export function formatBlockStaffingLine(staffing) {
  if (!staffing?.roles) return "No staffing";
  const parts = MANAGEMENT_ROLES.map(({ id, short }) => {
    const role = staffing.roles[id];
    if (!role) return null;
    const atStart = Number(role.people_at_block_start) || 0;
    const peak = Number(role.peak_people) || 0;
    if (atStart === 0 && peak === 0 && !(role.additional || []).length) return `${short} 0`;
    const extras = (role.additional || [])
      .map((a) => `+${a.people} ${a.start}–${a.end}`)
      .join(", ");
    if (extras) return `${short} ${atStart || peak}${extras ? ` (${extras})` : ""}`;
    return `${short} ${peak || atStart}`;
  }).filter(Boolean);
  return parts.join(" · ");
}

/**
 * Match DES work_coverage rows for a role (or hybrid) overlapping a planning block.
 * Presentation only — all metrics come from the API (no frontend capacity math).
 */
export function findWorkCoverageForRole(coverageRows, roleId, blockStart, blockEnd, { mode } = {}) {
  const bs = parseClockToSec(blockStart);
  const be = parseClockToSec(blockEnd);
  if (bs == null || be == null) return [];
  const rows = Array.isArray(coverageRows) ? coverageRows : [];
  return rows.filter((row) => {
    if (mode != null && String(row.mode || "base").toLowerCase() !== String(mode).toLowerCase()) {
      return false;
    }
    if (row.hybrid) return false;
    if (normalizeRole(row.role) !== roleId) return false;
    const s = Number(row.start_sec);
    const e = Number(row.end_sec);
    if (!Number.isFinite(s) || !Number.isFinite(e)) return false;
    return s < be && e > bs;
  });
}

export function findWorkCoverageForHybrid(coverageRows, hybridId, blockStart, blockEnd) {
  const bs = parseClockToSec(blockStart);
  const be = parseClockToSec(blockEnd);
  if (bs == null || be == null) return [];
  const rows = Array.isArray(coverageRows) ? coverageRows : [];
  return rows.filter((row) => {
    if (row.hybrid !== hybridId) return false;
    const s = Number(row.start_sec);
    const e = Number(row.end_sec);
    if (!Number.isFinite(s) || !Number.isFinite(e)) return false;
    return s < be && e > bs;
  });
}

const COVERAGE_ROLE_TITLE = {
  weigher: "WEIGH",
  sorter: "SORT",
  washer: "WASH",
  dryer: "DRY",
  folder: "FOLD",
  weigh_wash: "WEIGH/WASH",
  wash_dry: "WASH/DRY",
  weigh_wash_dry: "WEIGH/WASH/DRY",
};

const COVERAGE_ROLE_SHORT = {
  weigher: "Weigh",
  sorter: "Sort",
  washer: "Wash",
  dryer: "Dry",
  folder: "Fold",
};

/**
 * Manager-facing utilization from a DES work_coverage row.
 * Answers: was this person actually utilized during this staffing interval?
 * Does not recompute capacity — only formats API idle classification fields.
 */
export function describeWorkCoverage(row, options = {}) {
  if (!row) {
    return {
      level: "none",
      levelLabel: "",
      reasonCode: "",
      reasonLabel: "",
      usedMin: 0,
      staffMin: 0,
      idleMin: 0,
      headline: "",
      lines: [],
      detail: "",
    };
  }
  const params = { ...DEFAULT_PROCESS_PARAMS, ...(options.processParams || {}) };
  const staffMin = Number(row.staff_min) || 0;
  const usedMin = Number(row.used_min) || 0;
  const idleMin = Number(row.idle_min) || 0;
  const idleNo = Number(row.idle_no_eligible_work_min) || 0;
  const unusedFit = Number(row.unused_fit_min) || 0;
  const usedS = _fmtCoverageMin(usedMin);
  const staffS = _fmtCoverageMin(staffMin);
  const idleS = _fmtCoverageMin(idleMin);
  const ratio = staffMin > 0 ? usedMin / staffMin : 0;
  const utilPct = staffMin > 0 ? Math.round((usedMin / staffMin) * 100) : 0;

  let level = "underutilized";
  let levelLabel = "UNDERUTILIZED";
  if (row.status === "fully_utilized" || idleMin < 0.5) {
    level = "fully_utilized";
    levelLabel = "FULLY UTILIZED";
  } else if (ratio >= 0.75 || idleMin <= Math.max(5, staffMin * 0.15)) {
    level = "mostly_utilized";
    levelLabel = "MOSTLY UTILIZED";
  }

  let reasonCode = "FULLY_UTILIZED";
  if (level !== "fully_utilized") {
    if (idleNo > 0.05 && unusedFit <= 0.05) {
      reasonCode = "NO_WORK_AVAILABLE";
    } else if (unusedFit > 0.05 && idleNo <= 0.05) {
      reasonCode = "WORK_DID_NOT_FIT";
    } else if (idleNo > 0.05 && unusedFit > 0.05) {
      reasonCode = "WORK_ARRIVED_TOO_LATE";
    } else if (String(row.status || "").includes("machine")) {
      reasonCode = "MACHINE_CAPACITY_LIMITED";
    } else {
      reasonCode = "WORK_DID_NOT_FIT";
    }
  }

  const isTemp = String(row.mode || "").toLowerCase() === "additional";
  const roleKey = normalizeRole(row.role) || row.role;
  const roleTitle = COVERAGE_ROLE_TITLE[roleKey]
    || COVERAGE_ROLE_TITLE[row.hybrid]
    || String(ROLE_LABEL[roleKey] || roleKey || "STAFF").toUpperCase();
  const roleShort = COVERAGE_ROLE_SHORT[roleKey] || ROLE_LABEL[roleKey] || roleTitle;

  const reasonLabel = _coverageUnusedExplanation({
    role: row.role,
    idleNo,
    unusedFit,
    idleMin,
    params,
  });

  const alloc = row.role_allocation_min;
  if (alloc && typeof alloc === "object" && !isTemp) {
    const labels = { weigher: "Weigh", washer: "Wash", dryer: "Dry", sorter: "Sort", folder: "Fold" };
    const parts = [];
    Object.keys(labels).forEach((k) => {
      const v = Number(alloc[k]);
      if (v > 0) parts.push(`${labels[k]} ${_fmtCoverageMin(v)}m`);
    });
    const idleAlloc = Number(alloc.idle);
    const idlePart = Number.isFinite(idleAlloc) ? idleAlloc : idleMin;
    parts.push(`Idle ${_fmtCoverageMin(idlePart)}`);
    const hybridLines = [
      `${usedS} of ${staffS} min productive · ${utilPct}% utilized`,
      parts.join(" · "),
    ];
    if (reasonLabel) hybridLines.push(reasonLabel);
    return {
      level,
      levelLabel,
      reasonCode,
      reasonLabel,
      usedMin,
      staffMin,
      idleMin,
      headline: hybridLines[0],
      lines: hybridLines,
      detail: formatWorkCoverageDetail(row),
    };
  }

  const head = isTemp
    ? `${roleShort.toUpperCase()} TEMP ${row.start}–${row.end} — ${usedS} of ${staffS} min productive · ${utilPct}% utilized`
    : `${roleTitle} — ${usedS} of ${staffS} min productive · ${utilPct}% utilized`;

  const lines = [head];
  if (reasonLabel) lines.push(reasonLabel);

  return {
    level,
    levelLabel,
    reasonCode,
    reasonLabel,
    usedMin,
    staffMin,
    idleMin,
    headline: head,
    lines,
    detail: formatWorkCoverageDetail(row),
  };
}

function _coverageUnusedExplanation({ role, idleNo, unusedFit, idleMin, params }) {
  if (idleMin < 0.05) return "";
  const roleId = normalizeRole(role) || role;
  if (partsWouldBeIdleOnly(idleNo, unusedFit)) {
    return `${_fmtCoverageMin(idleMin)} min unused: ${_waitingPhrase(roleId)}`;
  }
  if (partsWouldBeFitOnly(idleNo, unusedFit)) {
    return `${_fmtCoverageMin(idleMin)} min unused: ${_insufficientFitPhrase(roleId, params, false)}`;
  }
  const parts = [];
  if (idleNo > 0.05) {
    parts.push(`${_fmtCoverageMin(idleNo)} min ${_waitingPhrase(roleId)}`);
  }
  if (unusedFit > 0.05) {
    parts.push(`${_fmtCoverageMin(unusedFit)} min ${_insufficientFitPhrase(roleId, params, true)}`);
  }
  if (!parts.length) return "";
  return `${_fmtCoverageMin(idleMin)} min unused: ${parts.join(" · ")}`;
}

function partsWouldBeIdleOnly(idleNo, unusedFit) {
  return idleNo > 0.05 && unusedFit <= 0.05;
}

function partsWouldBeFitOnly(idleNo, unusedFit) {
  return unusedFit > 0.05 && idleNo <= 0.05;
}

function _waitingPhrase(roleId) {
  if (roleId === "sorter") return "waiting for bags";
  if (roleId === "washer") return "waiting for sorted bags";
  if (roleId === "dryer") return "waiting for washed bags";
  if (roleId === "folder") return "waiting for dried bags";
  if (roleId === "weigher") return "waiting for bags";
  return "waiting for bags";
}

function _insufficientFitPhrase(roleId, params, shortForm) {
  if (roleId === "washer" || roleId === "dryer") {
    return "insufficient time for next required load";
  }
  if (roleId === "sorter") {
    const unit = Number(params.sort_min_per_bag) || 5;
    return shortForm
      ? "too short to start another sort"
      : `insufficient time for another ${_fmtCoverageMin(unit)}-min sort`;
  }
  if (roleId === "folder") {
    const unit = Number(params.fold_min_per_bag) || 6;
    return shortForm
      ? "too short to start another fold"
      : `insufficient time for another ${_fmtCoverageMin(unit)}-min fold`;
  }
  if (roleId === "weigher") {
    const sec = Number(params.weigh_sec_per_bag) || 45;
    return `insufficient time for another ${sec}-sec weigh`;
  }
  return "insufficient time for next required work";
}

/** Manager-facing primary lines (joined). */
export function formatWorkCoverageLine(row, options = {}) {
  const d = describeWorkCoverage(row, options);
  return d.lines.filter(Boolean).join("\n");
}

/** Diagnostic detail for hover / expand — keeps API diagnostics available. */
export function formatWorkCoverageDetail(row) {
  if (!row) return "";
  const bags = Number(row.eligible_bags) || 0;
  const demand = _fmtCoverageMin(row.available_work_min);
  const loads = Number(row.physical_loads_available) || 0;
  return [
    `${bags} eligible bags · ${demand} min total eligible work demand generated during interval`,
    `${_fmtCoverageMin(row.staff_min)} staff min · ${_fmtCoverageMin(row.used_min)} productive · ${_fmtCoverageMin(row.idle_min)} unused`,
    `${_fmtCoverageMin(row.idle_no_eligible_work_min)} min waiting (no eligible work) · ${_fmtCoverageMin(row.unused_fit_min)} min unused fit`,
    loads ? `${loads} physical loads` : null,
    row.status ? `engine status ${row.status}` : null,
  ].filter(Boolean).join(" · ");
}

function _fmtCoverageMin(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "0";
  const rounded = Math.round(n * 100) / 100;
  if (Math.abs(rounded - Math.round(rounded)) < 0.001) return String(Math.round(rounded));
  const tenths = Math.round(rounded * 10) / 10;
  if (Math.abs(rounded - tenths) < 0.001) return tenths.toFixed(1);
  return rounded.toFixed(2);
}

export function formatStageProgress(label, total, thisBlock) {
  const t = Number(total) || 0;
  const d = Number(thisBlock) || 0;
  if (d > 0) return `${label} ${t} (+${d} this slot)`;
  return `${label} ${t}`;
}

/** Compact hybrid chips for collapsed slot summary (short labels). */
export function formatHybridStaffChips(hybridIntervals, blockStart, blockEnd) {
  const short = {
    weigh_wash: "Hybrid W/W",
    wash_dry: "Hybrid W/D",
    weigh_wash_dry: "Hybrid W/W/D",
  };
  return MANAGEMENT_HYBRIDS.map((h) => {
    const n = getHybridPeopleForBlock(hybridIntervals, h.id, blockStart, blockEnd);
    if (n <= 0) return null;
    return `${short[h.id] || h.label} ${n}`;
  }).filter(Boolean);
}

/** Compact TEMP chips for collapsed slot summary (ADDITIONAL intervals only). */
export function formatTempStaffChips(intervals, blockStart, blockEnd) {
  const chips = [];
  for (const role of MANAGEMENT_ROLES) {
    const extras = getAdditionalForBlock(intervals, role.id, blockStart, blockEnd);
    for (const row of extras) {
      const people = Number(row.people) || 0;
      if (people <= 0) continue;
      chips.push(`${role.short} +${people} ${row.start}–${row.end}`);
    }
  }
  return chips;
}

/**
 * Collapsed STAFF line for one planning slot.
 * Includes BASE headcount, inline TEMP windows, and compact Hybrid chips.
 */
export function formatCollapsedSlotStaffLine(intervals, hybridIntervals, blockStart, blockEnd) {
  const dedicated = MANAGEMENT_ROLES.map((role) => {
    const n = getBasePeopleForBlock(intervals, role.id, blockStart, blockEnd);
    const extras = getAdditionalForBlock(intervals, role.id, blockStart, blockEnd)
      .filter((row) => (Number(row.people) || 0) > 0)
      .map((row) => `+${Number(row.people)} ${row.start}–${row.end}`);
    if (!extras.length) return `${role.short} ${n}`;
    return `${role.short} ${n} (${extras.join(", ")})`;
  }).join(" · ");
  const hybrids = formatHybridStaffChips(hybridIntervals, blockStart, blockEnd);
  return hybrids.length ? `${dedicated} · ${hybrids.join(" · ")}` : dedicated;
}

/** Effective dedicated headcount in a slot (BASE at/overlapping start + ADDITIONAL overlap). */
export function dedicatedPeopleInSlot(intervals, roleId, blockStart, blockEnd) {
  const base = getBasePeopleForBlock(intervals, roleId, blockStart, blockEnd);
  const additional = getAdditionalForBlock(intervals, roleId, blockStart, blockEnd).reduce(
    (sum, row) => sum + (Number(row.people) || 0),
    0,
  );
  return base + additional;
}

/**
 * Compact flow notes for a slot's staffing mix.
 * DES already enforces chronology (Dry cannot load before Wash ends).
 * These warn only when the authored mix cannot feed a later role in-slot.
 */
export function buildSlotStaffingNotes(staffingIntervals, hybridIntervals, blockStart, blockEnd) {
  const washer = dedicatedPeopleInSlot(staffingIntervals, "washer", blockStart, blockEnd);
  const dryer = dedicatedPeopleInSlot(staffingIntervals, "dryer", blockStart, blockEnd);
  const folder = dedicatedPeopleInSlot(staffingIntervals, "folder", blockStart, blockEnd);
  const ww = getHybridPeopleForBlock(hybridIntervals, "weigh_wash", blockStart, blockEnd);
  const wd = getHybridPeopleForBlock(hybridIntervals, "wash_dry", blockStart, blockEnd);
  const wwd = getHybridPeopleForBlock(hybridIntervals, "weigh_wash_dry", blockStart, blockEnd);
  const washCap = washer + ww + wd + wwd;
  const dryCap = dryer + wd + wwd;
  const hybridCap = ww + wd + wwd;
  const notes = [];
  if (dryCap > 0 && washCap === 0) {
    notes.push({
      tone: "warning",
      text: "Dry waits for Wash — no Wash labor in this slot (dedicated or hybrid).",
    });
  }
  if (folder > 0 && dryCap === 0) {
    notes.push({
      tone: "warning",
      text: "Fold waits for Dry — no Dry labor in this slot (dedicated or hybrid).",
    });
  }
  if (hybridCap > 0) {
    notes.push({
      tone: "info",
      text: "Hybrid is one person on one calendar — cannot work two roles at the same instant.",
    });
  }
  return notes;
}

/**
 * View model for one planning slot card (staffing start + end POSITION).
 * Presentation-only — all counts come from authored intervals / block_positions.
 */
export function buildPlanningSlotViewModel({
  blockStart,
  blockEnd,
  staffingIntervals,
  hybridIntervals,
  positionBlock,
  targetBags,
  staffingExpanded = false,
} = {}) {
  const staffLine = formatCollapsedSlotStaffLine(
    staffingIntervals,
    hybridIntervals,
    blockStart,
    blockEnd,
  );
  const staffingNotes = buildSlotStaffingNotes(
    staffingIntervals,
    hybridIntervals,
    blockStart,
    blockEnd,
  );
  return {
    slotKey: `${blockStart}->${blockEnd}`,
    slotLabel: `${blockStart} → ${blockEnd}`,
    blockStart,
    blockEnd,
    staffingExpanded: Boolean(staffingExpanded),
    staffLine,
    staffingNotes,
    hybridChips: formatHybridStaffChips(hybridIntervals, blockStart, blockEnd),
    positionLabel: `${blockEnd} POSITION`,
    flow: buildPositionFlowDisplay(positionBlock, targetBags),
  };
}

/**
 * End-of-slot remaining for a stage: bags not yet DONE with that stage.
 * Display-only; not the same as between-stage WAITING queues.
 */
export function stageRemaining(targetBags, stageTotal) {
  const target = Math.max(0, Number(targetBags) || 0);
  const done = Math.max(0, Number(stageTotal) || 0);
  return Math.max(0, target - done);
}

/**
 * Compact end-of-slot stage position for management POSITION nodes.
 * Done uses backend completed-stage totals; remaining = target - done.
 * inCycle is API-provided (wash/dry machine cycle) — never computed here.
 */
export function buildStagePositionDisplay({
  title,
  thisBlock,
  stageTotal,
  targetBags,
  completeLabel = false,
  inCycle = null,
} = {}) {
  const done = Math.max(0, Number(stageTotal) || 0);
  const remaining = stageRemaining(targetBags, done);
  const block = Math.max(0, Number(thisBlock) || 0);
  const target = Math.max(0, Number(targetBags) || 0);
  const cycleN = inCycle == null ? null : Math.max(0, Number(inCycle) || 0);
  return {
    title: title || "",
    thisBlock: block,
    done,
    remaining,
    target,
    doneLabel: completeLabel ? "COMPLETE" : "DONE",
    remainingLabel: "REMAINING",
    thisBlockLabel: block > 0 ? `+${block} this slot` : "0 this slot",
    inCycle: cycleN,
    inCycleLabel:
      cycleN != null && cycleN > 0
        ? `${cycleN} IN CYCLE`
        : null,
  };
}

function _blockInCycle(block, key) {
  if (!block) return 0;
  const detail = block.detail || {};
  const raw = block[key] ?? detail[key];
  return Math.max(0, Number(raw) || 0);
}

/**
 * Map a block_positions row to stage display models.
 * Waiting queues are returned separately and must not be conflated with remaining.
 */
/**
 * Concise hover copy for WAITING TO ENTER SORT (queued ≠ stage remaining).
 * Uses authored DONE totals; does not recompute waiting from the engine.
 */
export function formatWaitingToSortHint(weighedDone, sortedDone, waitingToSort) {
  const w = Math.max(0, Number(weighedDone) || 0);
  const s = Math.max(0, Number(sortedDone) || 0);
  const q = Math.max(0, Number(waitingToSort) || 0);
  if (q <= 0) return "No bags waiting to enter Sort.";
  return (
    `${w} bags have completed Weigh and ${s} have completed Sort, `
    + `leaving ${q} currently waiting to enter Sort.`
  );
}

/**
 * Presentation-only upstream reconciliation using backend counts.
 * Does not invent or replace DES values — only formats what the API returned.
 */
export function formatStageReconcile({
  upstreamDone,
  waitingToEnter,
  inCycle,
  inLabor = 0,
  stageDone,
  upstreamLabel,
  stageLabel,
} = {}) {
  const up = Math.max(0, Number(upstreamDone) || 0);
  const wait = Math.max(0, Number(waitingToEnter) || 0);
  const cycle = Math.max(0, Number(inCycle) || 0);
  const labor = Math.max(0, Number(inLabor) || 0);
  const done = Math.max(0, Number(stageDone) || 0);
  const accounted = wait + cycle + labor + done;
  const laborPart = labor > 0 ? ` + ${labor} in labor` : "";
  return {
    upstreamDone: up,
    waitingToEnter: wait,
    inCycle: cycle,
    inLabor: labor,
    stageDone: done,
    accounted,
    matches: accounted === up,
    text:
      `${up} ${upstreamLabel} DONE = ${wait} waiting to enter`
      + ` + ${cycle} in cycle${laborPart} + ${done} ${stageLabel} DONE`,
  };
}

/**
 * Two-row management POSITION view.
 * Row 1 PROGRESS = cumulative stage DONE (not current location).
 * Row 2 CURRENT = mutually exclusive parent states (where every bag sits now).
 * All counts come from block_positions / detail — no frontend DES math.
 */
export function buildPositionInventoryDisplay(block, targetBags) {
  if (!block) return null;
  const target = Math.max(0, Number(targetBags ?? block.target_bags) || 0);
  const detail = block.detail || {};
  const states = (block.reconciliation && block.reconciliation.states) || {};
  const n = (key) => Math.max(
    0,
    Number(block[key] ?? detail[key] ?? states[key]) || 0,
  );

  const inWeighLabor = n("in_weigh_labor");
  const inSortLabor = n("in_sort_labor");
  const inWashLabor = n("in_wash_labor");
  const inWashCycle = n("in_wash_cycle");
  const inTransfer = n("in_transfer_labor");
  const inDryLabor = n("in_dry_labor");
  const inDryCycle = n("in_dry_cycle");
  const inFoldLabor = n("in_fold_labor");

  const washingNow = inWashLabor + inWashCycle;
  const dryingNow = inDryLabor + inDryCycle;
  // Transfer is between wash and dry; fold into waiting-to-dry for management row.
  const waitingToDry = n("waiting_to_dry") + inTransfer;

  const inventory = [
    { id: "not_yet_weighed", label: "Not Yet Weighed", count: n("not_yet_weighed") },
    { id: "weighing_now", label: "Weighing Now", count: inWeighLabor },
    { id: "waiting_to_sort", label: "Waiting to Sort", count: n("waiting_to_sort") },
    { id: "sorting_now", label: "Sorting Now", count: inSortLabor },
    { id: "waiting_to_wash", label: "Waiting to Wash", count: n("waiting_to_wash") },
    {
      id: "washing_now",
      label: "Washing Now",
      count: washingNow,
      detail: washingNow > 0
        ? `${inWashLabor} loading · ${inWashCycle} in machine`
        : null,
    },
    { id: "waiting_to_dry", label: "Waiting to Dry", count: waitingToDry },
    {
      id: "drying_now",
      label: "Drying Now",
      count: dryingNow,
      detail: dryingNow > 0
        ? `${inDryLabor} loading · ${inDryCycle} in machine`
        : null,
    },
    { id: "waiting_to_fold", label: "Waiting to Fold", count: n("waiting_to_fold") },
    { id: "folding_now", label: "Folding Now", count: inFoldLabor },
    { id: "complete", label: "Complete", count: n("completed") || n("folded_total") },
  ];

  const inventorySum = inventory.reduce((sum, row) => sum + row.count, 0);
  const progress = [
    {
      id: "weigh",
      title: "WEIGH",
      done: n("weighed_total"),
      doneLabel: "DONE",
      thisSlot: n("weighed_this_block"),
    },
    {
      id: "sort",
      title: "SORT",
      done: n("sorted_total"),
      doneLabel: "DONE",
      thisSlot: n("sorted_this_block"),
    },
    {
      id: "wash",
      title: "WASH",
      done: n("washed_total"),
      doneLabel: "DONE",
      thisSlot: n("washed_this_block"),
    },
    {
      id: "dry",
      title: "DRY",
      done: n("dried_total"),
      doneLabel: "DONE",
      thisSlot: n("dried_this_block"),
    },
    {
      id: "fold",
      title: "FOLD",
      done: n("folded_total") || n("completed"),
      doneLabel: "COMPLETE",
      thisSlot: n("folded_this_block") || n("completed_this_block"),
    },
  ];

  // Pipeline checks (debug / details only).
  const weighDone = n("weighed_total");
  const sortDone = n("sorted_total");
  const washDone = n("washed_total");
  const dryDone = n("dried_total");
  const details = {
    weighPipeline: {
      left: weighDone,
      right: n("waiting_to_sort") + inSortLabor + sortDone,
      matches: weighDone === n("waiting_to_sort") + inSortLabor + sortDone,
      text:
        `${weighDone} Weigh DONE = ${n("waiting_to_sort")} waiting to sort`
        + ` + ${inSortLabor} sorting now + ${sortDone} Sort DONE`,
    },
    sortPipeline: {
      left: sortDone,
      right: n("waiting_to_wash") + inWashLabor + inWashCycle + washDone,
      matches: sortDone === n("waiting_to_wash") + inWashLabor + inWashCycle + washDone,
      text:
        `${sortDone} Sort DONE = ${n("waiting_to_wash")} waiting to wash`
        + ` + ${inWashLabor} wash labor + ${inWashCycle} wash cycle + ${washDone} Wash DONE`,
    },
    washPipeline: {
      left: washDone,
      right: n("waiting_to_dry") + inTransfer + inDryLabor + inDryCycle + dryDone,
      matches:
        washDone === n("waiting_to_dry") + inTransfer + inDryLabor + inDryCycle + dryDone,
      text:
        `${washDone} Wash DONE = ${n("waiting_to_dry")} waiting to dry`
        + ` + ${inTransfer} transfer + ${inDryLabor} dry labor`
        + ` + ${inDryCycle} dry cycle + ${dryDone} Dry DONE`,
    },
    dryPipeline: {
      left: dryDone,
      right: n("waiting_to_fold") + inFoldLabor + (n("folded_total") || n("completed")),
      matches:
        dryDone === n("waiting_to_fold") + inFoldLabor + (n("folded_total") || n("completed")),
      text:
        `${dryDone} Dry DONE = ${n("waiting_to_fold")} waiting to fold`
        + ` + ${inFoldLabor} folding now + ${n("folded_total") || n("completed")} Fold COMPLETE`,
    },
  };

  return {
    progress,
    inventory,
    inventorySum,
    target,
    reconciled: inventorySum === target,
    reconcileLabel: `Position reconciled: ${inventorySum} / ${target}`,
    details,
  };
}

/** Legacy flow helper kept for tests / debug details. Prefer buildPositionInventoryDisplay. */
export function buildPositionFlowDisplay(block, targetBags) {
  if (!block) return null;
  const foldTotal = Number(block.folded_total ?? block.completed_total) || 0;
  const foldBlock = Number(block.folded_this_block ?? block.completed_this_block) || 0;
  const waiting = {
    to_sort: Math.max(0, Number(block.waiting_to_sort) || 0),
    to_wash: Math.max(0, Number(block.waiting_to_wash) || 0),
    to_dry: Math.max(0, Number(block.waiting_to_dry) || 0),
    to_fold: Math.max(0, Number(block.waiting_to_fold) || 0),
  };
  const inWashLabor = _blockInCycle(block, "in_wash_labor");
  const inDryLabor = _blockInCycle(block, "in_dry_labor");
  const inFoldLabor = _blockInCycle(block, "in_fold_labor");
  const washInCycle = _blockInCycle(block, "in_wash_cycle");
  const dryInCycle = _blockInCycle(block, "in_dry_cycle");
  const stages = {
    weigh: buildStagePositionDisplay({
      title: "WEIGH",
      thisBlock: block.weighed_this_block,
      stageTotal: block.weighed_total,
      targetBags,
    }),
    sort: buildStagePositionDisplay({
      title: "SORT",
      thisBlock: block.sorted_this_block,
      stageTotal: block.sorted_total,
      targetBags,
    }),
    wash: {
      ...buildStagePositionDisplay({
        title: "WASH",
        thisBlock: block.washed_this_block,
        stageTotal: block.washed_total,
        targetBags,
        inCycle: washInCycle,
      }),
      inCycleLabel: `${washInCycle} IN CYCLE`,
      waitingToEnter: waiting.to_wash,
      waitingToEnterLabel: `${waiting.to_wash} WAITING TO ENTER`,
      showMachineDetail: true,
    },
    dry: {
      ...buildStagePositionDisplay({
        title: "DRY",
        thisBlock: block.dried_this_block,
        stageTotal: block.dried_total,
        targetBags,
        inCycle: dryInCycle,
      }),
      inCycleLabel: `${dryInCycle} IN CYCLE`,
      waitingToEnter: waiting.to_dry,
      waitingToEnterLabel: `${waiting.to_dry} WAITING TO ENTER`,
      showMachineDetail: true,
    },
    fold: buildStagePositionDisplay({
      title: "FOLD",
      thisBlock: foldBlock,
      stageTotal: foldTotal,
      targetBags,
      completeLabel: true,
    }),
  };
  const inventory = buildPositionInventoryDisplay(block, targetBags);
  return {
    stages,
    waiting,
    inventory,
    reconcile: {
      sortToWash: formatStageReconcile({
        upstreamDone: stages.sort.done,
        waitingToEnter: waiting.to_wash,
        inCycle: washInCycle,
        inLabor: inWashLabor,
        stageDone: stages.wash.done,
        upstreamLabel: "Sort",
        stageLabel: "Wash",
      }),
      washToDry: formatStageReconcile({
        upstreamDone: stages.wash.done,
        waitingToEnter: waiting.to_dry,
        inCycle: dryInCycle,
        inLabor: inDryLabor,
        stageDone: stages.dry.done,
        upstreamLabel: "Wash",
        stageLabel: "Dry",
      }),
      dryToFold: formatStageReconcile({
        upstreamDone: stages.dry.done,
        waitingToEnter: waiting.to_fold,
        inCycle: 0,
        inLabor: inFoldLabor,
        stageDone: stages.fold.done,
        upstreamLabel: "Dry",
        stageLabel: "Fold",
      }),
    },
    hints: {
      to_sort: formatWaitingToSortHint(stages.weigh.done, stages.sort.done, waiting.to_sort),
      to_wash: waiting.to_wash > 0
        ? "Finished Sort, not yet entered Wash labor/cycle."
        : "0 waiting to enter Wash — sorted bags are in Wash or Wash DONE.",
      to_dry: waiting.to_dry > 0
        ? "Wash complete, not yet entered Dry labor/cycle."
        : "0 waiting to enter Dry — washed bags are in Dry or Dry DONE.",
      to_fold: waiting.to_fold > 0
        ? "Dry cycle finished, not yet folding."
        : "0 waiting to enter Fold.",
    },
  };
}

export function roleDisplayName(role) {
  const id = normalizeRole(role) || role;
  return ROLE_LABEL[id] || String(role || "").replace(/^\w/, (c) => c.toUpperCase());
}

/**
 * Manager-facing outcome from management_outcome + summary.
 */
export function formatManagementOutcome(result) {
  const outcome = result?.management_outcome || result?.summary?.management_outcome || {};
  const summary = result?.summary || {};
  const status = outcome.completion_status || "stalled";
  const targetBags = outcome.target_bags ?? summary.bags_folded_by_target;
  const completedByTarget = outcome.completed_by_target ?? outcome.bags_completed_by_target ?? 0;
  const projected = outcome.projected_finish || summary.final_completion_time;
  const blocking = outcome.first_blocking_role;
  const bagsCompleted = outcome.bags_completed ?? completedByTarget;

  if (status === "completed") {
    return {
      status: "completed",
      title: projected ? `Finish ${projected}` : "On track",
      detail: null,
      tone: "success",
      projected,
      completedByTarget: bagsCompleted,
      targetBags,
      statusLabel: projected ? `Finish ${projected}` : "Complete",
    };
  }

  if (status === "incomplete_by_target") {
    const lateMin = lateMinutesAfterTarget(result?.inputs?.target_time || result?.raw_inputs?.target_time, projected);
    return {
      status: "incomplete_by_target",
      title: lateMin != null ? `${lateMin} min late` : "After target",
      detail: null,
      tone: "warning",
      projected,
      completedByTarget,
      targetBags,
      statusLabel: lateMin != null ? `${lateMin} min late` : "After target",
    };
  }

  const roleLabel = blocking ? roleDisplayName(blocking) : null;
  let statusLabel = "Stalled";
  if (roleLabel) statusLabel = `Stalled at ${roleLabel}`;

  return {
    status: "stalled",
    title: statusLabel,
    detail: null,
    tone: "neutral",
    projected: null,
    completedByTarget,
    targetBags,
    firstBlockingRole: blocking,
    statusLabel,
  };
}

export function lateMinutesAfterTarget(targetTime, finishTime) {
  const a = parseClockToSec(targetTime);
  const b = parseClockToSec(finishTime);
  if (a == null || b == null || b <= a) return null;
  return Math.round((b - a) / 60);
}

export function earlyMinutesBeforeTarget(targetTime, finishTime) {
  const a = parseClockToSec(targetTime);
  const b = parseClockToSec(finishTime);
  if (a == null || b == null || b >= a) return null;
  return Math.round((a - b) / 60);
}

export function formatDeficitLines(deficits) {
  if (!Array.isArray(deficits) || !deficits.length) return [];
  return deficits.map((d) => {
    const role = roleDisplayName(d.role);
    const bags = d.blocked_bags;
    if (d.reason === "NO_STAFF_AVAILABLE") {
      return bags != null
        ? `No ${role} available · ${bags} bag${bags === 1 ? "" : "s"} waiting`
        : `No ${role} available`;
    }
    if (d.reason === "CAPACITY_EXHAUSTED") {
      return bags != null
        ? `${role} staffing insufficient · ${bags} bag${bags === 1 ? "" : "s"} remaining`
        : `${role} staffing ends with work remaining`;
    }
    return `${role} work waiting for staffing`;
  });
}

export function intervalsForRole(intervals, roleId) {
  return (intervals || []).filter((r) => normalizeRole(r.role) === roleId);
}
