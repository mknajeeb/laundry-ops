import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import MetricCardGrid from "./MetricCardGrid";
import {
  buildLaborCostKpiCards,
  buildLaborKpiCards,
  fmtLaborValue,
} from "../../utils/employeeProductivityHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

function RoleBreakdownCard({ title, metrics, type }) {
  if (!metrics) {
    return (
      <Paper
        variant="outlined"
        sx={{
          p: 1.5,
          borderRadius: 2,
          bgcolor: VEEWASH_DASHBOARD.snapshotBg,
          borderColor: VEEWASH_DASHBOARD.snapshotBorder,
        }}
      >
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.5 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          No Data
        </Typography>
      </Paper>
    );
  }

  const folderItems = [
    { label: "Employees", value: metrics.employees ?? 0 },
    { label: "Total Hours", value: fmtLaborValue(metrics.total_hours, { digits: 2 }) },
    { label: "Bags Completed", value: metrics.bags_completed ?? 0 },
    { label: "Pounds Completed", value: fmtLaborValue(metrics.pounds_completed, { digits: 1 }) },
    { label: "Bags / Hour", value: fmtLaborValue(metrics.bags_per_hour, { digits: 2 }) },
    { label: "Pounds / Hour", value: fmtLaborValue(metrics.pounds_per_hour, { digits: 2 }) },
    { label: "Labor Cost", value: fmtLaborValue(metrics.labor_cost, { currency: true }) },
  ];

  const operatorItems = [
    { label: "Employees", value: metrics.employees ?? 0 },
    { label: "Total Hours", value: fmtLaborValue(metrics.total_hours, { digits: 2 }) },
    { label: "Pounds Processed", value: fmtLaborValue(metrics.pounds_processed, { digits: 1 }) },
    { label: "Labor Cost", value: fmtLaborValue(metrics.labor_cost, { currency: true }) },
  ];

  const items = type === "folder" ? folderItems : operatorItems;

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2,
        bgcolor: "#fff",
        borderColor: type === "folder" ? VEEWASH_DASHBOARD.wfBorder : VEEWASH_DASHBOARD.hdBorder,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
        {title}
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)" },
          gap: 1,
        }}
      >
        {items.map((item) => (
          <Box key={item.label}>
            <Typography variant="caption" color="text.secondary" fontWeight={700} display="block">
              {item.label}
            </Typography>
            <Typography variant="body2" fontWeight={800}>
              {item.value ?? "—"}
            </Typography>
          </Box>
        ))}
      </Box>
    </Paper>
  );
}

export default function EmployeeProductivityLaborSection({ laborSummary }) {
  if (!laborSummary) return null;

  const laborKpis = buildLaborKpiCards(laborSummary);
  const costKpis = buildLaborCostKpiCards(laborSummary);
  const roleBreakdown = laborSummary.role_breakdown || {};
  const employeeDetails = laborSummary.employee_details || [];
  const available = Boolean(laborSummary.available);

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1 }}>
        Labor Metrics
      </Typography>
      {!available ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
          {laborSummary.message || "No labor roster recorded for this date."}
        </Typography>
      ) : null}

      <MetricCardGrid
        sections={[
          {
            key: "labor-kpi",
            title: available ? "Labor Hours & Cost" : undefined,
            layout: "kpi",
            cards: laborKpis.map((card) => ({
              ...card,
              count: card.value,
              size: "kpi",
            })),
          },
          {
            key: "cost-kpi",
            title: available ? "Cost Efficiency" : undefined,
            layout: "kpi",
            cards: costKpis.map((card) => ({
              ...card,
              count: card.value,
              size: "kpi",
            })),
          },
        ]}
      />

      {available ? (
        <>
          <Typography variant="subtitle2" fontWeight={800} sx={{ mt: 2, mb: 1 }}>
            Role Breakdown
          </Typography>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" },
              gap: 1.25,
              mb: 2,
            }}
          >
            <RoleBreakdownCard title="Folders" metrics={roleBreakdown.folders} type="folder" />
            <RoleBreakdownCard title="Operators" metrics={roleBreakdown.operators} type="operator" />
          </Box>

          <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
            Employee Labor Detail
          </Typography>
          <TableContainer
            component={Paper}
            variant="outlined"
            sx={{ borderRadius: 2, boxShadow: VEEWASH_DASHBOARD.cardShadow }}
          >
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 700 }}>Employee</TableCell>
                  <TableCell sx={{ fontWeight: 700 }}>Role</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>Hours</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>Rate</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>Cost</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {employeeDetails.map((row) => (
                  <TableRow key={`${row.employee}-${row.role}`} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{row.employee}</TableCell>
                    <TableCell sx={{ textTransform: "capitalize" }}>{row.role}</TableCell>
                    <TableCell align="right">{fmtLaborValue(row.hours, { digits: 2 })}</TableCell>
                    <TableCell align="right">{fmtLaborValue(row.rate, { currency: true })}</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {fmtLaborValue(row.cost, { currency: true })}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      ) : null}
    </Box>
  );
}
