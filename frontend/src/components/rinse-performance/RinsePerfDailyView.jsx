import {
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
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import KpiCard from "./KpiCard";
import { cardSx, fmtDelta, fmtInt, fmtRate, metricDigits, statusLabel, vsTone } from "./rinsePerfFormat";

export default function RinsePerfDailyView({ data, metricKey, unit }) {
  if (!data) return null;
  const kpis = data.kpis || {};
  const digits = metricDigits(metricKey);
  const employees = data.employees || [];
  const bench = metricKey === "lbs_hr" ? data.benchmark : null;

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle1" fontWeight={800}>
        {data.business_date_et}
      </Typography>
      <Grid container spacing={1}>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Team Average" value={`${fmtRate(kpis.metric_value, digits)} ${unit}`} />
        </Grid>
        {bench != null ? (
          <Grid item xs={6} sm={4} md={2}>
            <KpiCard compact label="Target" value={`${fmtRate(bench, 1)} ${unit}`} />
          </Grid>
        ) : null}
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Approved Employees" value={fmtInt(kpis.approved_employee_days)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Included Hours" value={fmtRate(kpis.included_hours, 1)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Pounds" value={fmtInt(kpis.included_pounds)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <KpiCard compact label="Bags" value={fmtInt(kpis.included_bags)} />
        </Grid>
      </Grid>

      <Paper variant="outlined" sx={cardSx({ p: 0 })}>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Employee</TableCell>
                <TableCell>Role</TableCell>
                <TableCell align="right">Metric</TableCell>
                <TableCell align="right">vs Target</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell align="right">Pounds</TableCell>
                <TableCell align="right">Bags</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {employees.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8}>
                    <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted, p: 1 }}>
                      No employee-days for this date.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                employees.map((e) => (
                  <TableRow key={e.employee_id}>
                    <TableCell>{e.name}</TableCell>
                    <TableCell>{e.role_key}</TableCell>
                    <TableCell align="right">
                      {e.dashboard_rankable ? fmtRate(e.metric_value, digits) : "—"}
                    </TableCell>
                    <TableCell align="right" sx={{ color: vsTone(e.vs_target) }}>
                      {e.vs_target == null ? "—" : fmtDelta(e.vs_target)}
                    </TableCell>
                    <TableCell align="right">{fmtRate(e.hours, 1)}</TableCell>
                    <TableCell align="right">{fmtInt(e.pounds)}</TableCell>
                    <TableCell align="right">{fmtInt(e.bags)}</TableCell>
                    <TableCell>{statusLabel(e.status)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  );
}
