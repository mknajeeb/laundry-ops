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
  MenuItem,
  Popover,
  Stack,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { useTheme } from "@mui/material/styles";
import { getManagementSplitCostSimulatorBaseline } from "../../api";
import {
  getSplitCostBaselineCache,
  setSplitCostBaselineCache,
} from "./splitCostSimulatorCache";

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

function fmtLb(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

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
      label: r.c.short_label || r.c.label || r.c.key,
      short_label: r.c.short_label || r.c.label || r.c.key,
      share: norm,
      share_pct: Math.round(norm * 10000) / 100,
      estimated_orders: cOrders,
      estimated_loads: cLoads,
      cost_per_load: cpl,
      cost_per_split_order: Math.round(cpl * 2 * 10000) / 10000,
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

function periodSavings(shiftSavings, shiftsPerWeek = 7) {
  const shift = Math.round((Number(shiftSavings) || 0) * 100) / 100;
  const spw = Math.max(0, Number(shiftsPerWeek) || 0);
  const weekly = Math.round(shift * spw * 100) / 100;
  const monthly = Math.round(((weekly * 52) / 12) * 100) / 100;
  return { per_shift: shift, per_week: weekly, per_month: monthly, shifts_per_week: spw };
}

function CompactRow({ left, mid, right, strong }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 0.75,
        py: 0.55,
        borderBottom: "1px solid #f1f5f9",
        alignItems: "baseline",
      }}
    >
      <Typography sx={{ fontSize: 12, fontWeight: strong ? 800 : 600, color: "#334155" }}>
        {left}
      </Typography>
      <Typography
        sx={{
          fontSize: 12,
          fontWeight: strong ? 800 : 700,
          color: strong ? "#0f172a" : "#475569",
          textAlign: "right",
        }}
      >
        {mid}
        {right != null && right !== "" ? (
          <Box component="span" sx={{ color: "#16a34a", ml: 0.75, fontWeight: 800 }}>
            {right}
          </Box>
        ) : null}
      </Typography>
    </Box>
  );
}

function Sheet({ open, onClose, title, children, fullScreen }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      fullWidth
      maxWidth="xs"
      scroll="paper"
      sx={{ zIndex: (t) => t.zIndex.modal + 2 }}
    >
      <DialogTitle sx={{ pr: 6, py: 1.25 }}>
        <Typography sx={{ fontSize: 15, fontWeight: 800 }}>{title}</Typography>
        <IconButton
          aria-label="Close"
          onClick={onClose}
          sx={{ position: "absolute", right: 6, top: 6 }}
          size="small"
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ px: 1.5, py: 1.25 }}>
        {children}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Compact mobile-first Split Cost Simulator.
 * Math mirrors backend; UI keeps long-form details in secondary sheets.
 */
