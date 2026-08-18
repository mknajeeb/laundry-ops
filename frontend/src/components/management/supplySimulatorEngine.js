/** Shared Supply Cost Simulator math — mirrors backend.simulate_supply_cost */

export function normalizeDetergentPcts(tidePct, ultraPct) {
  const t = Math.max(0, Number(tidePct) || 0);
  const u = Math.max(0, Number(ultraPct) || 0);
  const s = t + u;
  if (s <= 0) return { tide: 100, ultra: 0 };
  return { tide: (t / s) * 100, ultra: (u / s) * 100 };
}

export function expectedCostPerLoad({
  tidePct,
  ultraCleanPct,
  downyPct,
  oxicleanPct,
  unitCosts = {},
}) {
  const { tide, ultra } = normalizeDetergentPcts(tidePct, ultraCleanPct);
  const cTide = Number(unitCosts.tide) || 0;
  const cUltra = Number(unitCosts.ultra_clean) || 0;
  const cDowny = Number(unitCosts.downy) || 0;
  const cOxi = Number(unitCosts.oxiclean) || 0;
  return (
    (tide / 100) * cTide
    + (ultra / 100) * cUltra
    + (Math.max(0, Number(downyPct) || 0) / 100) * cDowny
    + (Math.max(0, Number(oxicleanPct) || 0) / 100) * cOxi
  );
}

export function simulateSupplyCost({
  totalOrders,
  splitPct,
  avgLbPerBag,
  tidePct,
  ultraCleanPct,
  downyPct,
  oxicleanPct,
  unitCosts,
}) {
  const orders = Math.max(0, Math.floor(Number(totalOrders) || 0));
  const rate = Math.max(0, Math.min(1, (Number(splitPct) || 0) / 100));
  const avgLb = Math.max(0, Number(avgLbPerBag) || 0);
  const { tide, ultra } = normalizeDetergentPcts(tidePct, ultraCleanPct);
  const dPct = Math.max(0, Math.min(100, Number(downyPct) || 0));
  const oPct = Math.max(0, Math.min(100, Number(oxicleanPct) || 0));

  let splitOrders = Math.round(orders * rate);
  if (splitOrders > orders) splitOrders = orders;
  const nonSplit = orders - splitOrders;
  const totalLoads = nonSplit + splitOrders * 2;
  const estimatedLbs = Math.round(orders * avgLb * 10) / 10;
  const cpl = expectedCostPerLoad({
    tidePct: tide,
    ultraCleanPct: ultra,
    downyPct: dPct,
    oxicleanPct: oPct,
    unitCosts,
  });
  const totalCost = Math.round(totalLoads * cpl * 100) / 100;

  return {
    total_orders: orders,
    split_pct: Math.round(rate * 10000) / 100,
    split_orders: splitOrders,
    non_split_orders: nonSplit,
    total_loads: totalLoads,
    avg_lb_per_bag: Math.round(avgLb * 100) / 100,
    estimated_lbs: estimatedLbs,
    mix: {
      tide_pct: Math.round(tide * 100) / 100,
      ultra_clean_pct: Math.round(ultra * 100) / 100,
      downy_pct: dPct,
      oxiclean_pct: oPct,
    },
    cost_per_load_expected: Math.round(cpl * 10000) / 10000,
    estimated_supply_cost: totalCost,
    cost_per_order: orders ? Math.round((totalCost / orders) * 10000) / 10000 : null,
    cost_per_load: totalLoads ? Math.round((totalCost / totalLoads) * 10000) / 10000 : null,
    est_cost_per_lb:
      estimatedLbs > 0 ? Math.round((totalCost / estimatedLbs) * 10000) / 10000 : null,
  };
}

export function periodSavings(dollarSavingsPerShift, shiftsPerWeek = 7) {
  const shift = Math.round((Number(dollarSavingsPerShift) || 0) * 100) / 100;
  const spw = Math.max(0, Number(shiftsPerWeek) || 0);
  const weekly = Math.round(shift * spw * 100) / 100;
  const monthly = Math.round(((weekly * 52) / 12) * 100) / 100;
  return {
    shifts_per_week: spw,
    per_shift: shift,
    per_day: shift,
    per_week: weekly,
    per_month: monthly,
  };
}

