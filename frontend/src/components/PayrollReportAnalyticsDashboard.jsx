import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function money(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0.00";
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function hours(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatKpiValue(card) {
  if (card.kind === "money") return money(card.value);
  if (card.kind === "hours") return hours(card.value);
  return String(card.value ?? 0);
}

function TrendIcon({ direction }) {
  if (direction === "up") return <TrendingUpIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkMuted }} />;
  if (direction === "down") return <TrendingDownIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkMuted }} />;
  return <TrendingFlatIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkSoft }} />;
}

function KpiCard({ card }) {
  const diff = card.diff;
  const pct = card.pct;
  let deltaText = "vs prior period —";
  if (diff != null) {
    const sign = diff > 0 ? "+" : "";
    deltaText =
      pct == null
        ? `${sign}${card.kind === "money" ? money(diff) : hours(diff)}`
        : `${sign}${card.kind === "money" ? money(diff) : hours(diff)} (${sign}${Number(pct).toFixed(1)}%)`;
  }
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.25,
        height: "100%",
        borderColor: VEEWASH_BRAND.borderSoft,
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
      }}
    >
      <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkSoft, letterSpacing: 0.3 }}>
        {card.label}
      </Typography>
      <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.ink, lineHeight: 1.2 }}>
        {formatKpiValue(card)}
      </Typography>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.5 }}>
        <TrendIcon direction={card.direction} />
        <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {deltaText}
        </Typography>
      </Stack>
    </Paper>
  );
}

function ChartCard({ title, children, height = 240 }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%", borderColor: VEEWASH_BRAND.borderSoft }}>
      <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark, mb: 1 }}>
        {title}
      </Typography>
      <Box sx={{ width: "100%", height }}>
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </Box>
    </Paper>
  );
}

/**
 * Payroll Analytics Dashboard — consumes report.analytics payload only.
 */
