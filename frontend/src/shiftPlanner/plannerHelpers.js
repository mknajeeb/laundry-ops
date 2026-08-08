export function parseBagWeightsText(text) {
  if (!text || !String(text).trim()) return [];
  return String(text)
    .split(/[\s,;]+/)
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0);
}

export function buildPayload(inputs) {
  const body = {
    engine: "bag_des_v2",
    start_time: inputs.start_time,
    target_time: inputs.target_time,
    bag_count: Number(inputs.bag_count) || 1,
    avg_lbs_per_bag: Number(inputs.avg_lbs_per_bag) || 20,
    washer_count: Number(inputs.washer_count) || 1,
    dryer_count: Number(inputs.dryer_count) || 1,
    washer_capacity_lb: Number(inputs.washer_capacity_lb) || 80,
    dryer_capacity_lb: Number(inputs.dryer_capacity_lb) || 80,
    batch_size: Number(inputs.batch_size) || 8,
    batch_limit_mode: inputs.batch_limit_mode || "whichever_first",
    weigh_min_per_bag: Number(inputs.weigh_min_per_bag) || 1,
    sort_min_per_bag: Number(inputs.sort_min_per_bag) || 5,
    load_washer_min: Number(inputs.load_washer_min) || 3,
    unload_transfer_min: Number(inputs.unload_transfer_min) || 5,
    wash_cycle_min: Number(inputs.wash_cycle_min) || 30,
    load_dryer_min: Number(inputs.load_dryer_min) || 3,
    unload_dryer_min: Number(inputs.unload_dryer_min) || 0,
    dry_cycle_min: Number(inputs.dry_cycle_min) || 45,
    fold_rate_mode: inputs.fold_rate_mode || "lbs_per_hour",
    fold_min_per_bag: Number(inputs.fold_min_per_bag) || 6,
    fold_lbs_per_hour: Number(inputs.fold_lbs_per_hour) || 35,
    weigher_washer_same: Boolean(inputs.weigher_washer_same),
    weigher_sorter_same: Boolean(inputs.weigher_sorter_same),
    sorter_washer_same: Boolean(inputs.sorter_washer_same),
    washer_folder_same: Boolean(inputs.washer_folder_same),
    employees: (inputs.employees || [])
      .filter((e) => e && e.active !== false)
      .map((e) => ({
        ...e,
        secondary_roles: e.secondary_roles || [],
        role_schedule: (e.role_schedule || [])
          .filter((w) => w && w.role && (w.from || w.start_time))
          .map((w) => ({
            role: w.role,
            from: w.from || w.start_time,
            to: w.to || w.end_time || undefined,
          })),
        fold_lbs_per_hour: e.fold_lbs_per_hour != null && e.fold_lbs_per_hour !== ""
          ? Number(e.fold_lbs_per_hour)
          : undefined,
        weigh_min_per_bag: e.weigh_min_per_bag != null && e.weigh_min_per_bag !== ""
          ? Number(e.weigh_min_per_bag)
          : undefined,
        sort_min_per_bag: e.sort_min_per_bag != null && e.sort_min_per_bag !== ""
          ? Number(e.sort_min_per_bag)
          : undefined,
        load_washer_min: e.load_washer_min != null && e.load_washer_min !== ""
          ? Number(e.load_washer_min)
          : undefined,
        transfer_min: e.transfer_min != null && e.transfer_min !== ""
          ? Number(e.transfer_min)
          : undefined,
        load_dryer_min: e.load_dryer_min != null && e.load_dryer_min !== ""
          ? Number(e.load_dryer_min)
          : undefined,
      })),
    orders: (inputs.orders || []).map((o) => ({
      order_number: o.order_number,
      bag_count: Number(o.bag_count) || 1,
      weights: Array.isArray(o.weights)
        ? o.weights.map(Number).filter((n) => Number.isFinite(n))
        : parseBagWeightsText(o.weights_text),
      total_weight: o.total_weight != null && o.total_weight !== "" ? Number(o.total_weight) : undefined,
      two_washer: Boolean(o.two_washer),
      two_dryer: Boolean(o.two_dryer),
      rush: Boolean(o.rush),
      required_complete_time: o.required_complete_time || undefined,
    })),
    batch_overrides: inputs.batch_overrides || [],
    sim_mode: inputs.sim_mode || "reoptimize_full",
    exit_policy: inputs.exit_policy || "finish_current",
  };

  const weights = parseBagWeightsText(inputs.bag_weights_text);
  if (weights.length) body.bag_weights = weights;

  if (inputs.continue_from_time) body.continue_from_time = inputs.continue_from_time;
  if (inputs.apply_action) body.apply_action = inputs.apply_action;

  return body;
}

