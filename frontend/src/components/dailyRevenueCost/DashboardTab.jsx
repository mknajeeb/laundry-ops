import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Paper,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import { getDrcDashboard } from "../../api";
import { formatCurrency, formatPercent } from "../../utils/dailyRevenueCostHelpers";
import { SectionCard, SummaryRow } from "./DrcShared";

const PERIODS = [
  { id: "daily", label: "Daily" },
  { id: "weekly", label: "Weekly" },
  { id: "monthly", label: "Monthly" },
  { id: "custom", label: "Custom" },
];

const CATEGORY_LABELS = {
  self_service: "Self Service",
  drop_off: "Drop Off",
  rinse_wf: "Rinse WF",
  rinse_hd: "Rinse HD",
  rinse_wi: "Rinse WI",
  commercial: "Commercial Accounts",
};

function TrendBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min(100, (Number(value) / max) * 100) : 0;
  return (
    <Box sx={{ mb: 1.5 }}>
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
        <Typography variant="body2">{label}</Typography>
        <Typography variant="body2" fontWeight={600}>{formatCurrency(value)}</Typography>
      </Stack>
      <Box sx={{ height: 8, bgcolor: "grey.200", borderRadius: 1, overflow: "hidden" }}>
        <Box sx={{ height: "100%", width: `${pct}%`, bgcolor: color, borderRadius: 1 }} />
      </Box>
    </Box>
  );
}

export default function DashboardTab() {
  const [period, setPeriod] = useState("daily");
  const [refDate, setRefDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { period, date: refDate };
      if (period === "custom") {
        params.start_date = startDate;
        params.end_date = endDate;
      }
      const res = await getDrcDashboard(params);
      setData(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [period, refDate, startDate, endDate]);

  useEffect(() => {
    load();
  }, [load]);

  const maxTrend = Math.max(
    ...(data?.trend || []).flatMap((t) => [Math.abs(t.revenue), Math.abs(t.cost), Math.abs(t.profit)]),
    1,
  );

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

      <SectionCard title="Period">
        <ToggleButtonGroup
          value={period}
          exclusive
          onChange={(_, v) => v && setPeriod(v)}
          size="small"
          sx={{ flexWrap: "wrap", mb: 2 }}
        >
          {PERIODS.map((p) => (
            <ToggleButton key={p.id} value={p.id} sx={{ flex: { xs: "1 1 45%", sm: "0 0 auto" } }}>
              {p.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        {period === "custom" ? (
          <Stack spacing={2}>
            <PlanningDatePicker label="Start Date" value={startDate} onChange={setStartDate} />
            <PlanningDatePicker label="End Date" value={endDate} onChange={setEndDate} />
          </Stack>
        ) : (
          <PlanningDatePicker label="Reference Date" value={refDate} onChange={setRefDate} />
        )}

        {data ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {data.start_date} — {data.end_date}
          </Typography>
        ) : null}
      </SectionCard>

      {data ? (
        <>
          <SectionCard title="Revenue by Category">
            <Stack spacing={1}>
              {Object.entries(data.revenue_by_category || {}).map(([key, val]) => (
                <SummaryRow key={key} label={CATEGORY_LABELS[key] || key} value={val} />
              ))}
              <Box sx={{ borderTop: "1px solid", borderColor: "divider", pt: 1 }}>
                <SummaryRow label="Total Revenue" value={data.total_revenue} emphasize />
              </Box>
            </Stack>
          </SectionCard>

          <SectionCard title="Costs & Profitability">
            <SummaryRow label="Payroll Cost" value={data.payroll_cost} />
            <SummaryRow label="Payroll Tax" value={data.payroll_tax} />
            <SummaryRow label="Fixed Costs" value={data.fixed_costs} />
            <SummaryRow label="Variable Costs" value={data.variable_costs} />
            <SummaryRow label="Operating Costs" value={data.operating_costs} />
            <SummaryRow label="Total Cost" value={data.total_cost} emphasize />
            <SummaryRow label="Estimated Profit" value={data.estimated_profit} emphasize negative />
            <SummaryRow label="Profit Margin" value={formatPercent(data.profit_margin_pct)} emphasize />
          </SectionCard>

          <SectionCard title="Trends" subtitle="Revenue, cost, and profit by day.">
            {(data.trend || []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">No entries in this period.</Typography>
            ) : (
              (data.trend || []).map((point) => (
                <Paper key={point.date} elevation={0} sx={{ p: 2, mb: 2, border: "1px solid", borderColor: "divider" }}>
                  <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                    {point.date}
                  </Typography>
                  <TrendBar label="Revenue" value={point.revenue} max={maxTrend} color="primary.main" />
                  <TrendBar label="Cost" value={point.cost} max={maxTrend} color="warning.main" />
                  <TrendBar label="Profit" value={point.profit} max={maxTrend} color={Number(point.profit) >= 0 ? "success.main" : "error.main"} />
                </Paper>
              ))
            )}
          </SectionCard>
        </>
      ) : null}
    </Box>
  );
}
