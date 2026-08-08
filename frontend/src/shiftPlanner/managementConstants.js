/** Management planner defaults and role labels (management_mode always on). */

export const MANAGEMENT_ROLES = [
  { id: "weigher", label: "Weigh", short: "Weigh" },
  { id: "sorter", label: "Sort", short: "Sort" },
  { id: "washer", label: "Wash", short: "Wash" },
  { id: "dryer", label: "Dry", short: "Dry" },
  { id: "folder", label: "Fold", short: "Fold" },
];

export const ROLE_LABEL = Object.fromEntries(MANAGEMENT_ROLES.map((r) => [r.id, r.label]));

/** Block-level hybrid staffing: one person, multiple qualified roles, one calendar. */
export const MANAGEMENT_HYBRIDS = [
  { id: "weigh_wash", label: "Weigh / Wash", roles: ["weigher", "washer"] },
  { id: "wash_dry", label: "Wash / Dry", roles: ["washer", "dryer"] },
  { id: "weigh_wash_dry", label: "Weigh / Wash / Dry", roles: ["weigher", "washer", "dryer"] },
];

export const BLOCK_SIZE_OPTIONS = [
  { value: 30, label: "30 min" },
  { value: 45, label: "45 min" },
  { value: 60, label: "60 min" },
];

/** Engine management defaults — exposed as Process Parameters in the UI. */
export const DEFAULT_PROCESS_PARAMS = {
  weigh_sec_per_bag: 45,
  sort_min_per_bag: 5,
  load_washer_min: 3,
  wash_cycle_min: 30,
  load_dryer_min: 3,
  dry_cycle_min: 45,
  fold_min_per_bag: 6,
};

/** Org-persisted Plan / Machines / Process fields (not staffing or sim output). */
export const PERSISTED_PLANNER_PARAM_KEYS = [
  "bag_count",
  "start_time",
  "target_time",
  "planning_block_size_min",
  "washer_count",
  "dryer_count",
  "weigh_sec_per_bag",
  "sort_min_per_bag",
  "load_washer_min",
  "wash_cycle_min",
  "load_dryer_min",
  "dry_cycle_min",
  "fold_min_per_bag",
];

/** Extra strip fields locked with Edit Parameters but not persisted. */
export const SESSION_PLANNER_PARAM_KEYS = [
  "avg_lbs_per_bag",
  "two_washer_split_pct",
  "two_dryer_split_pct",
];

export const DEFAULT_MANAGEMENT_INPUTS = {
  bag_count: 50,
  start_time: "9:00 AM",
  target_time: "3:00 PM",
  planning_block_size_min: 60,
  washer_count: 4,
  dryer_count: 4,
  batch_size: 8,
  avg_lbs_per_bag: 20,
  // Validated planner default: 80% of bags use 2 machine positions.
  two_washer_split_pct: 80,
  two_dryer_split_pct: 80,
  ...DEFAULT_PROCESS_PARAMS,
  // Authored intervals only — empty by default (no auto staff).
  staffing_intervals: [],
  // Hybrid block staffing: { id, hybrid, people, start, end, mode: "base" }
  hybrid_intervals: [],
};

export function newStaffingInterval(role = "sorter", overrides = {}) {
  return {
    id: `si-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role,
    people: 1,
    start: "9:00 AM",
    end: "3:00 PM",
    mode: "base",
    ...overrides,
  };
}

function si(role, people, start, end, mode = "base") {
  return {
    id: `si-${role}-${mode}-${start}-${end}-${people}`.replace(/\s+/g, ""),
    role,
    people,
    start,
    end,
    mode,
  };
}

/** Named review scenarios for owner screenshots / local preview. */
export const MANAGEMENT_REVIEW_SCENARIOS = {
  empty: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 50,
    staffing_intervals: [],
  },
  completed: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 20,
    target_time: "3:00 PM",
    staffing_intervals: [
      si("weigher", 1, "9:00 AM", "3:00 PM"),
      si("sorter", 2, "9:00 AM", "3:00 PM"),
      si("washer", 1, "9:00 AM", "3:00 PM"),
      si("dryer", 1, "9:00 AM", "3:00 PM"),
      si("folder", 2, "9:00 AM", "3:00 PM"),
    ],
  },
  additional_sort: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 20,
    target_time: "12:00 PM",
    planning_block_size_min: 60,
    staffing_intervals: [
      si("weigher", 1, "9:00 AM", "12:00 PM"),
      si("sorter", 1, "9:00 AM", "12:00 PM"),
      si("sorter", 1, "9:15 AM", "9:45 AM", "additional"),
      si("washer", 1, "9:00 AM", "12:00 PM"),
      si("dryer", 1, "9:00 AM", "12:00 PM"),
      si("folder", 1, "9:00 AM", "12:00 PM"),
    ],
  },
  no_wash: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 20,
    target_time: "12:00 PM",
    staffing_intervals: [
      si("weigher", 1, "9:00 AM", "12:00 PM"),
      si("sorter", 1, "9:00 AM", "12:00 PM"),
      si("dryer", 1, "9:00 AM", "12:00 PM"),
      si("folder", 1, "9:00 AM", "12:00 PM"),
    ],
  },
  finishes_late: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 24,
    start_time: "9:00 AM",
    target_time: "10:00 AM",
    staffing_intervals: [
      si("weigher", 1, "9:00 AM", "3:00 PM"),
      si("sorter", 1, "9:00 AM", "3:00 PM"),
      si("washer", 1, "9:00 AM", "3:00 PM"),
      si("dryer", 1, "9:00 AM", "3:00 PM"),
      si("folder", 1, "9:00 AM", "3:00 PM"),
    ],
  },
  blocks_60: {
    ...DEFAULT_MANAGEMENT_INPUTS,
    bag_count: 20,
    planning_block_size_min: 60,
    staffing_intervals: [
      si("weigher", 1, "9:00 AM", "3:00 PM"),
      si("sorter", 2, "9:00 AM", "3:00 PM"),
      si("sorter", 1, "9:15 AM", "9:45 AM", "additional"),
      si("washer", 1, "9:00 AM", "3:00 PM"),
      si("dryer", 1, "9:00 AM", "3:00 PM"),
      si("folder", 2, "9:00 AM", "3:00 PM"),
    ],
  },
};
