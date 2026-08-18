/** Canonical Supply Cost Simulator UI — Shift + Planning modes, one engine. */

import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useTheme } from "@mui/material/styles";
import { getManagementSplitCostSimulatorBaseline } from "../../api";
import {
  getSplitCostBaselineCache,
  setSplitCostBaselineCache,
} from "./splitCostSimulatorCache";
import {
  buildShiftPresetFromSupplies,
  compareScenarios,
  periodSavings,
  simulateSupplyCost,
} from "./supplySimulatorEngine";

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

function applyPreset(preset, setters) {
  const d = preset?.defaults || {};
  setters.setOrders(d.total_orders != null ? Number(d.total_orders) : 100);
  setters.setCurrentSplit(d.split_pct != null ? Number(d.split_pct) : 0);
  setters.setAvgLb(d.avg_lb_per_bag != null ? Number(d.avg_lb_per_bag) : 20);
  setters.setTide(d.tide_pct != null ? Number(d.tide_pct) : 100);
  setters.setUltra(d.ultra_clean_pct != null ? Number(d.ultra_clean_pct) : 0);
  setters.setDowny(d.downy_pct != null ? Number(d.downy_pct) : 0);
  setters.setOxi(d.oxiclean_pct != null ? Number(d.oxiclean_pct) : 0);
  setters.setUnitCosts(preset?.unit_costs || {});
  const sp = d.split_pct != null ? Number(d.split_pct) : 0;
  setters.setTargetSplit((prev) => {
    if (prev > 0 && prev < sp) return prev;
    return Math.max(0, Math.round(sp * 0.7 * 10) / 10);
  });
  if (d.shifts_per_week != null) setters.setShiftsPerWeek(Number(d.shifts_per_week));
}

/**
 * @param {"shift"|"planning"} mode
 * @param {object} [shiftSupplies] live supplies payload for Shift mode instant prefill
 * @param {object} [planningDefaults] optional defaults from Supplies Dashboard
 */
