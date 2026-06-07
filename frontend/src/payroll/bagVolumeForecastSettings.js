/**
 * Bag Volume Labor Forecast — settings schema (Phase 1: store only, no scheduling UI math).
 */

export const FORECAST_METHODS = [
  { id: "planning", label: "Planning parameters" },
  { id: "actual", label: "Actual performance average" },
  { id: "compare", label: "Compare both" },
];

export const UNIT_TYPES = [
  { id: "bags_per_hour", label: "Bags / hour" },
  { id: "pounds_per_hour", label: "Pounds / hour" },
  { id: "minutes_per_bag", label: "Minutes / bag" },
  { id: "minutes_per_order", label: "Minutes / order" },
];

export const TARGET_COMPLETION_OPTIONS = [
  { id: "same_day", label: "Same day" },
  { id: "next_day", label: "Next day" },
  { id: "flexible", label: "Flexible" },
];

export function defaultBagVolumeForecast() {
  return {
    schema_version: 1,
    calculations_enabled: false,
    default_method: "compare",
    global_defaults: {
      average_bag_weight_lbs: 20,
      target_completion: "same_day",
      default_bag_count: 100,
      notes: "",
    },
    role_speed_parameters: [],
    performance_link: {
      use_rinse_folding_productivity: true,
      lookback_days: 30,
      fallback_to_planning_when_no_data: true,
    },
  };
}

export function normalizeBagVolumeForecast(raw, legacyForecast = {}) {
  const base = defaultBagVolumeForecast();
  if (!raw || typeof raw !== "object") {
    raw = {};
  }
  const out = {
    ...base,
    ...raw,
    global_defaults: { ...base.global_defaults, ...(raw.global_defaults || {}) },
    performance_link: { ...base.performance_link, ...(raw.performance_link || {}) },
    role_speed_parameters: Array.isArray(raw.role_speed_parameters)
      ? raw.role_speed_parameters.map(normalizeRoleSpeedRow)
      : [],
  };
  if (legacyForecast?.average_rinse_bag_weight_lbs != null && !out.global_defaults.average_bag_weight_lbs) {
    out.global_defaults.average_bag_weight_lbs = Number(legacyForecast.average_rinse_bag_weight_lbs);
  }
  return out;
}

export function normalizeRoleSpeedRow(row) {
  return {
    id: row.id ?? `rsp-${row.role_id}-${row.work_stream_id || 0}-${row.unit_type}`,
    role_id: row.role_id ?? "",
    work_stream_id: row.work_stream_id ?? "",
    role_name: row.role_name || "",
    work_stream_name: row.work_stream_name || "",
    unit_type: row.unit_type || "bags_per_hour",
    planning_speed: row.planning_speed ?? "",
    active: row.active !== false,
    notes: row.notes || "",
  };
}

export function newRoleSpeedRow(roles = [], streams = []) {
  const folder = roles.find((r) => /folder/i.test(r.name));
  const rinse = streams.find((s) => /rinse/i.test(s.name));
  return normalizeRoleSpeedRow({
    role_id: folder?.id || roles[0]?.id || "",
    work_stream_id: rinse?.id || streams[0]?.id || "",
    role_name: folder?.name || "",
    work_stream_name: rinse?.name || "",
    unit_type: "bags_per_hour",
    planning_speed: 4,
    active: true,
    notes: "",
  });
}

/** Phase 2 — client-side forecast stub (not used on scheduling screen). */
export function computeBagVolumeForecastStub(bagForecast, { bagCount = 100, method } = {}) {
  if (!bagForecast?.calculations_enabled) {
    return {
      status: "disabled",
      message:
        "Bag volume forecast is configured in Settings only. Enable calculations in a future release to see required workers and hours on Scheduling.",
      bag_count: bagCount,
      method: method || bagForecast?.default_method,
    };
  }
  return { status: "not_implemented", message: "Forecast engine not implemented yet." };
}
