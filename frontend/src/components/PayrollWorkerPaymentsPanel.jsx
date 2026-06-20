import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Chip,
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
import { getWorkerPayments } from "../api";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

export default function PayrollWorkerPaymentsPanel() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [category, setCategory] = useState("all");
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await getWorkerPayments({ year });
      setRows(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [year]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = rows.filter(
    (r) => category === "all" || r.worker_category === category,
  );

  return (
    <Stack spacing={2}>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Worker payment records
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Per-person payout history and year-to-date totals.
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
            <InputLabel>Worker type</InputLabel>
            <Select label="Worker type" value={category} onChange={(e) => setCategory(e.target.value)}>
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </Paper>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Type</TableCell>
              <TableCell align="right">Rate</TableCell>
              <TableCell>Payment method</TableCell>
              <TableCell align="right">Open unpaid</TableCell>
              <TableCell align="right">Paid YTD</TableCell>
              <TableCell>Last paid</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((r) => (
              <TableRow key={`${r.user_id}-${r.worker_category}`} hover>
                <TableCell>{r.worker_name}</TableCell>
                <TableCell>{r.worker_category_label}</TableCell>
                <TableCell align="right">
                  {r.rate_missing ? (
                    <Typography component="span" color="warning.main" variant="body2">
                      Missing
                    </Typography>
                  ) : (
                    `$${Number(r.hourly_rate || 0).toFixed(2)}`
                  )}
                </TableCell>
                <TableCell>{r.payment_method || "—"}</TableCell>
                <TableCell align="right">${Number(r.open_unpaid_amount || 0).toFixed(2)}</TableCell>
                <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                <TableCell>{r.last_payment_date || "—"}</TableCell>
                <TableCell>
                  {Number(r.open_unpaid_amount || 0) > 0 ? (
                    <Chip size="small" color="warning" label="Unpaid balance" />
                  ) : (
                    <Chip size="small" color="success" label="Current" />
                  )}
                </TableCell>
              </TableRow>
            ))}
            {!filtered.length ? (
              <TableRow>
                <TableCell colSpan={8}>
                  <Typography color="text.secondary">No workers for these filters.</Typography>
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}
