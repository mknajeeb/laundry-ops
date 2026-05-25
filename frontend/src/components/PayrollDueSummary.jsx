import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
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
import { getPayrollDue } from "../api";

const CATEGORY_ORDER = [
  { key: "w2", color: "primary" },
  { key: "contractor_1099", color: "secondary" },
  { key: "temp", color: "warning" },
];

export default function PayrollDueSummary({ fromDate = "", toDate = "" }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!fromDate || !toDate) {
      setData(null);
      return;
    }
    setError("");
    try {
      const res = await getPayrollDue({ from_date: fromDate, to_date: toDate });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load payroll due");
    }
  }, [fromDate, toDate]);

  useEffect(() => {
    load();
  }, [load]);

  if (!fromDate || !toDate) {
    return (
      <Alert severity="info">
        Set a pay period date range to see approved payroll due before creating a batch.
      </Alert>
    );
  }

  const categories = data?.categories || {};

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle1" sx={{ mb: 1 }}>
        Payroll due ({fromDate} – {toDate})
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      ) : null}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
        {CATEGORY_ORDER.map(({ key, color }) => {
          const cat = categories[key] || {};
          return (
            <Box
              key={key}
              sx={{
                flex: 1,
                p: 1.5,
                borderRadius: 1,
                border: 1,
                borderColor: "divider",
              }}
            >
              <Chip size="small" color={color} label={cat.label || key} sx={{ mb: 0.5 }} />
              <Typography variant="h6">${Number(cat.gross || 0).toFixed(2)}</Typography>
              <Typography variant="body2" color="text.secondary">
                {Number(cat.hours || 0).toFixed(2)} hrs · {cat.workers || 0} worker(s)
              </Typography>
              {cat.missing_rates ? (
                <Typography variant="caption" color="warning.main">
                  {cat.missing_rates} missing rate(s)
                </Typography>
              ) : null}
            </Box>
          );
        })}
        <Box
          sx={{
            flex: 1,
            p: 1.5,
            borderRadius: 1,
            bgcolor: "action.hover",
          }}
        >
          <Typography variant="overline">Total due</Typography>
          <Typography variant="h5">${Number(data?.grand_total || 0).toFixed(2)}</Typography>
          <Typography variant="body2" color="text.secondary">
            {Number(data?.grand_hours || 0).toFixed(2)} approved hours
          </Typography>
        </Box>
      </Stack>
      {(data?.workers || []).length ? (
        <TableContainer sx={{ maxHeight: 220 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>Worker</TableCell>
                <TableCell>Type</TableCell>
                <TableCell align="right">Hours</TableCell>
                <TableCell align="right">Rate</TableCell>
                <TableCell align="right">Due</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.workers.map((w) => (
                <TableRow key={`${w.worker_category}-${w.user_id}`}>
                  <TableCell>{w.worker_name}</TableCell>
                  <TableCell>{w.worker_category_label}</TableCell>
                  <TableCell align="right">{Number(w.approved_hours || 0).toFixed(2)}</TableCell>
                  <TableCell align="right">
                    {w.rate_missing ? (
                      <Typography component="span" color="warning.main" variant="body2">
                        Missing
                      </Typography>
                    ) : (
                      `$${Number(w.hourly_rate || 0).toFixed(2)}`
                    )}
                  </TableCell>
                  <TableCell align="right">${Number(w.gross_due || 0).toFixed(2)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No approved time in this period yet. Approve records on the Time Records tab.
        </Typography>
      )}
    </Paper>
  );
}
