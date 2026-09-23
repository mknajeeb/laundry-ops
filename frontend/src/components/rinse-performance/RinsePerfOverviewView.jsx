import { Box, Grid, Paper, Stack, Typography } from "@mui/material";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  BarChart,
  Bar,
} from "recharts";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import KpiCard from "./KpiCard";
import { cardSx, fmtInt, fmtRate, metricDigits, vsTone } from "./rinsePerfFormat";

function TrendTooltip({ active, payload, label, unit }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
  return (
    <Paper sx={{ p: 1, border: `1px solid ${VEEWASH_BRAND.borderSoft}` }}>
      <Typography variant="caption" fontWeight={700}>
        {label}
      </Typography>
      <Typography variant="body2">
        {fmtRate(row.metric_value, 1)} {unit}
      </Typography>
      <Typography variant="caption" display="block" sx={{ color: VEEWASH_BRAND.inkMuted }}>
        Hours {fmtRate(row.hours, 1)} · Pounds {fmtInt(row.pounds)} · Bags {fmtInt(row.bags)} ·
        Days {fmtInt(row.approved_employee_days)}
      </Typography>
    </Paper>
  );
}

export default function RinsePerfOverviewView({ data, metricKey, unit }) {
  if (!data) return null;
  const kpis = data.kpis || {};
  const digits = metricDigits(metricKey);
  const series = data.daily_series || [];
  const compareSeries = data.compare_daily_series || [];
  const chartData = series.map((d, i) => ({
    ...d,
    compare_metric: compareSeries[i]?.metric_value ?? null,
  }));
  const snapshot = (data.employee_snapshot || []).slice(0, 12);
  const bench =
    metricKey === "lbs_hr" || metricKey === "folding_speed" ? kpis.benchmark : null;
  const pointCount = series.filter((d) => d.metric_value != null).length;

  return (
    <Stack spacing={2}>
      <Grid container spacing={1}>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Team Average"
            value={`${fmtRate(kpis.metric_value, digits)} ${unit}`}
            delta={kpis.deltas?.metric}
          />
        </Grid>
        {bench != null ? (
          <Grid item xs={6} sm={4} md={2}>
            <KpiCard compact label="Target" value={`${fmtRate(bench, 1)} ${unit}`} />
          </Grid>
        ) : null}
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Approved Employee-Days"
            value={fmtInt(kpis.approved_employee_days)}
            delta={kpis.deltas?.approved_employee_days}
          />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Included Hours"
            value={fmtRate(kpis.included_hours, 1)}
            delta={kpis.deltas?.included_hours}
          />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Included Pounds"
            value={fmtInt(kpis.included_pounds)}
            delta={kpis.deltas?.included_pounds}
          />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Included Bags"
            value={fmtInt(kpis.included_bags)}
            delta={kpis.deltas?.included_bags}
          />
        </Grid>
      </Grid>

      <Grid container spacing={1.5}>
        <Grid item xs={12} md={8}>
          <Paper variant="outlined" sx={cardSx()}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Team Performance Trend
            </Typography>
            {pointCount < 1 ? (
              <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted, py: 2 }}>
                No published employee-days in this period.
              </Typography>
            ) : (
              <Box sx={{ width: "100%", height: pointCount <= 2 ? 160 : 240 }}>
                <ResponsiveContainer>
                  <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={VEEWASH_BRAND.borderSoft} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={40} />
                    <Tooltip content={<TrendTooltip unit={unit} />} />
                    {bench != null ? (
                      <ReferenceLine y={bench} stroke={VEEWASH_BRAND.gold} strokeDasharray="4 4" />
                    ) : null}
                    <Line
                      type="monotone"
                      dataKey="metric_value"
                      name="Current"
                      stroke={VEEWASH_BRAND.primary}
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      connectNulls={false}
                    />
                    {compareSeries.length ? (
                      <Line
                        type="monotone"
                        dataKey="compare_metric"
                        name="Compare"
                        stroke={VEEWASH_BRAND.inkSoft}
                        strokeWidth={1.5}
                        strokeDasharray="5 4"
                        dot={false}
                        connectNulls={false}
                      />
                    ) : null}
                  </LineChart>
                </ResponsiveContainer>
              </Box>
            )}
          </Paper>
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={cardSx()}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Employee Performance Snapshot
            </Typography>
            {!snapshot.length ? (
              <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
                No rankable employees.
              </Typography>
            ) : (
              <Box sx={{ width: "100%", height: Math.min(280, 36 + snapshot.length * 28) }}>
                <ResponsiveContainer>
                  <BarChart
                    data={snapshot}
                    layout="vertical"
                    margin={{ top: 0, right: 12, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={VEEWASH_BRAND.borderSoft} />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="name" width={88} tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(v) => [`${fmtRate(v, digits)} ${unit}`, "Metric"]}
                    />
                    {bench != null ? (
                      <ReferenceLine x={bench} stroke={VEEWASH_BRAND.gold} strokeDasharray="4 4" />
                    ) : null}
                    <Bar dataKey="metric_value" fill={VEEWASH_BRAND.primary} radius={[0, 3, 3, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Box>
            )}
            {snapshot.length ? (
              <Stack spacing={0.25} sx={{ mt: 1 }}>
                {snapshot.slice(0, 5).map((e) => (
                  <Typography key={e.employee_id} variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
                    {e.name}: {fmtRate(e.metric_value, digits)} {unit}
                    {e.vs_target != null ? (
                      <span style={{ color: vsTone(e.vs_target) }}>
                        {" "}
                        ({e.vs_target >= 0 ? "+" : ""}
                        {fmtRate(e.vs_target, 1)} vs target)
                      </span>
                    ) : null}
                  </Typography>
                ))}
              </Stack>
            ) : null}
          </Paper>
        </Grid>
      </Grid>
    </Stack>
  );
}
