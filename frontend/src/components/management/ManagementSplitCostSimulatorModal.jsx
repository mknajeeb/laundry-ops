import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { useTheme } from "@mui/material/styles";
import { getManagementSplitCostSimulatorBaseline } from "../../api";

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtMoney(v, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function fmtPct(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(digits)}%`;
}

function fmtLb(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

/** Pure client sim — mirrors backend.management_split_cost_simulator.simulate_split_cost */
function simulateSplitCost({ totalOrders, splitRate, avgLbPerBag, combinations }) {
  const orders = Math.max(0, Math.floor(Number(totalOrders) || 0));
  const rate = Math.max(0, Math.min(1, Number(splitRate) || 0));
  const avgLb = Math.max(0, Number(avgLbPerBag) || 0);
  let splitOrders = Math.round(orders * rate);
  if (splitOrders > orders) splitOrders = orders;
  const nonSplitOrders = orders - splitOrders;
  const totalLoads = nonSplitOrders + splitOrders * 2;
  const estimatedLbs = Math.round(orders * avgLb * 10) / 10;

  const raw = (combinations || []).map((c) => ({
    c,
    share: Math.max(0, Number(c.share) || 0),
  }));
  const shareSum = raw.reduce((s, r) => s + r.share, 0) || 1;

  let assigned = 0;
  let totalCost = 0;
  const comboRows = raw.map((r, i) => {
    const norm = r.share / shareSum;
    let cOrders;
    if (i === raw.length - 1) {
      cOrders = Math.max(0, orders - assigned);
    } else {
      cOrders = Math.round(orders * norm);
      assigned += cOrders;
    }
    let cSplit = Math.round(cOrders * rate);
    if (cSplit > cOrders) cSplit = cOrders;
    const cNon = cOrders - cSplit;
    const cLoads = cNon + cSplit * 2;
    const cpl = Number(r.c.cost_per_load) || 0;
    const cCost = Math.round(cLoads * cpl * 100) / 100;
    totalCost += cCost;
    return {
      key: r.c.key || r.c.label,
      label: r.c.label || r.c.key,
      share: norm,
      share_pct: Math.round(norm * 10000) / 100,
      estimated_orders: cOrders,
      estimated_loads: cLoads,
      cost_per_load: cpl,
      estimated_cost: cCost,
      products: r.c.products || [],
    };
  });

  totalCost = Math.round(totalCost * 100) / 100;
  return {
    total_orders: orders,
    split_rate: rate,
    split_pct: Math.round(rate * 10000) / 100,
    split_orders: splitOrders,
    non_split_orders: nonSplitOrders,
    total_loads: totalLoads,
    avg_lb_per_bag: Math.round(avgLb * 100) / 100,
    estimated_lbs: estimatedLbs,
    estimated_supply_cost: totalCost,
    cost_per_order: orders ? Math.round((totalCost / orders) * 10000) / 10000 : null,
    cost_per_load: totalLoads ? Math.round((totalCost / totalLoads) * 10000) / 10000 : null,
    est_cost_per_lb:
      estimatedLbs > 0 ? Math.round((totalCost / estimatedLbs) * 10000) / 10000 : null,
    combinations: comboRows,
  };
}

function compare(baseline, target) {
  const loadsSaved = (baseline.total_loads || 0) - (target.total_loads || 0);
  const dollarSavings =
    Math.round(((baseline.estimated_supply_cost || 0) - (target.estimated_supply_cost || 0)) * 100)
    / 100;
  const bCost = baseline.estimated_supply_cost || 0;
  return {
    loads_saved: loadsSaved,
    dollar_savings: dollarSavings,
    savings_pct: bCost > 0 ? Math.round((dollarSavings / bCost) * 10000) / 100 : null,
  };
}

function MetricRow({ label, left, right, emphasize }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "1.2fr 1fr 1fr",
        gap: 0.5,
        py: 0.55,
        borderBottom: "1px solid #f1f5f9",
        bgcolor: emphasize ? "#f0fdf4" : "transparent",
      }}
    >
      <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>{label}</Typography>
      <Typography sx={{ fontSize: 13, fontWeight: emphasize ? 800 : 700, color: "#0f172a" }}>
        {left}
      </Typography>
      <Typography sx={{ fontSize: 13, fontWeight: emphasize ? 800 : 700, color: "#0f172a" }}>
        {right}
      </Typography>
    </Box>
  );
}

/**
 * Split Cost Simulator V1 — read-only planning sheet under Rinse WF Supplies.
 * Baseline = last N CLOSED ET business days (never today's in-progress day).
 */
export default function ManagementSplitCostSimulatorModal({
  open,
  onClose,
  selectedDateEt,
  todayWorkloadOrders = 100,
}) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const [windowDays, setWindowDays] = useState(7);
  const [avgMode, setAvgMode] = useState("last_7"); // last_7 | last_30 | manual
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [baseline, setBaseline] = useState(null);

  const [totalOrders, setTotalOrders] = useState(100);
  const [baselineSplitPct, setBaselineSplitPct] = useState(0);
  const [targetSplitPct, setTargetSplitPct] = useState(0);
  const [avgLb, setAvgLb] = useState(20);

  useEffect(() => {
    if (!open || !selectedDateEt) return undefined;
    let cancelled = false;
    const ac = new AbortController();
    (async () => {
      setLoading(true);
      setError("");
      try {
        const res = await getManagementSplitCostSimulatorBaseline(selectedDateEt, {
          window: windowDays,
          today_orders: todayWorkloadOrders,
          signal: ac.signal,
        });
        if (cancelled) return;
        const data = res?.data || {};
        setBaseline(data);
        const d = data.defaults || {};
        setTotalOrders(
          d.total_orders != null ? Number(d.total_orders) : Number(todayWorkloadOrders) || 100,
        );
        const sp = d.split_pct != null ? Number(d.split_pct) : 0;
        setBaselineSplitPct(sp);
        // Sensible planning target: modest reduction, floor at 0
        setTargetSplitPct(Math.max(0, Math.round((sp - 10) * 10) / 10));
        if (avgMode !== "manual" && d.avg_lb_per_bag != null) {
          setAvgLb(Number(d.avg_lb_per_bag));
        }
      } catch (err) {
        if (cancelled || err?.code === "ERR_CANCELED") return;
        setError(err?.response?.data?.error || err?.message || "Failed to load baseline");
        setBaseline(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      ac.abort();
    };
    // avgMode manual should not refetch; windowDays / open / date drive reload
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selectedDateEt, windowDays, todayWorkloadOrders]);

  const onWindowChange = (_e, next) => {
    if (!next) return;
    setWindowDays(next);
    setAvgMode(next === 7 ? "last_7" : "last_30");
  };

  const onAvgModeChange = (_e, next) => {
    if (!next) return;
    setAvgMode(next);
    if (next === "last_7") {
      setWindowDays(7);
      if (windowDays === 7 && baseline?.basis?.avg_lb_per_bag != null) {
        setAvgLb(Number(baseline.basis.avg_lb_per_bag));
      }
    } else if (next === "last_30") {
      setWindowDays(30);
      if (windowDays === 30 && baseline?.basis?.avg_lb_per_bag != null) {
        setAvgLb(Number(baseline.basis.avg_lb_per_bag));
      }
    }
  };

  const combos = baseline?.combinations || [];

  const baselineSim = useMemo(
    () =>
      simulateSplitCost({
        totalOrders,
        splitRate: baselineSplitPct / 100,
        avgLbPerBag: avgLb,
        combinations: combos,
      }),
    [totalOrders, baselineSplitPct, avgLb, combos],
  );

  const targetSim = useMemo(
    () =>
      simulateSplitCost({
        totalOrders,
        splitRate: targetSplitPct / 100,
        avgLbPerBag: avgLb,
        combinations: combos,
      }),
    [totalOrders, targetSplitPct, avgLb, combos],
  );

  const delta = useMemo(() => compare(baselineSim, targetSim), [baselineSim, targetSim]);
  const basis = baseline?.basis || {};

  const onBaselineSplitChange = (v) => {
    const pct = Math.max(0, Math.min(100, Number(v) || 0));
    setBaselineSplitPct(pct);
  };

  const onBaselineSplitOrdersChange = (v) => {
    const orders = Math.max(0, Math.floor(Number(totalOrders) || 0));
    const so = Math.max(0, Math.min(orders, Math.floor(Number(v) || 0)));
    setBaselineSplitPct(orders ? Math.round((so / orders) * 10000) / 100 : 0);
  };

  const onTargetSplitChange = (v) => {
    setTargetSplitPct(Math.max(0, Math.min(100, Number(v) || 0)));
  };

  const onTargetSplitOrdersChange = (v) => {
    const orders = Math.max(0, Math.floor(Number(totalOrders) || 0));
    const so = Math.max(0, Math.min(orders, Math.floor(Number(v) || 0)));
    setTargetSplitPct(orders ? Math.round((so / orders) * 10000) / 100 : 0);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      fullWidth
      maxWidth="sm"
      scroll="paper"
    >
      <DialogTitle sx={{ pr: 6, pb: 1 }}>
        <Typography sx={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
          Split Cost Simulator
        </Typography>
        <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", mt: 0.25 }}>
          ESTIMATED · SIMULATION · read-only
        </Typography>
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: "absolute", right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 1.5, sm: 2 }, py: 1.5 }}>
        {loading ? (
          <Box sx={{ py: 6, textAlign: "center" }}>
            <CircularProgress size={28} />
            <Typography sx={{ mt: 1.5, fontSize: 13, color: "#64748b" }}>
              Loading closed-day baseline…
            </Typography>
          </Box>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : !baseline?.available ? (
          <Alert severity="info">
            No closed ET business days available for baseline. Close prior days first.
          </Alert>
        ) : (
          <Stack spacing={1.75}>
            <Alert severity="info" sx={{ py: 0.5 }}>
              Planning only — does not change live supply usage, splits, or reporting.
              Split rate applied uniformly across combinations.
            </Alert>

            <Box>
              <Typography sx={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.6, color: "#64748b", mb: 0.5 }}>
                HISTORICAL WINDOW
              </Typography>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={windowDays}
                onChange={onWindowChange}
                sx={{ mb: 0.75, flexWrap: "wrap" }}
              >
                <ToggleButton value={7} sx={{ textTransform: "none", fontWeight: 700, px: 1.25 }}>
                  Last 7 Days
                </ToggleButton>
                <ToggleButton value={30} sx={{ textTransform: "none", fontWeight: 700, px: 1.25 }}>
                  Last 30 Days
                </ToggleButton>
              </ToggleButtonGroup>
              <Typography sx={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.6, color: "#64748b", mb: 0.5 }}>
                AVG LB / BAG SOURCE
              </Typography>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={avgMode}
                onChange={onAvgModeChange}
                sx={{ flexWrap: "wrap" }}
              >
                <ToggleButton value="last_7" sx={{ textTransform: "none", fontWeight: 700, px: 1.25 }}>
                  Last 7
                </ToggleButton>
                <ToggleButton value="last_30" sx={{ textTransform: "none", fontWeight: 700, px: 1.25 }}>
                  Last 30
                </ToggleButton>
                <ToggleButton value="manual" sx={{ textTransform: "none", fontWeight: 700, px: 1.25 }}>
                  Manual
                </ToggleButton>
              </ToggleButtonGroup>
            </Box>

            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(4, 1fr)" },
                gap: 1,
              }}
            >
              <TextField
                label="Total Orders"
                type="number"
                size="small"
                value={totalOrders}
                onChange={(e) => setTotalOrders(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
                inputProps={{ min: 0, step: 1 }}
              />
              <TextField
                label="Baseline Split %"
                type="number"
                size="small"
                value={baselineSplitPct}
                onChange={(e) => onBaselineSplitChange(e.target.value)}
                inputProps={{ min: 0, max: 100, step: 0.1 }}
              />
              <TextField
                label="Target Split %"
                type="number"
                size="small"
                value={targetSplitPct}
                onChange={(e) => onTargetSplitChange(e.target.value)}
                inputProps={{ min: 0, max: 100, step: 0.1 }}
              />
              <TextField
                label="Avg Lb / Bag"
                type="number"
                size="small"
                value={avgLb}
                disabled={avgMode !== "manual"}
                onChange={(e) => setAvgLb(Math.max(0, Number(e.target.value) || 0))}
                inputProps={{ min: 0, step: 0.1 }}
                helperText={avgMode === "manual" ? "Manual PRE avg" : "From closed-day PRE"}
              />
            </Box>

            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 1,
              }}
            >
              <TextField
                label="Baseline Split Orders"
                type="number"
                size="small"
                value={baselineSim.split_orders}
                onChange={(e) => onBaselineSplitOrdersChange(e.target.value)}
                inputProps={{ min: 0, step: 1 }}
              />
              <TextField
                label="Target Split Orders"
                type="number"
                size="small"
                value={targetSim.split_orders}
                onChange={(e) => onTargetSplitOrdersChange(e.target.value)}
                inputProps={{ min: 0, step: 1 }}
              />
            </Box>

            {/* Primary result */}
            <Box
              sx={{
                p: 1.5,
                borderRadius: 2,
                bgcolor: "#0f172a",
                color: "#f8fafc",
              }}
            >
              <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", mb: 0.75 }}>
                PRIMARY RESULT · ESTIMATED
              </Typography>
              <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.25 }}>
                Reducing splits from {fmtPct(baselineSim.split_pct, 1)} → {fmtPct(targetSim.split_pct, 1)}
              </Typography>
              <Typography sx={{ fontSize: 15, fontWeight: 700, mt: 0.75, color: "#bbf7d0" }}>
                {fmtInt(delta.loads_saved)} fewer loads
              </Typography>
              <Typography sx={{ fontSize: 15, fontWeight: 700, mt: 0.35, color: "#bbf7d0" }}>
                {fmtMoney(delta.dollar_savings)} estimated supply savings
                {delta.savings_pct != null ? ` (${fmtPct(delta.savings_pct, 1)})` : ""}
              </Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 600, mt: 0.75, color: "#e2e8f0" }}>
                {fmtMoney(baselineSim.est_cost_per_lb, 4)}/lb → {fmtMoney(targetSim.est_cost_per_lb, 4)}/lb
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 600, mt: 0.5, color: "#64748b" }}>
                EST. COST / LB — planning from PRE avg; not live Cost / Completed Lb
              </Typography>
            </Box>

            {/* Baseline vs Target */}
            <Box>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "1.2fr 1fr 1fr",
                  gap: 0.5,
                  pb: 0.5,
                  mb: 0.25,
                }}
              >
                <Typography sx={{ fontSize: 10, fontWeight: 800, color: "#94a3b8" }}>METRIC</Typography>
                <Typography sx={{ fontSize: 10, fontWeight: 800, color: "#94a3b8" }}>BASELINE</Typography>
                <Typography sx={{ fontSize: 10, fontWeight: 800, color: "#94a3b8" }}>TARGET</Typography>
              </Box>
              <MetricRow label="Split %" left={fmtPct(baselineSim.split_pct)} right={fmtPct(targetSim.split_pct)} />
              <MetricRow
                label="Split Orders"
                left={fmtInt(baselineSim.split_orders)}
                right={fmtInt(targetSim.split_orders)}
              />
              <MetricRow
                label="Non-Split Orders"
                left={fmtInt(baselineSim.non_split_orders)}
                right={fmtInt(targetSim.non_split_orders)}
              />
              <MetricRow
                label="Total Loads"
                left={fmtInt(baselineSim.total_loads)}
                right={fmtInt(targetSim.total_loads)}
                emphasize
              />
              <MetricRow
                label="Loads Saved"
                left="—"
                right={fmtInt(delta.loads_saved)}
                emphasize
              />
              <MetricRow
                label="Estimated Lbs"
                left={fmtLb(baselineSim.estimated_lbs)}
                right={fmtLb(targetSim.estimated_lbs)}
              />
              <MetricRow
                label="Supply Cost"
                left={fmtMoney(baselineSim.estimated_supply_cost)}
                right={fmtMoney(targetSim.estimated_supply_cost)}
                emphasize
              />
              <MetricRow
                label="Cost / Order"
                left={fmtMoney(baselineSim.cost_per_order, 4)}
                right={fmtMoney(targetSim.cost_per_order, 4)}
              />
              <MetricRow
                label="Cost / Load"
                left={fmtMoney(baselineSim.cost_per_load, 4)}
                right={fmtMoney(targetSim.cost_per_load, 4)}
              />
              <MetricRow
                label="Est. Cost / Lb"
                left={fmtMoney(baselineSim.est_cost_per_lb, 4)}
                right={fmtMoney(targetSim.est_cost_per_lb, 4)}
              />
              <MetricRow
                label="Dollar Savings"
                left="—"
                right={fmtMoney(delta.dollar_savings)}
                emphasize
              />
              <MetricRow
                label="Savings %"
                left="—"
                right={fmtPct(delta.savings_pct)}
              />
            </Box>

            {/* Combination mix — target view */}
            <Box>
              <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", mb: 0.5 }}>
                SUPPLY COMBINATION MIX · TARGET · ESTIMATED
              </Typography>
              <Typography sx={{ fontSize: 11, color: "#94a3b8", mb: 0.75, fontWeight: 600 }}>
                Mix from closed-day orders (1 bag = 1 order). Split applied uniformly.
              </Typography>
              <Stack spacing={0.75}>
                {(targetSim.combinations || []).map((c) => (
                  <Box
                    key={c.key}
                    sx={{
                      p: 1,
                      borderRadius: 1.25,
                      border: "1px solid #e2e8f0",
                      bgcolor: "#fff",
                    }}
                  >
                    <Typography sx={{ fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
                      {c.label}
                    </Typography>
                    <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600, mt: 0.25 }}>
                      {fmtPct(c.share_pct)} of orders · {fmtInt(c.estimated_orders)} orders
                      {" · "}
                      {fmtMoney(c.cost_per_load, 4)}/load · {fmtInt(c.estimated_loads)} loads
                      {" · "}
                      {fmtMoney(c.estimated_cost)}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Box>

            {/* Cost per load reference */}
            <Box>
              <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", mb: 0.5 }}>
                COST PER LOAD REFERENCE · CURRENT SUPPLY MASTER
              </Typography>
              <Stack spacing={0.5}>
                {(baseline.cost_per_load_reference || []).map((c) => (
                  <Box key={c.label} sx={{ py: 0.5, borderBottom: "1px solid #f1f5f9" }}>
                    <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>
                      {c.label}
                    </Typography>
                    <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
                      1 load = {fmtMoney(c.cost_per_load, 4)}
                      {" · "}
                      Split order (2 loads) = {fmtMoney(c.cost_per_split_order, 4)}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Box>

            {/* Historical basis */}
            <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f8fafc", border: "1px solid #e2e8f0" }}>
              <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#334155" }}>
                {basis.label || `${windowDays}-Day Baseline`}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600, mt: 0.35 }}>
                Based on {fmtInt(basis.completed_bags)} WF bags · {fmtLb(basis.pre_lbs_total)} PRE lb
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                Avg {fmtLb(basis.avg_lb_per_bag)} lb/bag · {fmtPct(basis.split_pct)} split
              </Typography>
              <Typography sx={{ fontSize: 11, color: "#94a3b8", fontWeight: 600, mt: 0.5 }}>
                Last {basis.days_used ?? windowDays} completed ET business days
                {basis.note ? ` · ${basis.note}` : ""}
              </Typography>
              <Typography sx={{ fontSize: 10, color: "#94a3b8", mt: 0.5 }}>
                Prices as of {baseline.price_as_of_et || selectedDateEt} ET (Supply Master)
              </Typography>
            </Box>

            <Button onClick={onClose} variant="contained" sx={{ textTransform: "none", fontWeight: 800 }}>
              Close
            </Button>
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  );
}
