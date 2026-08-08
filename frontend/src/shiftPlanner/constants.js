export const DEFAULT_EMPLOYEES = [
  {
    id: "E-WEIGH-1",
    name: "Weigher 1",
    primary_role: "weigher",
    start_time: "7:00 AM",
    end_time: "3:00 PM",
    secondary_roles: [],
    active: true,
  },
  {
    id: "E-SORT-1",
    name: "Sorter 1",
    primary_role: "sorter",
    start_time: "7:00 AM",
    end_time: "3:00 PM",
    secondary_roles: [],
    active: true,
  },
  {
    id: "E-WASH-1",
    name: "Washer 1",
    primary_role: "washer",
    start_time: "7:00 AM",
    end_time: "3:00 PM",
    secondary_roles: [],
    active: true,
  },
  {
    id: "E-FOLD-1",
    name: "Folder 1",
    primary_role: "folder",
    start_time: "7:00 AM",
    end_time: "3:00 PM",
    secondary_roles: [],
    fold_lbs_per_hour: 35,
    active: true,
  },
  {
    id: "E-FOLD-2",
    name: "Folder 2",
    primary_role: "folder",
    start_time: "8:00 AM",
    end_time: "3:00 PM",
    secondary_roles: [],
    fold_lbs_per_hour: 40,
    active: true,
  },
  {
    id: "E-FOLD-3",
    name: "Folder 3",
    primary_role: "folder",
    start_time: "9:30 AM",
    end_time: "2:00 PM",
    secondary_roles: [],
    fold_lbs_per_hour: 35,
    active: true,
  },
];

export const DEFAULT_INPUTS = {
  engine: "bag_des_v2",
  start_time: "7:00 AM",
  target_time: "12:00 PM",
  bag_count: 50,
  avg_lbs_per_bag: 20,
  bag_weights_text: "",
  washer_count: 4,
  dryer_count: 4,
  washer_capacity_lb: 80,
  dryer_capacity_lb: 80,
  batch_size: 8,
  batch_limit_mode: "whichever_first",
  summary_interval_min: 30,
  weigh_min_per_bag: 1,
  sort_min_per_bag: 5,
  load_washer_min: 3,
  unload_transfer_min: 5,
  wash_cycle_min: 30,
  load_dryer_min: 3,
  unload_dryer_min: 0,
  dry_cycle_min: 45,
  fold_rate_mode: "lbs_per_hour",
  fold_min_per_bag: 6,
  fold_lbs_per_hour: 35,
  weigher_washer_same: false,
  weigher_sorter_same: false,
  sorter_washer_same: false,
  washer_folder_same: false,
  employees: DEFAULT_EMPLOYEES,
  orders: [],
  batch_overrides: [],
  sim_mode: "reoptimize_full",
  exit_policy: "finish_current",
};

export const ROLE_OPTIONS = [
  { value: "weigher", label: "Weigher" },
  { value: "sorter", label: "Sorter" },
  { value: "washer", label: "Washer person" },
  { value: "folder", label: "Folder" },
  { value: "helper", label: "Helper" },
];

export const BATCH_LIMIT_MODES = [
  { value: "bags", label: "Fixed number of bags" },
  { value: "pounds", label: "Limited by machine weight capacity" },
  { value: "whichever_first", label: "Whichever limit is reached first" },
];

export const FOLD_RATE_MODES = [
  { value: "lbs_per_hour", label: "Pounds per hour" },
  { value: "minutes_per_bag", label: "Minutes per bag" },
];

// Legacy command-board exports (kept so unused panels import cleanly).
export const STRATEGY_FLAGS = [
  { key: "continuous_sorting", label: "Continuous sorting" },
  { key: "weigh_all_first", label: "Weigh all first" },
  { key: "batch_washing", label: "Batch washing" },
  { key: "sorter_helps_washer", label: "Sorter can help washer" },
  { key: "washer_helps_folding", label: "Washer helps folding when idle" },
  { key: "sorter_helps_if_surplus", label: "Sorter helps when surplus ≥ 1 batch" },
  { key: "prioritize_folded", label: "Prioritize folded by target" },
  { key: "prioritize_ready", label: "Prioritize ready by target" },
];

export const HELPER_ASSIGN_OPTIONS = [
  { value: "none", label: "None" },
  { value: "sorter", label: "Sorter → washer transfer" },
  { value: "folder", label: "Folder → washer transfer" },
  { value: "extra_washer", label: "+1 washer helper" },
];
