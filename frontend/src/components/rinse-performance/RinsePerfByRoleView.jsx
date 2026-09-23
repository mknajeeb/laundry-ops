import { Box, Paper, Stack, Typography } from "@mui/material";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from "@mui/material";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import { cardSx, fmtDelta, fmtInt, fmtRate, metricDigits, vsTone } from "./rinsePerfFormat";

export default function RinsePerfByRoleView({ data, metricKey, unit, onSelectRole }) {
  if (!data) return null;
  const roles = data.roles || [];
  const live = roles.filter((r) => r.enabled);
  const digits = metricDigits(metricKey);
  const primary = live[0];
  const series = primary?.daily_series || [];

  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={cardSx({ p: 0 })}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Role</TableCell>
                <TableCell align="right">Metric</TableCell>
                <TableCell align="right">vs Target</TableCell>
                <TableCell align="right">Employee-Days</TableCell>
                <TableCell align="right">Employees</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell align="right">Pounds</TableCell>
                <TableCell align="right">Bags</TableCell>
                <TableCell align="center">Trend</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {roles.map((r) => (
                <TableRow
                  key={r.role_key}
                  hover={r.enabled}
                  sx={{
                    cursor: r.enabled ? "pointer" : "default",
                    opacity: r.enabled ? 1 : 0.55,
                  }}
                  onClick={() => r.enabled && onSelectRole?.(r.role_key)}
                >
                  <TableCell>
                    <Typography variant="body2" fontWeight={700}>
                      {r.display_name}
                    </Typography>
                    {!r.enabled ? (
                      <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkSoft }}>
                        Coming soon
                      </Typography>
                    ) : null}
                  </TableCell>
                  <TableCell align="right">
                    {r.enabled ? `${fmtRate(r.metric_value, digits)} ${unit}` : "—"}
                  </TableCell>
                  <TableCell align="right" sx={{ color: vsTone(r.vs_target) }}>
                    {r.vs_target == null ? "—" : fmtDelta(r.vs_target)}
                  </TableCell>
                  <TableCell align="right">{r.enabled ? fmtInt(r.employee_days) : "—"}</TableCell>
                  <TableCell align="right">{r.enabled ? fmtInt(r.employees) : "—"}</TableCell>
                  <TableCell align="right">{r.enabled ? fmtRate(r.hours, 1) : "—"}</TableCell>
                  <TableCell align="right">{r.enabled ? fmtInt(r.pounds) : "—"}</TableCell>
                  <TableCell align="right">{r.enabled ? fmtInt(r.bags) : "—"}</TableCell>
                  <TableCell align="center">
                    {r.trend === "up" ? "↑" : r.trend === "down" ? "↓" : r.enabled ? "—" : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {primary ? (
        <Paper variant="outlined" sx={cardSx()}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            {primary.display_name} trend
          </Typography>
          <Box sx={{ width: "100%", height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" stroke={VEEWASH_BRAND.borderSoft} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={40} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="metric_value"
                  stroke={VEEWASH_BRAND.primary}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </Box>
        </Paper>
      ) : null}
    </Stack>
  );
}
