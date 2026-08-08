/** Management planner defaults and role labels (management_mode always on). */

export const MANAGEMENT_ROLES = [
  { id: "weigher", label: "Weigh", short: "Weigh" },
  { id: "sorter", label: "Sort", short: "Sort" },
  { id: "washer", label: "Wash", short: "Wash" },
  { id: "dryer", label: "Dry", short: "Dry" },
  { id: "folder", label: "Fold", short: "Fold" },
];

export const ROLE_LABEL = Object.fromEntries(MANAGEMENT_ROLES.map((r) => [r.id, r.label]));

export const BLOCK_SIZE_OPTIONS = [
  { value: 30, label: "30 min" },
  { value: 45, label: "45 min" },
  { value: 60, label: "60 min" },
];

export const DEFAULT_MANAGEMENT_INPUTS = {
  bag_count: 50,
  start_time: "9:00 AM",
  target_time: "3:00 PM",
  end_time: "5:00 PM",
  planning_block_size_min: 60,
  washer_count: 4,
  dryer_count: 4,
  batch_size: 8,
  avg_lbs_per_bag: 20,
  // Authored intervals only — empty by default (no auto staff).
  staffing_intervals: [],
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
    end_time: "5:00 PM",
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
    end_time: "3:00 PM",
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
    end_time: "3:00 PM",
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
    end_time: "5:00 PM",
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