export default function PayrollReportAnalyticsDashboard({
  analytics,
  summary,
  comparisonRange,
  onComparisonRangeChange,
}) {
  const kpis = analytics?.kpis || [];
  const periods = analytics?.period_comparison || [];
  const categories = analytics?.category_breakdown || [];
  const overtime = analytics?.overtime_analysis || periods;
  const chartData = periods.map((p) => ({
    ...p,
    label: String(p.pay_period_end || p.payroll_period || "").slice(5),
    fullLabel: p.payroll_period,
  }));
  const catData = categories.map((c) => ({
    ...c,
    name: c.label || c.worker_category,
  }));
  const otChart = overtime.map((o) => ({
    ...o,
    label: String(o.pay_period_end || o.payroll_period || "").slice(5),
    fullLabel: o.payroll_period,
  }));

  return (
    <Stack spacing={2} sx={{ mb: 1 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
      >
        <Box>
          <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            Payroll Analytics
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Periods: {summary?.payroll_period_count ?? "—"} · Pay dates:{" "}
            {summary?.official_pay_date_count ?? "—"} · Workers:{" "}
            {summary?.unique_employees ?? summary?.worker_count ?? "—"} · Gross:{" "}
            {money(summary?.gross_pay)} · Paid: {money(summary?.amount_paid)} · Outstanding:{" "}
            {money(summary?.outstanding_balance)} · EE taxes: {money(summary?.employee_tax_deductions)} ·
            Net: {money(summary?.net_pay)} · ER taxes: {money(summary?.employer_taxes)} · Total cost:{" "}
            {money(summary?.total_payroll_cost)}
          </Typography>
        </Box>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Comparison range</InputLabel>
          <Select
            label="Comparison range"
            value={comparisonRange || analytics?.comparison_range || 4}
            onChange={(e) => onComparisonRangeChange?.(Number(e.target.value))}
          >
            <MenuItem value={4}>Last 4 periods</MenuItem>
            <MenuItem value={8}>Last 8 periods</MenuItem>
            <MenuItem value={12}>Last 12 periods</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gap: 1.25,
          gridTemplateColumns: {
            xs: "repeat(2, minmax(0, 1fr))",
            sm: "repeat(3, minmax(0, 1fr))",
            md: "repeat(4, minmax(0, 1fr))",
            lg: "repeat(6, minmax(0, 1fr))",
          },
        }}
      >
        {kpis.map((card) => (
          <KpiCard key={card.key} card={card} />
        ))}
      </Box>

      <Box
        sx={{
          display: "grid",
          gap: 1.5,
          gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
        }}
      >
        <ChartCard title="Total payroll cost trajectory">
          <AreaChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
            <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
            <Legend />
            <Area type="monotone" dataKey="total_payroll_cost" name="Total cost" stroke="#007a91" fill="#0097b233" />
            <Area type="monotone" dataKey="gross_pay" name="Gross" stroke="#0097b2" fill="transparent" />
            <Area type="monotone" dataKey="net_pay" name="Net" stroke="#c4a052" fill="transparent" />
          </AreaChart>
        </ChartCard>
        <ChartCard title="Hours trajectory">
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(v, name) => [hours(v), name]}
              labelFormatter={(_, p) => {
                const row = p?.[0]?.payload;
                return `${row?.fullLabel || ""} · Total ${hours(row?.total_hours)}`;
              }}
            />
            <Legend />
            <Bar dataKey="regular_hours" name="Regular" stackId="h" fill="#0097b2" />
            <Bar dataKey="ot_hours" name="OT" stackId="h" fill="#c4a052" />
          </BarChart>
        </ChartCard>
        <ChartCard title="Payroll-cost composition">
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
            <Tooltip formatter={(v) => money(v)} />
            <Legend />
            <Bar dataKey="gross_pay" name="Gross" stackId="c" fill="#0097b2" />
            <Bar dataKey="employer_taxes" name="ER taxes" stackId="c" fill="#64748b" />
          </BarChart>
        </ChartCard>
        <ChartCard title="Overtime analysis">
          <ComposedChart data={otChart}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis yAxisId="l" tick={{ fontSize: 11 }} />
            <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v) => money(v)} />
            <Tooltip
              formatter={(v, name) =>
                String(name).toLowerCase().includes("premium")
                  ? [money(v), name]
                  : [hours(v), name]
              }
            />
            <Legend />
            <Bar yAxisId="l" dataKey="ot_hours" name="OT hours" fill="#c4a052" />
            <Line yAxisId="r" type="monotone" dataKey="ot_premium" name="OT premium" stroke="#007a91" strokeWidth={2} />
          </ComposedChart>
        </ChartCard>
        <Box sx={{ gridColumn: { xs: "auto", md: "1 / -1" } }}>
          <ChartCard title="Category comparison (W-2 / Temp / 1099)" height={220}>
            <BarChart data={catData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="l" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(v, name) =>
                  String(name).toLowerCase().includes("hour") ? [hours(v), name] : [money(v), name]
                }
              />
              <Legend />
              <Bar yAxisId="l" dataKey="total_payroll_cost" name="Payroll cost" fill="#0097b2" />
              <Bar yAxisId="r" dataKey="total_hours" name="Hours" fill="#94a3b8" />
            </BarChart>
          </ChartCard>
        </Box>
      </Box>

      <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft }}>
        <Box sx={{ px: 1.5, py: 1 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            Period comparison
          </Typography>
        </Box>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                {[
                  "Payroll Period",
                  "Pay Date(s)",
                  "Workers",
                  "Reg hrs",
                  "OT hrs",
                  "Total hrs",
                  "Base",
                  "OT prem",
                  "Gross",
                  "EE taxes",
                  "Net",
                  "ER taxes",
                  "Total cost",
                  "Paid",
                  "Outstanding",
                  "$/hr",
                  "Δ cost",
                ].map((h) => (
                  <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark }}>
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {periods.map((p) => {
                const dCost = p.delta_from_previous?.total_payroll_cost;
                const pCost = p.pct_from_previous?.total_payroll_cost;
                return (
                  <TableRow key={p.payroll_period} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{p.payroll_period}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{p.pay_dates_label || "—"}</TableCell>
                    <TableCell align="right">{p.worker_count}</TableCell>
                    <TableCell align="right">{hours(p.regular_hours)}</TableCell>
                    <TableCell align="right">{hours(p.ot_hours)}</TableCell>
                    <TableCell align="right">{hours(p.total_hours)}</TableCell>
                    <TableCell align="right">{money(p.base_earnings)}</TableCell>
                    <TableCell align="right">{money(p.ot_premium)}</TableCell>
                    <TableCell align="right">{money(p.gross_pay)}</TableCell>
                    <TableCell align="right">{money(p.employee_tax_deductions)}</TableCell>
                    <TableCell align="right">{money(p.net_pay)}</TableCell>
                    <TableCell align="right">{money(p.employer_taxes)}</TableCell>
                    <TableCell align="right">{money(p.total_payroll_cost)}</TableCell>
                    <TableCell align="right">{money(p.amount_paid)}</TableCell>
                    <TableCell align="right">{money(p.outstanding_balance)}</TableCell>
                    <TableCell align="right">
                      {p.avg_cost_per_hour == null ? "—" : money(p.avg_cost_per_hour)}
                    </TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                      {dCost == null
                        ? "—"
                        : `${dCost > 0 ? "+" : ""}${money(dCost)}${
                            pCost == null ? "" : ` (${pCost > 0 ? "+" : ""}${Number(pCost).toFixed(1)}%)`
                          }`}
                    </TableCell>
                  </TableRow>
                );
              })}
              {!periods.length ? (
                <TableRow>
                  <TableCell colSpan={17}>No comparison periods available.</TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  );
}
