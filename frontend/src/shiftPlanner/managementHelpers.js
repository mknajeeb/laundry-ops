/**
 * Management planner helpers.
 * Frontend validates for immediate feedback; backend remains authoritative.
 * Does not recreate staffing normalization or DES logic.
 */

import { MANAGEMENT_ROLES, ROLE_LABEL } from "./managementConstants";

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

/** Base people covering the start of a block for a role. */
export function getBasePeopleForBlock(intervals, roleId, blockStart) {
  const bs = parseClockToSec(blockStart);
  if (bs == null) return 0;
  for (const row of intervals || []) {
    if (normalizeRole(row.role) !== roleId) continue;
    if (String(row.mode || "base").toLowerCase() === "additional") continue;
    const s = parseClockToSec(row.start);
    const e = parseClockToSec(row.end);
    if (s == null || e == null) continue;
    if (s <= bs && bs < e) return Number(row.people) || 0;
  }
  return 0;
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
  const intervals = (inputs.staffing_intervals || []).map((row) => ({
    role: normalizeRole(row.role) || row.role,
    people: Number(row.people),
    start: row.start,
    end: row.end,
    mode: String(row.mode || "base").toLowerCase() === "additional" ? "additional" : "base",
  }));

  // Horizon = start → target finish. Backend still accepts end_time; map it internally.
  const target = inputs.target_time;

  return {
    engine: "bag_des_v2",
    management_mode: true,
    start_time: inputs.start_time,
    target_time: target,
    end_time: target,
    planning_block_size_min: Number(inputs.planning_block_size_min) || 60,
    summary_interval_min: Number(inputs.planning_block_size_min) || 60,
    bag_count: Number(inputs.bag_count) || 1,
    avg_lbs_per_bag: Number(inputs.avg_lbs_per_bag) || 20,
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

export function formatStageProgress(label, total, thisBlock) {
  const t = Number(total) || 0;
  const d = Number(thisBlock) || 0;
  if (d > 0) return `${label} ${t} (+${d} this block)`;
  return `${label} ${t}`;
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
