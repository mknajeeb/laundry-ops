import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getAccountantYtd, getPayoutBatches } from "../api";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

export default function AccountantReportsPanel() {
  const [subTab, setSubTab] = useState(0);
  const [year, setYear] = useState(new Date().getFullYear());
  const [category, setCategory] = useState("all");
  const [ytdRows, setYtdRows] = useState([]);
  const [batches, setBatches] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [ytdRes, batchRes] = await Promise.all([
        getAccountantYtd({ year, worker_category: category !== "all" ? category : undefined }),
        getPayoutBatches(category !== "all" ? { worker_category: category } : {}),
      ]);
      setYtdRows(ytdRes.data?.items || []);
      setBatches(batchRes.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [year, category]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">Accountant Reports</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Read-only reporting for your accountant. Role-based access (accountant_viewer) can be
          added later — use admin access for now.
        </Typography>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          <FormControl size="small" sx={{ minWidth: 100 }}>
            <InputLabel>Year</InputLabel>
            <Select label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[year, year - 1].map((y) => (
                <MenuItem key={y} value={y}>
                  {y}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Category</InputLabel>
            <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </Paper>

      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)}>
        <Tab label="Payout batches" />
        <Tab label="YTD by worker" />
        <Tab label="1099 / Temp summary" />
        <Tab label="W-2 support" />
        <Tab label="Engagement letter" />
      </Tabs>

      {subTab === 0 ? (
        <TableContainer component={Paper} sx={{ overflowX: "auto" }}>
        <Table size="small" sx={{ minWidth: 640 }}>
          <TableHead>
            <TableRow>
              <TableCell>Batch</TableCell>
              <TableCell>Category</TableCell>
              <TableCell>Period</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Payout</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {batches.map((b) => (
              <TableRow key={b.id}>
                <TableCell>{b.batch_name}</TableCell>
                <TableCell>{b.worker_category_label || b.worker_category}</TableCell>
                <TableCell>
                  {b.pay_period_start} – {b.pay_period_end}
                </TableCell>
                <TableCell>{b.status}</TableCell>
                <TableCell align="right">${Number(b.total_payout_amount || 0).toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </TableContainer>
      ) : null}

      {subTab === 1 ? (
        <TableContainer component={Paper} sx={{ overflowX: "auto" }}>
        <Table size="small" sx={{ minWidth: 720 }}>
          <TableHead>
            <TableRow>
              <TableCell>Worker</TableCell>
              <TableCell>Category</TableCell>
              <TableCell align="right">Paid YTD</TableCell>
              <TableCell align="right">Payments</TableCell>
              <TableCell align="right">Avg weekly</TableCell>
              <TableCell align="right">Avg monthly</TableCell>
              <TableCell>Last paid</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {ytdRows.map((r) => (
              <TableRow key={`${r.user_id}-${r.worker_category}`}>
                <TableCell>{r.worker_name}</TableCell>
                <TableCell>{r.worker_category_label}</TableCell>
                <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                <TableCell align="right">{r.payment_count}</TableCell>
                <TableCell align="right">${Number(r.avg_weekly_pay || 0).toFixed(2)}</TableCell>
                <TableCell align="right">${Number(r.avg_monthly_pay || 0).toFixed(2)}</TableCell>
                <TableCell>{r.last_payment_date || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </TableContainer>
      ) : null}

      {subTab === 2 ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            1099 / Temp payment summary ({year})
          </Typography>
          <Table size="small">
            <TableBody>
              {ytdRows
                .filter((r) => r.worker_category !== "w2")
                .map((r) => (
                  <TableRow key={r.user_id}>
                    <TableCell>{r.worker_name}</TableCell>
                    <TableCell>{r.worker_category_label}</TableCell>
                    <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                    <TableCell>
                      {r.reporting_threshold_warning ? (
                        <Typography color="warning.main" variant="caption">
                          Review W-9 / 1099 threshold
                        </Typography>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      {subTab === 3 ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="body2" color="text.secondary">
            W-2 payroll support: gross wages and withholding fields are stored on payout batch
            lines when category is W-2. Full tax engine and paystub generation will be added
            later. Use payout batch summaries for accountant handoff.
          </Typography>
          <Table size="small" sx={{ mt: 2 }}>
            <TableHead>
              <TableRow>
                <TableCell>Worker</TableCell>
                <TableCell align="right">YTD paid (batches)</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ytdRows
                .filter((r) => r.worker_category === "w2")
                .map((r) => (
                  <TableRow key={r.user_id}>
                    <TableCell>{r.worker_name}</TableCell>
                    <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      {subTab === 4 ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Contractor Engagement and Payment Verification Letter
          </Typography>
          <Typography variant="body2" paragraph>
            Planned template for 1099/temp workers requesting proof of work. Print from
            Contractor Management → Forms &amp; Packets when available.
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ fontStyle: "italic" }}>
            “This letter confirms that, according to our records, [Name] provided contractor
            services to VeeWash/Washpro from [date] to [date]. Payments were made for contractor
            services based on approved work records…”
          </Typography>
        </Paper>
      ) : null}
    </Stack>
  );
}