export default function SupplyCostSimulatorModal({
  open,
  onClose,
  mode = "shift",
  selectedDateEt,
  shiftSupplies = null,
  todayWorkloadOrders = null,
  planningDefaults = null,
}) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const isShift = mode === "shift";

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refBasis, setRefBasis] = useState("7");
  const [presetMeta, setPresetMeta] = useState(null);

  const [orders, setOrders] = useState(100);
  const [currentSplit, setCurrentSplit] = useState(0);
  const [targetSplit, setTargetSplit] = useState(0);
  const [avgLb, setAvgLb] = useState(20);
  const [tide, setTide] = useState(100);
  const [ultra, setUltra] = useState(0);
  const [downy, setDowny] = useState(0);
  const [oxi, setOxi] = useState(0);
  const [unitCosts, setUnitCosts] = useState({});
  const [shiftsPerWeek, setShiftsPerWeek] = useState(7);

  const setters = {
    setOrders,
    setCurrentSplit,
    setAvgLb,
    setTide,
    setUltra,
    setDowny,
    setOxi,
    setUnitCosts,
    setTargetSplit,
    setShiftsPerWeek,
  };

  // Shift mode: instant from live supplies
  useEffect(() => {
    if (!open || !isShift) return;
    const preset = buildShiftPresetFromSupplies(shiftSupplies, {
      selectedDateEt,
      todayWorkloadOrders,
    });
    setPresetMeta(preset);
    applyPreset(preset, setters);
    setError("");
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isShift, shiftSupplies, selectedDateEt, todayWorkloadOrders]);

  // Planning mode: cached historical preset
  useEffect(() => {
    if (!open || isShift) return undefined;
    if (planningDefaults && refBasis === "manual") {
      setOrders(Number(planningDefaults.total_orders) || orders);
      setCurrentSplit(Number(planningDefaults.split_pct) || 0);
      setAvgLb(Number(planningDefaults.avg_lb_per_bag) || avgLb);
      setTide(Number(planningDefaults.tide_pct) || tide);
      setUltra(Number(planningDefaults.ultra_clean_pct) || ultra);
      setDowny(Number(planningDefaults.downy_pct) || downy);
      setOxi(Number(planningDefaults.oxiclean_pct) || oxi);
      if (planningDefaults.unit_costs) setUnitCosts(planningDefaults.unit_costs);
      setLoading(false);
      return undefined;
    }
    if (refBasis === "manual") return undefined;

    const windowDays = refBasis === "30" ? 30 : 7;
    let cancelled = false;
    const ac = new AbortController();
    const cached = getSplitCostBaselineCache(selectedDateEt, windowDays);
    if (cached?.available) {
      setPresetMeta(cached);
      applyPreset(cached, setters);
      setLoading(false);
    } else {
      setLoading(true);
    }

    (async () => {
      try {
        const res = await getManagementSplitCostSimulatorBaseline(selectedDateEt, {
          window: windowDays,
          today_orders: todayWorkloadOrders ?? undefined,
          signal: ac.signal,
        });
        if (cancelled) return;
        const data = res?.data || {};
        setSplitCostBaselineCache(selectedDateEt, windowDays, data);
        setPresetMeta(data);
        applyPreset(data, setters);
        setError("");
      } catch (err) {
        if (cancelled || err?.code === "ERR_CANCELED") return;
        if (!cached) {
          setError(err?.response?.data?.error || err?.message || "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isShift, selectedDateEt, refBasis, todayWorkloadOrders, planningDefaults]);

  const current = useMemo(
    () =>
      simulateSupplyCost({
        totalOrders: orders,
        splitPct: currentSplit,
        avgLbPerBag: avgLb,
        tidePct: tide,
        ultraCleanPct: ultra,
        downyPct: downy,
        oxicleanPct: oxi,
        unitCosts,
      }),
    [orders, currentSplit, avgLb, tide, ultra, downy, oxi, unitCosts],
  );

  const target = useMemo(
    () =>
      simulateSupplyCost({
        totalOrders: orders,
        splitPct: targetSplit,
        avgLbPerBag: avgLb,
        tidePct: tide,
        ultraCleanPct: ultra,
        downyPct: downy,
        oxicleanPct: oxi,
        unitCosts,
      }),
    [orders, targetSplit, avgLb, tide, ultra, downy, oxi, unitCosts],
  );

  const delta = useMemo(
    () => compareScenarios(current, target, shiftsPerWeek),
    [current, target, shiftsPerWeek],
  );
  const periods = delta.period_savings || periodSavings(delta.dollar_savings, shiftsPerWeek);

  const onTargetOrdersChange = (v) => {
    const so = Math.max(0, Math.min(orders, Math.floor(Number(v) || 0)));
    setTargetSplit(orders ? Math.round((so / orders) * 10000) / 100 : 0);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      fullWidth
      maxWidth="xs"
      scroll="paper"
      PaperProps={{ sx: { maxWidth: 430, width: "100%", m: fullScreen ? 0 : 1 } }}
    >
      <DialogTitle sx={{ pr: 6, py: 1.1 }}>
        <Typography sx={{ fontSize: 16, fontWeight: 800 }}>
          {isShift ? "Simulate Split Cost" : "Planning Simulator"}
        </Typography>
        <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>
          ESTIMATED · {isShift ? "SHIFT" : "PLANNING"} · one engine
        </Typography>
        <IconButton
          aria-label="Close"
          onClick={onClose}
          size="small"
          sx={{ position: "absolute", right: 6, top: 6 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ px: 1.5, py: 1.25, overflowX: "hidden" }}>
        {loading && !presetMeta ? (
          <Box sx={{ py: 5, textAlign: "center" }}>
            <CircularProgress size={26} />
          </Box>
        ) : error && !presetMeta ? (
          <Typography color="error">{error}</Typography>
        ) : (
          <Stack spacing={1.25}>
            {!isShift ? (
              <TextField
                select
                size="small"
                label="Reference Basis"
                value={refBasis}
                onChange={(e) => setRefBasis(e.target.value)}
              >
                <MenuItem value="7">Last 7 Days</MenuItem>
                <MenuItem value="30">Last 30 Days</MenuItem>
                <MenuItem value="manual">Manual</MenuItem>
              </TextField>
            ) : null}

            {/* Scenario */}
            <Box sx={{ p: 1.15, borderRadius: 2, border: "1px solid #e2e8f0" }}>
              <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>
                {fmtInt(orders)} Orders
              </Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#64748b", mt: 0.35 }}>
                Current Split {fmtPct(currentSplit, 1)}
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: isShift ? "1fr" : "1fr 1fr",
                  gap: 1,
                  mt: 1,
                }}
              >
                {!isShift ? (
                  <TextField
                    label="Orders"
                    type="number"
                    size="small"
                    value={orders}
                    onChange={(e) => setOrders(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
                  />
                ) : null}
                <TextField
                  label="Target Split %"
                  type="number"
                  size="small"
                  value={targetSplit}
                  onChange={(e) =>
                    setTargetSplit(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
                  }
                  inputProps={{ min: 0, max: 100, step: 0.1 }}
                />
                {isShift ? (
                  <TextField
                    label="Target Split Orders"
                    type="number"
                    size="small"
                    value={target.split_orders}
                    onChange={(e) => onTargetOrdersChange(e.target.value)}
                  />
                ) : null}
              </Box>
            </Box>

            {/* Primary result */}
            <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: "#0f172a", color: "#f8fafc" }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#94a3b8" }}>
                Loads {fmtInt(current.total_loads)} → {fmtInt(target.total_loads)}
              </Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0", mt: 0.35 }}>
                Cost {fmtMoney(current.estimated_supply_cost)} →{" "}
                {fmtMoney(target.estimated_supply_cost)}
              </Typography>
              <Typography sx={{ fontSize: 22, fontWeight: 800, color: "#bbf7d0", mt: 1 }}>
                {delta.dollar_savings >= 0 ? "SAVE" : "ADD"}{" "}
                {fmtMoney(Math.abs(delta.dollar_savings))} / SHIFT
              </Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#cbd5e1", mt: 0.35 }}>
                {fmtInt(Math.abs(delta.loads_saved))}{" "}
                {delta.loads_saved >= 0 ? "fewer" : "more"} loads
              </Typography>
              {!isShift ? (
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, 1fr)",
                    gap: 0.75,
                    mt: 1.25,
                    pt: 1,
                    borderTop: "1px solid #334155",
                  }}
                >
                  {[
                    ["Day", periods.per_day ?? periods.per_shift],
                    ["Week", periods.per_week],
                    ["Month", periods.per_month],
                  ].map(([lab, val]) => (
                    <Box key={lab}>
                      <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>
                        {lab}
                      </Typography>
                      <Typography sx={{ fontSize: 13, fontWeight: 800, color: "#bbf7d0" }}>
                        {fmtMoney(val)}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              ) : null}
            </Box>

            {/* Compact KPIs */}
            <Box>
              <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#475569" }}>
                Cost/Order {fmtMoney(target.cost_per_order, 2)} · Cost/Load{" "}
                {fmtMoney(target.cost_per_load, 2)} · Est $/lb{" "}
                {fmtMoney(target.est_cost_per_lb, 4)}
              </Typography>
            </Box>

            {/* Mix helper */}
            <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>
              Tide {fmtPct(tide, 0)} · Ultra Clean {fmtPct(ultra, 0)}
              {" · "}
              Downy {fmtPct(downy, 0)} · Oxi {fmtPct(oxi, 0)}
            </Typography>

            {/* Planning / edit assumptions */}
            <Accordion
              disableGutters
              elevation={0}
              sx={{ border: "1px solid #e2e8f0", borderRadius: "8px !important", "&:before": { display: "none" } }}
            >
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography sx={{ fontSize: 13, fontWeight: 800 }}>
                  {isShift ? "Assumptions" : "Edit mix & assumptions"}
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0 }}>
                <Stack spacing={1}>
                  {!isShift || refBasis === "manual" ? (
                    <>
                      <TextField
                        label="Avg Lb / Bag"
                        type="number"
                        size="small"
                        value={avgLb}
                        onChange={(e) => setAvgLb(Math.max(0, Number(e.target.value) || 0))}
                      />
                      <TextField
                        label="Current / Baseline Split %"
                        type="number"
                        size="small"
                        value={currentSplit}
                        onChange={(e) =>
                          setCurrentSplit(Math.max(0, Math.min(100, Number(e.target.value) || 0)))
                        }
                      />
                    </>
                  ) : (
                    <TextField
                      label="Avg Lb / Bag (PRE)"
                      type="number"
                      size="small"
                      value={avgLb}
                      onChange={(e) => setAvgLb(Math.max(0, Number(e.target.value) || 0))}
                      helperText="From selected day PRE"
                    />
                  )}
                  <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b" }}>
                    Detergent Mix (≈100%)
                  </Typography>
                  <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                    <TextField
                      label="Tide %"
                      type="number"
                      size="small"
                      value={tide}
                      onChange={(e) => setTide(Math.max(0, Number(e.target.value) || 0))}
                    />
                    <TextField
                      label="Ultra Clean %"
                      type="number"
                      size="small"
                      value={ultra}
                      onChange={(e) => setUltra(Math.max(0, Number(e.target.value) || 0))}
                    />
                  </Box>
                  <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b" }}>
                    Add-ons (independent)
                  </Typography>
                  <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                    <TextField
                      label="Downy %"
                      type="number"
                      size="small"
                      value={downy}
                      onChange={(e) => setDowny(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
                    />
                    <TextField
                      label="OxiClean %"
                      type="number"
                      size="small"
                      value={oxi}
                      onChange={(e) => setOxi(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
                    />
                  </Box>
                  {!isShift ? (
                    <TextField
                      label="Shifts / Week"
                      type="number"
                      size="small"
                      value={shiftsPerWeek}
                      onChange={(e) => setShiftsPerWeek(Math.max(0, Number(e.target.value) || 0))}
                      helperText="Week = day × this · Month = week × 52/12"
                    />
                  ) : null}
                </Stack>
              </AccordionDetails>
            </Accordion>

            <Accordion
              disableGutters
              elevation={0}
              sx={{ border: "1px solid #e2e8f0", borderRadius: "8px !important", "&:before": { display: "none" } }}
            >
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography sx={{ fontSize: 13, fontWeight: 800 }}>
                  View calculation details
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0 }}>
                <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1 }}>
                  Expected cost/load = Tide%×Tide + Ultra%×Ultra + Downy%×Downy + Oxi%×Oxi.
                  Loads = non-split + split×2. ESTIMATED only.
                </Typography>
                <Typography sx={{ fontSize: 12, fontWeight: 700 }}>
                  E[cost/load] {fmtMoney(current.cost_per_load_expected, 4)}
                </Typography>
                <Typography sx={{ fontSize: 12 }}>
                  Tide dose {fmtMoney(unitCosts.tide, 4)} · Ultra {fmtMoney(unitCosts.ultra_clean, 4)}
                </Typography>
                <Typography sx={{ fontSize: 12 }}>
                  Downy {fmtMoney(unitCosts.downy, 4)} · Oxi {fmtMoney(unitCosts.oxiclean, 4)}
                </Typography>
                <Typography sx={{ fontSize: 12, mt: 0.75 }}>
                  Est lbs {fmtInt(current.estimated_lbs)} (orders × avg PRE lb)
                </Typography>
                <Typography sx={{ fontSize: 12 }}>
                  Split orders {fmtInt(current.split_orders)} → {fmtInt(target.split_orders)}
                </Typography>
              </AccordionDetails>
            </Accordion>
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** @deprecated name — use SupplyCostSimulatorModal */
export { SupplyCostSimulatorModal as ManagementSplitCostSimulatorModal };
