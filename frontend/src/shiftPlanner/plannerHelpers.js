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

export function buildPayload(inputs) {
  const body = { ...inputs };
  delete body.orders_using_1_washers;
  delete body.orders_using_1_dryers;

  body.helper_rule = inputs.helper_rule || "none";
  body.washer_person_count = Number(inputs.washer_person_count) || 1;
  body.batch_overrides = inputs.batch_overrides || [];
  body.strategy_flags = inputs.strategy_flags || [];
  body.orders_using_2_washers = Number(inputs.orders_using_2_washers) || 0;
  body.orders_using_2_dryers = Number(inputs.orders_using_2_dryers) || 0;

  ["weigher_count", "sorter_count"].forEach((k) => {
    if (body[k] === "" || body[k] == null) delete body[k];
    else body[k] = Number(body[k]);
  });

  [
    "bag_count", "avg_lbs_per_bag", "washer_count", "dryer_count",
    "wash_cycle_min", "dry_cycle_min", "weigh_min_per_bag", "sort_min_per_bag",
    "fold_min_per_bag", "folder_count", "batch_size", "load_washer_min",
    "unload_washer_min", "load_dryer_min", "unload_dryer_min", "washer_transfer_min",
  ].forEach((k) => {
    body[k] = Number(body[k]);
  });

  return body;
}

export function formatBottleneck(value) {
  if (!value || value === "none") return "—";
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
  return { batch_number: batchNumber, apply_scope: applyScope, ...fields };
}

export function helperFieldsFromAssignment(assignment) {
  switch (assignment) {
    case "sorter":
      return { sorter_helps_washer: true };
    case "folder":
      return { folder_helps_washer: true };
    case "extra_washer":
      return { extra_washer_helpers: 1 };
    default:
      return {};
  }
}

export function commandBoardFromResult(result) {
  return result?.operational?.command_board || null;
}

export function isCommandBoardValid(board) {
  if (!board?.simulation_valid) return false;
  const rows = board.batch_timeline || [];
  if (!rows.length) return false;
  return rows.some((r) => r.wash_start || r.sort_end);
}
