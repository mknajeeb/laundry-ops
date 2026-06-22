import { OPERATIONAL_STRATEGIES } from "./constants";

export function calcLoadTotals(bagCount, orders2) {
  const n = Math.min(Math.max(0, Number(orders2) || 0), bagCount);
  const single = bagCount - n;
  return {
    orders2: n,
    orders1: single,
    washerLoads: n * 2 + single,
    dryerLoads: n * 2 + single,
  };
}

export function splitFromCounts(bagCount, orders2Wash, orders2Dry) {
  const wash = calcLoadTotals(bagCount, orders2Wash);
  const dry = calcLoadTotals(bagCount, orders2Dry);
  return { wash, dry };
}

export function applyOperationalStrategy(inputs, strategyValue) {
  const meta = OPERATIONAL_STRATEGIES.find((s) => s.value === strategyValue);
  if (!meta || strategyValue === "custom") return inputs;
  return {
    ...inputs,
    washing_strategy: meta.washing_strategy,
    weighing_mode: meta.weighing_mode,
    weighing_handled_by: meta.weighing_handled_by || inputs.weighing_handled_by,
    helper_rule: meta.helper_rule,
  };
}

export function buildPayload(inputs, { includeScenarios = false } = {}) {
  const bagCount = Number(inputs.bag_count) || 0;
  const body = { ...inputs };
  delete body.operational_strategy;
  delete body.orders_using_1_washers;
  delete body.orders_using_1_dryers;
  delete body.washer_person_count;

  body.helper_rule = inputs.helper_rule || "none";
  body.washer_person_count = Number(inputs.washer_person_count) || 1;
  body.batch_overrides = inputs.batch_overrides || [];

  body.orders_using_2_washers = Number(inputs.orders_using_2_washers) || 0;
  body.orders_using_2_dryers = Number(inputs.orders_using_2_dryers) || 0;

  ["weigher_count", "sorter_count"].forEach((k) => {
    if (body[k] === "" || body[k] == null) delete body[k];
    else body[k] = Number(body[k]);
  });

  const numericKeys = [
    "bag_count", "avg_lbs_per_bag", "washer_early_start_min",
    "washer_count", "dryer_count", "wash_cycle_min", "dry_cycle_min",
    "weigh_min_per_bag", "sort_min_per_bag", "fold_min_per_bag", "folder_count",
    "batch_size", "load_washer_min", "unload_washer_min", "load_dryer_min",
    "unload_dryer_min", "washer_transfer_min",
  ];
  numericKeys.forEach((k) => {
    body[k] = Number(body[k]);
  });

  if (includeScenarios) {
    body.include_scenario_comparisons = true;
  }
  return body;
}

export function formatBottleneck(value) {
  if (!value || value === "none") return "None";
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function mergeBatchOverride(overrides, patch) {
  const list = Array.isArray(overrides) ? [...overrides] : [];
  const filtered = list.filter(
    (o) => !(Number(o.batch_number) === Number(patch.batch_number) && o.apply_scope === patch.apply_scope),
  );
  filtered.push(patch);
  return filtered;
}

export function buildBatchOverride(batchNumber, applyScope, fields) {
  return {
    batch_number: batchNumber,
    apply_scope: applyScope,
    ...fields,
  };
}

export function applyScenarioPatch(inputs, patch) {
  const next = { ...inputs };
  Object.entries(patch).forEach(([key, value]) => {
    if (key === "operational_strategy") {
      next.operational_strategy = value;
      Object.assign(next, applyOperationalStrategy(next, value));
      return;
    }
    if (value === "+1") {
      next[key] = Number(next[key] || 0) + 1;
      return;
    }
    next[key] = value;
  });
  return next;
}
