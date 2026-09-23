import { Fragment, useState } from "react";
import {
  Alert,
  Box,
  Collapse,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import KpiCard from "./KpiCard";
import {
  cardSx,
  fmtDelta,
  fmtInt,
  fmtRate,
  metricDigits,
  statusLabel,
  vsTone,
} from "./rinsePerfFormat";

export default function RinsePerfByEmployeeView({ data, metricKey, unit }) {
  const [expandedDay, setExpandedDay] = useState(null);
  if (!data) {
    return (
      <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
        Select an employee to view period performance.
      </Typography>
    );
  }
  const summary = data.summary || {};
  const digits = metricDigits(metricKey);
  const days = data.employee_days || [];
  const publishedPoints = days.filter((d) => d.dashboard_rankable && d.metric_value != null);
  const bench = metricKey === "lbs_hr" ? data.benchmark : null;
  const recent = data.recent_sessions_diagnostic || [];

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle1" fontWeight={800}>
        {data.name || "Employee"}
      </Typography>

      <Grid container spacing={1}>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Folding Speed"
            value={`${fmtRate(summary.metric_value, digits)} ${unit}`}
            delta={data.deltas?.metric}
          />
        </Grid>
        {bench != null ? (
          <Grid item xs={6} sm={4} md={2}>
            <KpiCard
              compact
              label="vs Target"
              value={summary.vs_target == null ? "—" : fmtDelta(summary.vs_target)}
            />
          </Grid>
        ) : null}
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard
            compact
            label="Approved Days"
            value={fmtInt(summary.approved_employee_days)}
            delta={data.deltas?.approved_employee_days}
          />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Hours" value={fmtRate(summary.included_hours, 1)} delta={data.deltas?.included_hours} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Pounds" value={fmtInt(summary.included_pounds)} delta={data.deltas?.included_pounds} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Bags" value={fmtInt(summary.included_bags)} delta={data.deltas?.included_bags} />
        </Grid>
      </Grid>

      <Paper variant="outlined" sx={cardSx()}>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
          Employee Performance Trend
        </Typography>
        <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted, display: "block", mb: 1 }}>
          One point per employee-day (Published days only drive the period rate).
        </Typography>
        {publishedPoints.length === 0 ? (
          <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
            No approved employee-days in this period.
          </Typography>
        ) : publishedPoints.length === 1 ? (
          <Box
            sx={{
              py: 1.5,
              px: 2,
              borderRadius: 1,
              bgcolor: VEEWASH_BRAND.primaryLight,
              display: "inline-block",
            }}
          >
            <Typography variant="h6" fontWeight={800} sx={{ color: VEEWASH_BRAND.primaryDark }}>
              {publishedPoints[0].date} · {fmtRate(publishedPoints[0].metric_value, digits)} {unit}
            </Typography>
          </Box>
        ) : (
          <Box sx={{ width: "100%", height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={days}>
                <CartesianGrid strokeDasharray="3 3" stroke={VEEWASH_BRAND.borderSoft} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={40} />
                <Tooltip />
                {bench != null ? (
                  <ReferenceLine y={bench} stroke={VEEWASH_BRAND.gold} strokeDasharray="4 4" />
                ) : null}
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
        )}
      </Paper>

      <Paper variant="outlined" sx={cardSx()}>
        <Typography variant="subtitle2" fontWeight={700}>
          Recent Sessions
        </Typography>
        <Alert severity="info" sx={{ my: 1, py: 0.5 }}>
          Diagnostic only — last 3 relevant sessions for comparison. Not used in Published period
          metrics.
        </Alert>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Session</TableCell>
                <TableCell>Role</TableCell>
                <TableCell align="right">Pounds</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell align="right">lb/hr</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {recent.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
                      No recent sessions.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                recent.map((s) => (
                  <TableRow key={s.session_id}>
                    <TableCell>{s.date}</TableCell>
                    <TableCell>{s.session_code || s.session_id}</TableCell>
                    <TableCell>{s.role_key}</TableCell>
                    <TableCell align="right">{fmtInt(s.pounds)}</TableCell>
                    <TableCell align="right">{fmtRate(s.hours, 1)}</TableCell>
                    <TableCell align="right">{fmtRate(s.lbs_hr, 1)}</TableCell>
                    <TableCell>{statusLabel(s.status)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Paper variant="outlined" sx={cardSx({ p: 0 })}>
        <Box sx={{ px: 1.5, pt: 1.25 }}>
          <Typography variant="subtitle2" fontWeight={700}>
            Employee-Days
          </Typography>
        </Box>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Date</TableCell>
                <TableCell align="right">Metric</TableCell>
                <TableCell align="right">vs Target</TableCell>
                <TableCell align="right">Pounds</TableCell>
                <TableCell align="right">Bags</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {days.map((d) => (
                <Fragment key={d.date}>
                  <TableRow
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => setExpandedDay((x) => (x === d.date ? null : d.date))}
                  >
                    <TableCell>{d.date}</TableCell>
                    <TableCell align="right">{fmtRate(d.metric_value, digits)}</TableCell>
                    <TableCell align="right" sx={{ color: vsTone(d.vs_target) }}>
                      {d.vs_target == null ? "—" : fmtDelta(d.vs_target)}
                    </TableCell>
                    <TableCell align="right">{fmtInt(d.pounds)}</TableCell>
                    <TableCell align="right">{fmtInt(d.bags)}</TableCell>
                    <TableCell align="right">{fmtRate(d.hours, 1)}</TableCell>
                    <TableCell>{statusLabel(d.status)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell colSpan={7} sx={{ py: 0, border: 0 }}>
                      <Collapse in={expandedDay === d.date} unmountOnExit>
                        <Box sx={{ py: 1, pl: 2 }}>
                          <Typography variant="caption" fontWeight={700} sx={{ mb: 0.5, display: "block" }}>
                            Sessions
                          </Typography>
                          <Table size="small">
                            <TableHead>
                              <TableRow>
                                <TableCell>Code</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell align="right">Bags</TableCell>
                                <TableCell align="right">Pounds</TableCell>
                                <TableCell align="right">Hours</TableCell>
                                <TableCell align="right">lb/hr</TableCell>
                              </TableRow>
                            </TableHead>
                            <TableBody>
                              {(d.sessions || []).map((s) => (
                                <TableRow key={s.session_id || s.session_code}>
                                  <TableCell>{s.session_code || s.session_id}</TableCell>
                                  <TableCell>{statusLabel(s.publication_status)}</TableCell>
                                  <TableCell align="right">{fmtInt(s.orders_completed)}</TableCell>
                                  <TableCell align="right">{fmtInt(s.total_pre_lbs)}</TableCell>
                                  <TableCell align="right">{fmtRate(s.performance_hours, 1)}</TableCell>
                                  <TableCell align="right">{fmtRate(s.lbs_per_hour, 1)}</TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  );
}
