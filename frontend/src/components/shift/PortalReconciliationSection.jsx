import {
  Alert,
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
import { formatEtDateTime } from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const METRICS = [
  { key: "at_vendor", label: "At Vendor" },
  { key: "rfv", label: "RFV" },
  { key: "due_today", label: "Due Today" },
  { key: "due_today_yet_to_process", label: "Due Today Yet To Process" },
];

function fmtCount(value) {
  if (value == null) return "—";
  return String(value);
}

function fmtDiff(value) {
  if (value == null) return "—";
  if (value === 0) return "0";
  return value > 0 ? `+${value}` : String(value);
}

/** Side-by-side direct portal scrape vs dashboard-derived counts. */
export default function PortalReconciliationSection({ reconciliation }) {
  const recon = reconciliation || {};
  if (!recon.available || !recon.portal_scrape_at) return null;

  const portalLabel = recon.source_labels?.portal || "Direct Portal";
  const dashboardLabel = recon.source_labels?.dashboard || "Dashboard Derived";
  const portalCounts = recon.portal_counts || {};
  const dashboardCounts = recon.dashboard_counts || {};
  const differences = recon.differences || {};
  const rows = METRICS.filter((m) => portalCounts[m.key] != null && dashboardCounts[m.key] != null);

  if (rows.length === 0) return null;

  const scrapeAtEt = formatEtDateTime(recon.portal_scrape_at);

  return (
    <Paper
      elevation={0}
      sx={{
        mt: 1.25,
        p: { xs: 1, sm: 1.25 },
        borderRadius: 2,
        border: "1px solid",
        borderColor: recon.has_mismatch ? "error.light" : VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: recon.has_mismatch ? "error.50" : "#fff",
      }}
    >
      <Typography
        variant="subtitle2"
        fontWeight={700}
        sx={{ mb: 0.25, color: VEEWASH_DASHBOARD.primaryBlueDark, fontSize: "0.9375rem" }}
      >
        Portal Reconciliation
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
        Portal data as of {scrapeAtEt}
      </Typography>

      {recon.has_mismatch ? (
        <Alert severity="error" sx={{ mb: 1, py: 0.35 }}>
          Dashboard counts do not match direct portal scrape — review before trusting snapshot cards.
        </Alert>
      ) : (
        <Alert severity="success" variant="outlined" sx={{ mb: 1, py: 0.35 }}>
          Dashboard matches direct portal for all compared metrics.
        </Alert>
      )}

      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small" aria-label="Portal reconciliation">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 700, minWidth: 120 }}>Metric</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700, minWidth: 88, whiteSpace: "nowrap" }}>
                {portalLabel}
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 700, minWidth: 88, whiteSpace: "nowrap" }}>
                {dashboardLabel}
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 700, minWidth: 72 }}>Difference</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map(({ key, label }) => {
              const diff = differences[key];
              const mismatch = diff != null && diff !== 0;
              return (
                <TableRow
                  key={key}
                  sx={mismatch ? { bgcolor: "error.50" } : undefined}
                >
                  <TableCell sx={{ fontWeight: 600 }}>{label}</TableCell>
                  <TableCell align="right">{fmtCount(portalCounts[key])}</TableCell>
                  <TableCell align="right">{fmtCount(dashboardCounts[key])}</TableCell>
                  <TableCell
                    align="right"
                    sx={{
                      fontWeight: mismatch ? 800 : 400,
                      color: mismatch ? "error.main" : "text.primary",
                    }}
                  >
                    {fmtDiff(diff)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ mt: 0.75, display: "flex", flexDirection: { xs: "column", sm: "row" }, gap: { xs: 0.25, sm: 1.5 } }}>
        <Typography variant="caption" color="text.secondary">
          {portalLabel}: Vendor Home page scrape / RFV presence crawl
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {dashboardLabel}: org-filtered presence list + RFV queue logic
        </Typography>
      </Box>
    </Paper>
  );
}
