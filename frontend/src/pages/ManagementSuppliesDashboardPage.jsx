import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { getManagementSuppliesDashboard } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import SupplyCostSimulatorModal from "../components/management/SupplyCostSimulatorModal";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "last_7", label: "Last 7 Days" },
  { id: "this_week", label: "This Week" },
  { id: "previous_week", label: "Prev Week" },
  { id: "mtd", label: "MTD" },
  { id: "previous_month", label: "Prev Month" },
  { id: "custom", label: "Custom" },
];

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
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} lb`;
}

function Metric({ label, value }) {
  return (
    <Box
      sx={{
        p: 1,
        borderRadius: 1.5,
        border: "1px solid #e2e8f0",
        bgcolor: "#fff",
        minHeight: 64,
      }}
    >
      <Typography sx={{ fontSize: 16, fontWeight: 800, color: "#0f172a", lineHeight: 1.15 }}>
        {value}
      </Typography>
      <Typography
        sx={{
          mt: 0.35,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.4,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {label}
      </Typography>
    </Box>
  );
}

/**
 * Management Supplies Dashboard — period reporting + Planning Simulator entry.
 */
export default function ManagementSuppliesDashboardPage() {
  const [period, setPeriod] = useState("last_7");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [simOpen, setSimOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { period };
      if (period === "custom") {
        params.start_et = customStart;
        params.end_et = customEnd;
      }
      const res = await getManagementSuppliesDashboard(params);
      setData(res?.data || null);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, customStart, customEnd]);

  useEffect(() => {
    if (period === "custom" && (!customStart || !customEnd)) return;
    load();
  }, [load, period, customStart, customEnd]);

  const planningDefaults = data
    ? {
        ...(data.planning_defaults || {}),
        unit_costs: data.unit_costs,
      }
    : null;

  return (
    <Box sx={{ ...VEEWASH_DASHBOARD.page, maxWidth: 720, mx: "auto", px: { xs: 1.5, sm: 2 }, pb: 4 }}>
      <ManagementHubNav activeId="rinse_wf" />
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mt: 1.5, mb: 1 }}>
        <Typography sx={{ fontSize: 20, fontWeight: 800 }}>Supplies</Typography>
        <Button
          component={RouterLink}
          to="/management/supply-master"
          size="small"
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          Supply Master
        </Button>
      </Stack>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600, mb: 1.25 }}>
        Period reporting · ESTIMATED cost from Supply Master doses
      </Typography>

      <ToggleButtonGroup
        exclusive
        size="small"
        value={period}
        onChange={(_e, v) => v && setPeriod(v)}
        sx={{ flexWrap: "wrap", mb: 1.25, gap: 0.5 }}
      >
        {PERIODS.map((p) => (
          <ToggleButton
            key={p.id}
            value={p.id}
            sx={{ textTransform: "none", fontWeight: 700, px: 1, py: 0.35 }}
          >
            {p.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      {period === "custom" ? (
        <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, mb: 1.25 }}>
          <TextField
            label="Start ET"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={customStart}
            onChange={(e) => setCustomStart(e.target.value)}
          />
          <TextField
            label="End ET"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={customEnd}
            onChange={(e) => setCustomEnd(e.target.value)}
          />
        </Box>
      ) : null}

      {loading ? (
        <Box sx={{ py: 6, textAlign: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : error ? (
        <Alert severity="error" action={<Button onClick={load}>Retry</Button>}>
          {error}
        </Alert>
      ) : !data?.available ? (
        <Alert severity="info">No WF supply aggregates for this period yet.</Alert>
      ) : (
        <>
          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#334155", mb: 1 }}>
            {data.period_label} · {data.period_start_et}
            {data.period_end_et !== data.period_start_et ? ` → ${data.period_end_et}` : ""}
          </Typography>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)" },
              gap: 0.75,
              mb: 1.25,
            }}
          >
            <Metric label="WF Orders" value={fmtInt(data.wf_orders)} />
            <Metric label="HD Orders" value={fmtInt(data.hd_orders)} />
            <Metric label="PRE Lbs" value={fmtLb(data.pre_lbs)} />
            <Metric label="Loads (est.)" value={fmtInt(data.loads)} />
            <Metric label="Split Rate" value={fmtPct(data.split_pct)} />
            <Metric label="Supply Cost (est.)" value={fmtMoney(data.estimated_supply_cost)} />
            <Metric label="Cost / Order" value={fmtMoney(data.cost_per_order, 2)} />
            <Metric label="Cost / Load" value={fmtMoney(data.cost_per_load, 2)} />
            <Metric label="Est. Cost / Lb" value={fmtMoney(data.est_cost_per_lb, 4)} />
          </Box>

          <Box
            sx={{
              p: 1.25,
              borderRadius: 2,
              border: "1px solid #e2e8f0",
              bgcolor: "#f8fafc",
              mb: 1.5,
            }}
          >
            <Typography sx={{ fontSize: 12, fontWeight: 800, mb: 0.5 }}>
              Order Mix
            </Typography>
            <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#334155" }}>
              Tide {fmtPct(data.tide_pct)} · Ultra Clean {fmtPct(data.ultra_clean_pct)}
            </Typography>
            <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#334155" }}>
              Downy {fmtPct(data.downy_pct)} · OxiClean {fmtPct(data.oxiclean_pct)}
            </Typography>
            <Typography sx={{ fontSize: 10, color: "#94a3b8", mt: 0.5, fontWeight: 600 }}>
              % of orders — Downy/Oxi independent (may overlap)
            </Typography>
          </Box>

          <Button
            variant="contained"
            fullWidth
            onClick={() => setSimOpen(true)}
            sx={{ textTransform: "none", fontWeight: 800, py: 1.1 }}
          >
            Open Planning Simulator
          </Button>
          <Typography sx={{ fontSize: 10, color: "#94a3b8", mt: 1, fontWeight: 600 }}>
            {data.note}
          </Typography>
        </>
      )}

      <SupplyCostSimulatorModal
        mode="planning"
        open={simOpen}
        onClose={() => setSimOpen(false)}
        selectedDateEt={data?.period_end_et}
        planningDefaults={planningDefaults}
        todayWorkloadOrders={data?.planning_defaults?.total_orders}
      />
    </Box>
  );
}
