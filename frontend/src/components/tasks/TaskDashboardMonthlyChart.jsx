import { useMemo } from "react";
import { Box, Paper } from "@mui/material";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const SERIES = [
  ["not_started", "Not started", "#90a4ae"],
  ["in_progress", "In progress", "#1565c0"],
  ["pending_verification", "Pending verification", "#ef6c00"],
  ["verified", "Verified", "#2e7d32"],
  ["overdue", "Overdue", "#c62828"],
  ["needs_correction", "Needs correction", "#6a1b9a"],
];

/**
 * Compact stacked columns. Each assignment is in exactly one series.
 */
export default function TaskDashboardMonthlyChart({ data, loading = false }) {
  const chartData = useMemo(() => {
    const buckets = data?.buckets;
    const source = Array.isArray(buckets) && buckets.length ? buckets : data?.days || [];
    return source.map((row) => {
      const chart = row.chart || row;
      return {
        label: row.label || row.business_date || row.day,
        "Not started": chart.not_started || 0,
        "In progress": chart.in_progress || 0,
        "Pending verification": chart.pending_verification || 0,
        Verified: chart.verified || 0,
        Overdue: chart.overdue || 0,
        "Needs correction": chart.needs_correction || 0,
      };
    });
  }, [data]);

  return (
    <Paper variant="outlined" className="task-dashboard-chart" sx={{ p: 1, mb: 1.5 }}>
      <Box className="task-dashboard-chart-plot" sx={{ width: "100%", height: 168, opacity: loading ? 0.5 : 1 }}>
        <ResponsiveContainer>
          <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 10 }} width={28} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {SERIES.map(([key, label, fill]) => (
              <Bar key={key} dataKey={label} stackId="status" fill={fill} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Paper>
  );
}
