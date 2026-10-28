import { useMemo } from "react";
import {
  Box,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
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

/**
 * Monthly Task Performance — grouped bars by business day (America/New_York).
 */
export default function TaskDashboardMonthlyChart({
  data,
  year,
  month,
  category,
  categories = [],
  onYearChange,
  onMonthChange,
  onCategoryChange,
  loading = false,
}) {
  const days = data?.days || [];
  const totals = data?.totals || {};
  const chartData = useMemo(
    () =>
      days.map((d) => ({
        day: d.day,
        date: d.business_date,
        Completed: d.completed || 0,
        Pending: d.pending || 0,
        Overdue: d.overdue || 0,
        Verified: d.verified || 0,
      })),
    [days]
  );

  const years = [];
  const nowY = new Date().getFullYear();
  for (let y = nowY - 2; y <= nowY + 1; y += 1) years.push(y);

  return (
    <Paper
      variant="outlined"
      className="task-dashboard-chart"
      sx={{ p: { xs: 1.5, md: 2 }, mb: 2.5 }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ sm: "center" }}
        spacing={1}
        sx={{ mb: 1.5 }}
      >
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>
            Monthly Task Performance
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Shared assignments count once · {totals.completed || 0}/{totals.assigned || 0}{" "}
            completed
            {totals.completion_rate != null ? ` (${totals.completion_rate}%)` : ""}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <TextField
            select
            size="small"
            label="Month"
            value={month}
            onChange={(e) => onMonthChange?.(Number(e.target.value))}
            sx={{ minWidth: 110 }}
          >
            {[
              "January",
              "February",
              "March",
              "April",
              "May",
              "June",
              "July",
              "August",
              "September",
              "October",
              "November",
              "December",
            ].map((label, idx) => (
              <MenuItem key={label} value={idx + 1}>
                {label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Year"
            value={year}
            onChange={(e) => onYearChange?.(Number(e.target.value))}
            sx={{ minWidth: 96 }}
          >
            {years.map((y) => (
              <MenuItem key={y} value={y}>
                {y}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Category"
            value={category || ""}
            onChange={(e) => onCategoryChange?.(e.target.value)}
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">All categories</MenuItem>
            {(categories.length
              ? categories
              : [
                  { code: "start_of_day", name: "Start of Day" },
                  { code: "intra_day", name: "Intra-Day" },
                  { code: "end_of_day", name: "End of Day" },
                  { code: "inventory", name: "Inventory" },
                ]
            ).map((c) => (
              <MenuItem key={c.code} value={c.code}>
                {c.name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </Stack>
      <Box sx={{ width: "100%", height: 280, opacity: loading ? 0.5 : 1 }}>
        <ResponsiveContainer>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="day" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip
              formatter={(value, name) => [value, name]}
              labelFormatter={(label, payload) => {
                const row = payload?.[0]?.payload;
                return row?.date || `Day ${label}`;
              }}
            />
            <Legend />
            <Bar dataKey="Completed" stackId="a" fill="#2e7d32" radius={[2, 2, 0, 0]} />
            <Bar dataKey="Pending" stackId="a" fill="#90a4ae" />
            <Bar dataKey="Overdue" stackId="a" fill="#c62828" />
            <Bar dataKey="Verified" fill="#1565c0" />
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Paper>
  );
}
