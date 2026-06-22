export const DEFAULT_INPUTS = {
  start_time: "7:00 AM",
  target_time: "12:00 PM",
  bag_count: 50,
  avg_lbs_per_bag: 20,
  orders_using_1_washers: 10,
  orders_using_2_washers: 40,
  orders_using_1_dryers: 10,
  orders_using_2_dryers: 40,
  washer_count: 4,
  dryer_count: 4,
  wash_cycle_min: 30,
  dry_cycle_min: 45,
  weigh_min_per_bag: 1,
  sort_min_per_bag: 5,
  fold_min_per_bag: 6,
  folder_count: 3,
  weigher_count: "",
  sorter_count: "",
  washer_person_count: 1,
  weighing_handled_by: "dedicated_weigher",
  weighing_mode: "separate_lane",
  helper_rule: "none",
  washer_early_start_min: 0,
  washing_strategy: "batch_washing",
  operational_strategy: "continuous_batch",
  batch_size: 8,
  load_washer_min: 3,
  unload_washer_min: 3,
  load_dryer_min: 3,
  unload_dryer_min: 2,
  washer_transfer_min: 5,
  batch_overrides: [],
};

export const OPERATIONAL_STRATEGIES = [
  {
    value: "continuous_batch",
    label: "Continuous sorting + batch washing",
    washing_strategy: "batch_washing",
    weighing_mode: "separate_lane",
    helper_rule: "none",
  },
  {
    value: "weigh_all_first",
    label: "Weigh all first, then sort/wash",
    washing_strategy: "batch_washing",
    weighing_mode: "upfront",
    weighing_handled_by: "dedicated_weigher",
    helper_rule: "none",
  },
  {
    value: "sort_one_wash_one",
    label: "Sort one batch, wash one batch",
    washing_strategy: "batch_washing",
    weighing_mode: "separate_lane",
    helper_rule: "none",
  },
  {
    value: "washer_handles_transfer",
    label: "Washer person handles wash + dryer transfer",
    washing_strategy: "batch_washing",
    weighing_mode: "separate_lane",
    helper_rule: "none",
  },
  {
    value: "sorter_assists",
    label: "Sorter assists washer during transfers",
    washing_strategy: "batch_washing",
    weighing_mode: "separate_lane",
    helper_rule: "sorter_helps_washer",
  },
  {
    value: "custom",
    label: "Custom",
    washing_strategy: "batch_washing",
    weighing_mode: "separate_lane",
    helper_rule: "none",
  },
];

export const HELPER_RULES = [
  { value: "none", label: "No helper" },
  { value: "sorter_helps_washer", label: "Sorter helps washer during transfers" },
  { value: "sorter_helps_if_surplus", label: "Sorter helps only if sorting surplus above threshold" },
  { value: "washer_helps_folding", label: "Washer helps folding when idle" },
];

export const QUICK_SCENARIOS = [
  { key: "folder_plus", label: "+1 folder", patch: { folder_count: "+1" } },
  { key: "sorter_plus", label: "+1 sorter", patch: { sorter_count: "+1" } },
  { key: "batch_6", label: "Batch size 6", patch: { batch_size: 6 } },
  { key: "batch_8", label: "Batch size 8", patch: { batch_size: 8 } },
  { key: "batch_10", label: "Batch size 10", patch: { batch_size: 10 } },
  { key: "weigh_first", label: "Weigh all first", patch: { operational_strategy: "weigh_all_first" } },
];

export const PLANNER_TABS = ["Plan", "Results", "Compare"];