export default function ManagementSplitCostSimulatorModal({
  open,
  onClose,
  selectedDateEt,
  todayWorkloadOrders = 100,
}) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const narrow = useMediaQuery("(max-width:430px)");

  const [refBasis, setRefBasis] = useState("7"); // 7 | 30 | manual
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [baseline, setBaseline] = useState(null);
  const [fromCache, setFromCache] = useState(false);

  const [totalOrders, setTotalOrders] = useState(100);
  const [baselineSplitPct, setBaselineSplitPct] = useState(0);
  const [targetSplitPct, setTargetSplitPct] = useState(0);
  const [avgLb, setAvgLb] = useState(20);
  const [shiftsPerWeek, setShiftsPerWeek] = useState(7);
  const [combos, setCombos] = useState([]);

  const [detailOpen, setDetailOpen] = useState(false);
  const [comboDetailOpen, setComboDetailOpen] = useState(false);
  const [costRefOpen, setCostRefOpen] = useState(false);
  const [editMixOpen, setEditMixOpen] = useState(false);
  const [editShares, setEditShares] = useState([]);
  const [assumptionsAnchor, setAssumptionsAnchor] = useState(null);
  const [infoAnchor, setInfoAnchor] = useState(null);

  const windowDays = refBasis === "30" ? 30 : 7;

  useEffect(() => {
    if (!open || !selectedDateEt) return undefined;
    let cancelled = false;
    const ac = new AbortController();

    const cached = getSplitCostBaselineCache(selectedDateEt, windowDays);
    if (cached?.available && refBasis !== "manual") {
      setBaseline(cached);
      setFromCache(true);
      setCombos(cached.combinations || []);
      const d = cached.defaults || {};
      setTotalOrders(
        d.total_orders != null ? Number(d.total_orders) : Number(todayWorkloadOrders) || 100,
      );
      const sp = d.split_pct != null ? Number(d.split_pct) : 0;
      setBaselineSplitPct(sp);
      setTargetSplitPct((prev) => (prev > 0 ? prev : Math.max(0, Math.round((sp * 0.46) * 10) / 10)));
      if (refBasis !== "manual" && d.avg_lb_per_bag != null) setAvgLb(Number(d.avg_lb_per_bag));
      if (d.shifts_per_week != null) setShiftsPerWeek(Number(d.shifts_per_week));
      setLoading(false);
      setError("");
    } else if (refBasis !== "manual") {
      setLoading(true);
    }

    if (refBasis === "manual") {
      // Keep current assumptions; still refresh mix from last-used window if empty
      return undefined;
    }

    (async () => {
      try {
        const res = await getManagementSplitCostSimulatorBaseline(selectedDateEt, {
          window: windowDays,
          today_orders: todayWorkloadOrders,
          signal: ac.signal,
        });
        if (cancelled) return;
        const data = res?.data || {};
        setSplitCostBaselineCache(selectedDateEt, windowDays, data);
        setBaseline(data);
        setFromCache(Boolean(data.cached));
        setCombos(data.combinations || []);
        const d = data.defaults || {};
        setTotalOrders(
          d.total_orders != null ? Number(d.total_orders) : Number(todayWorkloadOrders) || 100,
        );
        const sp = d.split_pct != null ? Number(d.split_pct) : 0;
        setBaselineSplitPct(sp);
        setTargetSplitPct((prev) => {
          if (prev > 0 && prev < sp) return prev;
          return Math.max(0, Math.round((sp * 0.46) * 10) / 10);
        });
        if (d.avg_lb_per_bag != null) setAvgLb(Number(d.avg_lb_per_bag));
        if (d.shifts_per_week != null) setShiftsPerWeek(Number(d.shifts_per_week));
        setError("");
      } catch (err) {
        if (cancelled || err?.code === "ERR_CANCELED") return;
        if (!getSplitCostBaselineCache(selectedDateEt, windowDays)) {
          setError(err?.response?.data?.error || err?.message || "Failed to load baseline");
          setBaseline(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [open, selectedDateEt, windowDays, todayWorkloadOrders, refBasis]);

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

  const loadsSaved = (baselineSim.total_loads || 0) - (targetSim.total_loads || 0);
  const dollarSavings =
    Math.round(
      ((baselineSim.estimated_supply_cost || 0) - (targetSim.estimated_supply_cost || 0)) * 100,
    ) / 100;
  const periods = periodSavings(dollarSavings, shiftsPerWeek);
  const basis = baseline?.basis || {};
  const orderMix = baseline?.order_mix || {};
  const costRef = baseline?.cost_per_load_reference || [];

  const editTotal = useMemo(
    () => editShares.reduce((s, r) => s + (Number(r.share_pct) || 0), 0),
    [editShares],
  );
  const editOk = Math.abs(editTotal - 100) < 0.05;

  const openEditMix = () => {
    setEditShares(
      (combos || []).map((c) => ({
        key: c.key,
        label: c.short_label || c.label || c.key,
        share_pct: Number(c.share_pct) || 0,
        cost_per_load: c.cost_per_load,
        products: c.products,
      })),
    );
    setEditMixOpen(true);
  };

  const applyEditMix = () => {
    if (!editOk) return;
    const next = editShares.map((r) => ({
      key: r.key,
      label: r.label,
      short_label: r.label,
      share: (Number(r.share_pct) || 0) / 100,
      share_pct: Number(r.share_pct) || 0,
      cost_per_load: r.cost_per_load,
      products: r.products || [],
    }));
    setCombos(next);
    setEditMixOpen(false);
  };

  const resetEditMix = () => {
    const hist = baseline?.combinations || [];
    setEditShares(
      hist.map((c) => ({
        key: c.key,
        label: c.short_label || c.label || c.key,
        share_pct: Number(c.share_pct) || 0,
        cost_per_load: c.cost_per_load,
        products: c.products,
      })),
    );
  };

  const onRefChange = (e) => {
    const v = e.target.value;
    setRefBasis(v);
  };

  const showManual = refBasis === "manual";

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        fullScreen={fullScreen}
        fullWidth
        maxWidth="xs"
        scroll="paper"
        PaperProps={{
          sx: {
            width: "100%",
            maxWidth: narrow ? "100%" : 430,
            m: fullScreen ? 0 : 1,
          },
        }}
      >
        <DialogTitle sx={{ pr: 6, py: 1.1, pb: 0.75 }}>
          <Typography sx={{ fontSize: 16, fontWeight: 800, color: "#0f172a" }}>
            Split Cost Simulator
          </Typography>
          <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>
            ESTIMATED · SIMULATION{fromCache ? " · cached" : ""}
          </Typography>
          <IconButton
            aria-label="Close"
            onClick={onClose}
            sx={{ position: "absolute", right: 6, top: 6 }}
            size="small"
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent
          dividers
          sx={{
            px: 1.5,
            py: 1.25,
            overflowX: "hidden",
            maxWidth: "100%",
          }}
        >
          {loading && !baseline ? (
            <Box sx={{ py: 5, textAlign: "center" }}>
              <CircularProgress size={26} />
              <Typography sx={{ mt: 1.25, fontSize: 13, color: "#64748b" }}>
                Loading closed-day reference…
              </Typography>
            </Box>
          ) : error && !baseline ? (
            <Alert severity="error">{error}</Alert>
          ) : !baseline?.available && refBasis !== "manual" ? (
            <Alert severity="info">No closed ET days for baseline yet.</Alert>
          ) : (
            <Stack spacing={1.25} sx={{ maxWidth: "100%" }}>
              {/* Reference basis */}
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 0.75,
                  flexWrap: "wrap",
                }}
              >
                <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b" }}>
                  Reference
                </Typography>
                <TextField
                  select
                  size="small"
                  value={refBasis}
                  onChange={onRefChange}
                  sx={{
                    minWidth: 140,
                    "& .MuiInputBase-root": { fontSize: 13, fontWeight: 700 },
                  }}
                >
                  <MenuItem value="7">Last 7 Days</MenuItem>
                  <MenuItem value="30">Last 30 Days</MenuItem>
                  <MenuItem value="manual">Manual</MenuItem>
                </TextField>
                <Tooltip title="Historical source">
                  <IconButton
                    size="small"
                    onClick={(e) => setInfoAnchor(e.currentTarget)}
                    aria-label="Reference info"
                  >
                    <InfoOutlinedIcon sx={{ fontSize: 18, color: "#64748b" }} />
                  </IconButton>
                </Tooltip>
                <IconButton
                  size="small"
                  onClick={(e) => setAssumptionsAnchor(e.currentTarget)}
                  aria-label="Operating assumptions"
                >
                  <SettingsOutlinedIcon sx={{ fontSize: 18, color: "#64748b" }} />
                </IconButton>
                {loading ? <CircularProgress size={14} /> : null}
              </Box>

              {/* Scenario card */}
              <Box
                sx={{
                  p: 1.25,
                  borderRadius: 2,
                  border: "1px solid #e2e8f0",
                  bgcolor: "#fff",
                }}
              >
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: 1,
                  }}
                >
                  <TextField
                    label="Orders"
                    type="number"
                    size="small"
                    value={totalOrders}
                    onChange={(e) =>
                      setTotalOrders(Math.max(0, Math.floor(Number(e.target.value) || 0)))
                    }
                    inputProps={{ min: 0, step: 1 }}
                  />
                  <TextField
                    label="Avg Bag (lb)"
                    type="number"
                    size="small"
                    value={avgLb}
                    disabled={!showManual}
                    onChange={(e) => setAvgLb(Math.max(0, Number(e.target.value) || 0))}
                    inputProps={{ min: 0, step: 0.1 }}
                  />
                  <TextField
                    label="Baseline Split %"
                    type="number"
                    size="small"
                    value={baselineSplitPct}
                    disabled={!showManual}
                    onChange={(e) =>
                      setBaselineSplitPct(
                        Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                      )
                    }
                    inputProps={{ min: 0, max: 100, step: 0.1 }}
                  />
                  <TextField
                    label="Target Split %"
                    type="number"
                    size="small"
                    value={targetSplitPct}
                    onChange={(e) =>
                      setTargetSplitPct(
                        Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                      )
                    }
                    inputProps={{ min: 0, max: 100, step: 0.1 }}
                  />
                </Box>
              </Box>

              {/* Primary savings */}
              <Box
                sx={{
                  p: 1.5,
                  borderRadius: 2,
                  bgcolor: "#0f172a",
                  color: "#f8fafc",
                }}
              >
                <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#94a3b8" }}>
                  Reduce splits
                </Typography>
                <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.2, mt: 0.25 }}>
                  {fmtPct(baselineSim.split_pct, 1)} → {fmtPct(targetSim.split_pct, 1)}
                </Typography>
                <Typography sx={{ fontSize: 22, fontWeight: 800, color: "#bbf7d0", mt: 1 }}>
                  SAVE {fmtMoney(dollarSavings)} / SHIFT
                </Typography>
                <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#e2e8f0", mt: 0.5 }}>
                  {fmtInt(loadsSaved)} fewer loads
                </Typography>
                <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#cbd5e1", mt: 0.35 }}>
                  {fmtMoney(baselineSim.est_cost_per_lb, 4)}/lb →{" "}
                  {fmtMoney(targetSim.est_cost_per_lb, 4)}/lb
                </Typography>
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
                    ["Shift", periods.per_shift],
                    ["Week", periods.per_week],
                    ["Month", periods.per_month],
                  ].map(([lab, val]) => (
                    <Box key={lab}>
                      <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>
                        {lab}
                      </Typography>
                      <Typography sx={{ fontSize: 14, fontWeight: 800, color: "#bbf7d0" }}>
                        {fmtMoney(val)}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Box>

              {/* Impact */}
              <Box>
                <Typography
                  sx={{
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: 0.6,
                    color: "#64748b",
                    mb: 0.35,
                  }}
                >
                  IMPACT
                </Typography>
                <CompactRow
                  strong
                  left="Loads"
                  mid={`${fmtInt(baselineSim.total_loads)} → ${fmtInt(targetSim.total_loads)}`}
                  right={loadsSaved ? `${loadsSaved > 0 ? "−" : "+"}${fmtInt(Math.abs(loadsSaved))}` : null}
                />
                <CompactRow
                  strong
                  left="Supply Cost"
                  mid={`${fmtMoney(baselineSim.estimated_supply_cost)} → ${fmtMoney(targetSim.estimated_supply_cost)}`}
                  right={
                    dollarSavings
                      ? `${dollarSavings > 0 ? "−" : "+"}${fmtMoney(Math.abs(dollarSavings))}`
                      : null
                  }
                />
                <CompactRow
                  left="Cost/Order"
                  mid={`${fmtMoney(baselineSim.cost_per_order, 2)} → ${fmtMoney(targetSim.cost_per_order, 2)}`}
                />
                <CompactRow
                  left="Cost/Lb"
                  mid={`${fmtMoney(baselineSim.est_cost_per_lb, 4)} → ${fmtMoney(targetSim.est_cost_per_lb, 4)}`}
                />
                <CompactRow
                  left="Split Rate"
                  mid={`${fmtPct(baselineSim.split_pct, 1)} → ${fmtPct(targetSim.split_pct, 1)}`}
                />
                <Button
                  size="small"
                  onClick={() => setDetailOpen(true)}
                  sx={{ mt: 0.5, px: 0, textTransform: "none", fontWeight: 700 }}
                >
                  View detailed stats
                </Button>
              </Box>

              {/* Historical order mix */}
              <Box
                sx={{
                  p: 1.15,
                  borderRadius: 2,
                  border: "1px solid #e2e8f0",
                  bgcolor: "#f8fafc",
                }}
              >
                <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#0f172a" }}>
                  Historical Order Mix
                </Typography>
                <Typography sx={{ fontSize: 10, color: "#94a3b8", fontWeight: 600, mb: 0.75 }}>
                  % of orders — not loads or doses · Based on{" "}
                  {fmtInt(orderMix.total_completed_wf_orders || basis.completed_bags)} completed
                  WF orders
                </Typography>
                <CompactRow
                  left="Standard detergent"
                  mid={fmtPct(orderMix.detergent_standard_order_pct, 1)}
                />
                <CompactRow
                  left="Hypoallergenic / Ultra Clean"
                  mid={fmtPct(orderMix.detergent_hypo_order_pct, 1)}
                />
                <CompactRow left="Downy requested" mid={fmtPct(orderMix.downy_order_pct, 1)} />
                <CompactRow left="OxiClean requested" mid={fmtPct(orderMix.oxiclean_order_pct, 1)} />
                <CompactRow left="No add-on" mid={fmtPct(orderMix.no_addon_order_pct, 1)} />
                {orderMix.downy_and_oxi_order_pct != null ? (
                  <CompactRow
                    left="Downy + Oxi"
                    mid={fmtPct(orderMix.downy_and_oxi_order_pct, 1)}
                  />
                ) : null}
              </Box>

              {/* Combination mix compact */}
              <Box>
                <Typography
                  sx={{
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: 0.6,
                    color: "#64748b",
                    mb: 0.35,
                  }}
                >
                  SUPPLY COMBINATION MIX
                </Typography>
                {(combos || []).slice(0, 6).map((c) => (
                  <CompactRow
                    key={c.key}
                    left={c.short_label || c.label || c.key}
                    mid={fmtPct(c.share_pct, 1)}
                  />
                ))}
                <Stack direction="row" spacing={1} sx={{ mt: 0.5, flexWrap: "wrap" }}>
                  <Button
                    size="small"
                    onClick={() => setComboDetailOpen(true)}
                    sx={{ textTransform: "none", fontWeight: 700, px: 0 }}
                  >
                    View combinations
                  </Button>
                  <Button
                    size="small"
                    onClick={openEditMix}
                    sx={{ textTransform: "none", fontWeight: 700, px: 0 }}
                  >
                    Edit Mix
                  </Button>
                </Stack>
              </Box>

              {/* Cost per load */}
              <Box>
                <Typography
                  sx={{
                    fontSize: 10,
                    fontWeight: 800,
                    letterSpacing: 0.6,
                    color: "#64748b",
                    mb: 0.25,
                  }}
                >
                  COST PER LOAD
                </Typography>
                <Typography sx={{ fontSize: 10, color: "#94a3b8", fontWeight: 600, mb: 0.35 }}>
                  Split order = 2 loads
                </Typography>
                {costRef.slice(0, 6).map((c) => (
                  <CompactRow
                    key={c.key || c.label}
                    left={c.label}
                    mid={fmtMoney(c.cost_per_load, 2)}
                  />
                ))}
                <Button
                  size="small"
                  onClick={() => setCostRefOpen(true)}
                  sx={{ mt: 0.35, textTransform: "none", fontWeight: 700, px: 0 }}
                >
                  View reference
                </Button>
              </Box>

              <Typography sx={{ fontSize: 10, color: "#94a3b8", fontWeight: 600 }}>
                Avg {fmtLb(avgLb, 2)} lb/bag · Est. Cost/Lb = supply cost ÷ (orders × avg PRE
                lb/bag). Read-only — does not change live supply.
              </Typography>
            </Stack>
          )}
        </DialogContent>
      </Dialog>

      {/* Info popover */}
      <Popover
        open={Boolean(infoAnchor)}
        anchorEl={infoAnchor}
        onClose={() => setInfoAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
      >
        <Box sx={{ p: 1.5, maxWidth: 260 }}>
          <Typography sx={{ fontSize: 12, fontWeight: 800, mb: 0.5 }}>
            Based on last {basis.days_used || windowDays} closed business days
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            {fmtInt(basis.completed_bags)} WF bags
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            {fmtLb(basis.pre_lbs_total, 1)} PRE lb
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            {fmtLb(basis.avg_lb_per_bag, 2)} lb/bag
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            {fmtPct(basis.split_pct, 2)} finalized split
          </Typography>
        </Box>
      </Popover>

      {/* Assumptions popover */}
      <Popover
        open={Boolean(assumptionsAnchor)}
        anchorEl={assumptionsAnchor}
        onClose={() => setAssumptionsAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
      >
        <Box sx={{ p: 1.5, width: 220 }}>
          <Typography sx={{ fontSize: 12, fontWeight: 800, mb: 1 }}>
            Operating assumptions
          </Typography>
          <TextField
            label="Shifts / Week"
            type="number"
            size="small"
            fullWidth
            value={shiftsPerWeek}
            onChange={(e) => setShiftsPerWeek(Math.max(0, Number(e.target.value) || 0))}
            inputProps={{ min: 0, max: 14, step: 0.5 }}
            helperText="Week = shift × this · Month = week × 52/12"
          />
        </Box>
      </Popover>

      {/* Detailed stats */}
      <Sheet
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title="Detailed Stats"
        fullScreen={fullScreen}
      >
        <CompactRow left="Split Orders" mid={`${fmtInt(baselineSim.split_orders)} → ${fmtInt(targetSim.split_orders)}`} />
        <CompactRow
          left="Non-Split Orders"
          mid={`${fmtInt(baselineSim.non_split_orders)} → ${fmtInt(targetSim.non_split_orders)}`}
        />
        <CompactRow
          left="Estimated Lbs"
          mid={`${fmtLb(baselineSim.estimated_lbs)} → ${fmtLb(targetSim.estimated_lbs)}`}
        />
        <CompactRow
          left="Savings %"
          mid={
            baselineSim.estimated_supply_cost
              ? fmtPct((dollarSavings / baselineSim.estimated_supply_cost) * 100, 1)
              : "—"
          }
        />
        <CompactRow left="Cost / Load" mid={`${fmtMoney(baselineSim.cost_per_load, 4)} → ${fmtMoney(targetSim.cost_per_load, 4)}`} />
        <Typography sx={{ fontSize: 11, color: "#94a3b8", mt: 1 }}>
          Uniform split rate across combinations. ESTIMATED only.
        </Typography>
      </Sheet>

      {/* Combination details */}
      <Sheet
        open={comboDetailOpen}
        onClose={() => setComboDetailOpen(false)}
        title="Combination Details · Target"
        fullScreen={fullScreen}
      >
        <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1, fontWeight: 600 }}>
          Estimated under target split · order mix
        </Typography>
        {(targetSim.combinations || []).map((c) => (
          <Box
            key={c.key}
            sx={{ py: 0.85, borderBottom: "1px solid #f1f5f9" }}
          >
            <Typography sx={{ fontSize: 13, fontWeight: 800 }}>{c.short_label || c.label}</Typography>
            <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600 }}>
              {fmtPct(c.share_pct)} · {fmtInt(c.estimated_orders)} orders ·{" "}
              {fmtMoney(c.cost_per_load, 4)}/load · {fmtInt(c.estimated_loads)} loads ·{" "}
              {fmtMoney(c.estimated_cost)}
            </Typography>
          </Box>
        ))}
      </Sheet>

      {/* Cost reference */}
      <Sheet
        open={costRefOpen}
        onClose={() => setCostRefOpen(false)}
        title="Cost per Load Reference"
        fullScreen={fullScreen}
      >
        <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1, fontWeight: 600 }}>
          Current Supply Master · Split order = 2× load cost
        </Typography>
        {costRef.map((c) => (
          <Box key={c.key || c.label} sx={{ py: 0.75, borderBottom: "1px solid #f1f5f9" }}>
            <Typography sx={{ fontSize: 13, fontWeight: 800 }}>{c.label}</Typography>
            <Typography sx={{ fontSize: 12, color: "#475569", fontWeight: 600 }}>
              1 load = {fmtMoney(c.cost_per_load, 4)} · Split ={" "}
              {fmtMoney(c.cost_per_split_order, 4)}
            </Typography>
          </Box>
        ))}
      </Sheet>

      {/* Edit mix */}
      <Sheet
        open={editMixOpen}
        onClose={() => setEditMixOpen(false)}
        title="Edit Mix · Simulation only"
        fullScreen={fullScreen}
      >
        <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1, fontWeight: 600 }}>
          Adjust order shares for this simulation. Does not change Supply Master or history.
        </Typography>
        <Stack spacing={1}>
          {editShares.map((r, idx) => (
            <TextField
              key={r.key}
              label={r.label}
              type="number"
              size="small"
              value={r.share_pct}
              onChange={(e) => {
                const v = Number(e.target.value);
                setEditShares((rows) =>
                  rows.map((x, i) => (i === idx ? { ...x, share_pct: v } : x)),
                );
              }}
              inputProps={{ min: 0, max: 100, step: 0.1 }}
              InputProps={{
                endAdornment: (
                  <Typography sx={{ fontSize: 12, color: "#94a3b8", ml: 0.5 }}>%</Typography>
                ),
              }}
            />
          ))}
        </Stack>
        <Typography
          sx={{
            mt: 1.25,
            fontSize: 14,
            fontWeight: 800,
            color: editOk ? "#16a34a" : "#dc2626",
          }}
        >
          Total {editTotal.toFixed(1)}%
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
          <Button
            variant="outlined"
            onClick={resetEditMix}
            sx={{ textTransform: "none", fontWeight: 700, flex: 1 }}
          >
            Reset to {windowDays}-Day Avg
          </Button>
          <Button
            variant="contained"
            disabled={!editOk}
            onClick={applyEditMix}
            sx={{ textTransform: "none", fontWeight: 800, flex: 1 }}
          >
            Apply to Simulation
          </Button>
        </Stack>
      </Sheet>
    </>
  );
}