export function formatBottleneck(value) {
  if (!value || value === "none") return "—";
  return String(value);
}

export function newEmployee(role = "sorter", startTime = "8:30 AM") {
  const id = `E-NEW-${Date.now()}`;
  return {
    id,
    name: `${role.charAt(0).toUpperCase()}${role.slice(1)} (new)`,
    primary_role: role,
    start_time: startTime,
    end_time: "3:00 PM",
    secondary_roles: [],
    role_schedule: [],
    active: true,
    fold_lbs_per_hour: role === "folder" ? 35 : undefined,
  };
}

export function newOrder(index = 1) {
  return {
    order_number: `ORD-${index}`,
    bag_count: 3,
    weights_text: "",
    total_weight: "",
    two_washer: false,
    two_dryer: false,
    rush: false,
    required_complete_time: "",
  };
}

export function summaryDelta(before, after) {
  if (!before || !after) return null;
  const keys = [
    "bags_ready_by_target",
    "bags_folded_by_target",
    "first_batch_ready_time",
    "final_completion_time",
    "primary_bottleneck",
  ];
  const out = {};
  keys.forEach((k) => {
    out[k] = { before: before[k], after: after[k] };
  });
  return out;
}

export function emptyBatchOverrideDraft(batch) {
  return {
    batch_number: batch?.batch_number || 1,
    apply_scope: "this_batch_only",
    bag_ids_text: (batch?.bag_ids || []).join(", "),
    batch_size: batch?.bags || batch?.total_bags || "",
    max_pounds: "",
    washer_id: batch?.washer_id || "",
    dryer_id: batch?.dryer_id || "",
    washer_person_id: "",
    transfer_person_id: "",
    dryer_load_person_id: "",
    priority: "",
    extra_helper_id: "",
    sorter_helps_washer: false,
    folder_helps_washer: false,
    sorting_paused: false,
    planned_start_time: "",
    strict_resource_lock: false,
  };
}

export function batchOverrideFromDraft(draft) {
  const bagIds = String(draft.bag_ids_text || "")
    .split(/[\s,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const out = {
    batch_number: Number(draft.batch_number),
    apply_scope: draft.apply_scope || "this_batch_only",
    sorter_helps_washer: Boolean(draft.sorter_helps_washer),
    folder_helps_washer: Boolean(draft.folder_helps_washer),
    sorting_paused: Boolean(draft.sorting_paused),
    strict_resource_lock: Boolean(draft.strict_resource_lock),
  };
  if (bagIds.length) out.bag_ids = bagIds;
  if (draft.batch_size !== "" && draft.batch_size != null) out.batch_size = Number(draft.batch_size);
  if (draft.max_pounds !== "" && draft.max_pounds != null) out.max_pounds = Number(draft.max_pounds);
  if (draft.washer_id) out.washer_id = draft.washer_id;
  if (draft.dryer_id) out.dryer_id = draft.dryer_id;
  if (draft.washer_person_id) out.washer_person_id = draft.washer_person_id;
  if (draft.transfer_person_id) out.transfer_person_id = draft.transfer_person_id;
  if (draft.dryer_load_person_id) out.dryer_load_person_id = draft.dryer_load_person_id;
  if (draft.extra_helper_id) out.extra_helper_id = draft.extra_helper_id;
  if (draft.priority !== "" && draft.priority != null) out.priority = Number(draft.priority);
  if (draft.planned_start_time) out.planned_start_time = draft.planned_start_time;
  return out;
}

export function upsertBatchOverride(overrides, patch) {
  const list = Array.isArray(overrides) ? [...overrides] : [];
  const filtered = list.filter(
    (o) => !(Number(o.batch_number) === Number(patch.batch_number) && (o.apply_scope || "this_batch_only") === (patch.apply_scope || "this_batch_only")),
  );
  filtered.push(patch);
  return filtered;
}

export function resetBatchOverrides(overrides, batchNumber) {
  return (overrides || []).filter((o) => Number(o.batch_number) !== Number(batchNumber));
}