export function compareScenarios(current, target, shiftsPerWeek = 7) {
  const loadsSaved = (current.total_loads || 0) - (target.total_loads || 0);
  const dollarSavings =
    Math.round(
      ((current.estimated_supply_cost || 0) - (target.estimated_supply_cost || 0)) * 100,
    ) / 100;
  return {
    loads_saved: loadsSaved,
    dollar_savings: dollarSavings,
    period_savings: periodSavings(dollarSavings, shiftsPerWeek),
  };
}

/** Build Shift preset from live Management supplies summary (client-side). */
export function buildShiftPresetFromSupplies(supplies, { selectedDateEt, todayWorkloadOrders } = {}) {
  const dash = supplies?.dashboard || {};
  const pop = supplies?.population || {};
  const products = supplies?.products || [];

  const orders = Number(
    todayWorkloadOrders
      ?? dash.workload_orders
      ?? dash.unique_orders
      ?? pop.workload_orders
      ?? pop.orders
      ?? 0,
  );

  const splitY = Number(dash.confirmed_split_orders ?? pop.confirmed_split_orders ?? 0);
  const splitN = Number(dash.confirmed_not_split_orders ?? pop.confirmed_not_split_orders ?? 0);
  const finalized = splitY + splitN;
  const splitPct = finalized ? Math.round((splitY / finalized) * 10000) / 100 : 0;

  const preLbs = pop.pre_weight_lbs != null ? Number(pop.pre_weight_lbs) : null;
  const preN = Number(pop.pre_weight_bag_count || 0);
  const avgLb = preLbs != null && preN > 0 ? Math.round((preLbs / preN) * 100) / 100 : 20;

  let tideN = 0;
  let ultraN = 0;
  let downyN = 0;
  let oxiN = 0;
  const unitCosts = { tide: null, ultra_clean: null, downy: null, oxiclean: null };

  for (const p of products) {
    const legacy = String(p.legacy_report_key || "").trim();
    const st = String(p.supply_type || "").toUpperCase();
    const n = Number(p.orders_using ?? p.orders ?? 0);
    const cpd = p.cost_per_dose != null ? Number(p.cost_per_dose) : null;
    if (st === "DETERGENT" || legacy === "Tide") {
      tideN = n;
      unitCosts.tide = cpd;
    } else if (
      st === "HYPOALLERGENIC_DETERGENT"
      || legacy === "Kirkland"
      || legacy === "All Free & Clear"
    ) {
      ultraN = n;
      unitCosts.ultra_clean = cpd;
    } else if (st === "FABRIC_SOFTENER" || legacy === "Downy") {
      downyN = n;
      unitCosts.downy = cpd;
    } else if (st === "BOOSTER_OXI" || legacy === "OxiClean") {
      oxiN = n;
      unitCosts.oxiclean = cpd;
    }
  }

  const detTotal = tideN + ultraN;
  const tidePct = detTotal > 0 ? Math.round((tideN / detTotal) * 10000) / 100 : 100;
  const ultraPct = detTotal > 0 ? Math.round((ultraN / detTotal) * 10000) / 100 : 0;
  const base = orders > 0 ? orders : 1;
  const downyPct = Math.round((downyN / base) * 10000) / 100;
  const oxiPct = Math.round((oxiN / base) * 10000) / 100;

  return {
    available: true,
    mode: "shift",
    date_et: selectedDateEt || null,
    unit_costs: unitCosts,
    defaults: {
      total_orders: orders || 100,
      split_pct: splitPct,
      avg_lb_per_bag: avgLb,
      tide_pct: tidePct,
      ultra_clean_pct: ultraPct,
      downy_pct: downyPct,
      oxiclean_pct: oxiPct,
      shifts_per_week: 7,
    },
  };
}
