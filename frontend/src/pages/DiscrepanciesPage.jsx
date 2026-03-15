import { useEffect, useState } from "react";
import {
  Box,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { getOrderDiscrepancies } from "../api";

function fmtDate(v) {
  if (!v) return "-";
  const d = new Date(`${String(v).slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function fmtNum(n, service) {
  const v = Number(n || 0);
  if ((service || "").toUpperCase() === "HD") return `${Math.round(v)} pcs`;
  return `${v.toFixed(2)} lb`;
}

function DiscrepanciesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [batchDate, setBatchDate] = useState("");

  const load = async () => {
    try {
      setLoading(true);
      const res = await getOrderDiscrepancies(batchDate ? { batch_date: batchDate } : {});
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (e) {
      console.error(e);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="end" sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 30, fontWeight: 400 }}>Discrepancies</Typography>
        <TextField
          size="small"
          type="date"
          label="Batch Date"
          InputLabelProps={{ shrink: true }}
          value={batchDate}
          onChange={(e) => setBatchDate(e.target.value)}
          onBlur={load}
        />
      </Stack>
      <Paper sx={{ borderRadius: 2, border: "1px solid #e5e7eb", overflow: "hidden" }}>
        {loading ? (
          <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }}>
            <CircularProgress size={24} />
          </Stack>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Order</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>Service</TableCell>
                <TableCell>Original</TableCell>
                <TableCell>Submitted</TableCell>
                <TableCell>Difference</TableCell>
                <TableCell>Date</TableCell>
                <TableCell>Batch</TableCell>
                <TableCell>By</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} sx={{ color: "#6b7280" }}>
                    No discrepancies found.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>#{r.order_id}</TableCell>
                    <TableCell>{r.name_clean || "-"}</TableCell>
                    <TableCell>{(r.service_type || "").toUpperCase() || "-"}</TableCell>
                    <TableCell>{fmtNum(r.original_measure, r.service_type)}</TableCell>
                    <TableCell>{fmtNum(r.submitted_measure, r.service_type)}</TableCell>
                    <TableCell>{fmtNum(r.difference_measure, r.service_type)}</TableCell>
                    <TableCell>{fmtDate(r.date_clean)}</TableCell>
                    <TableCell>{fmtDate(r.batch_date)}</TableCell>
                    <TableCell>{r.username || "-"}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </Paper>
    </Box>
  );
}

export default DiscrepanciesPage;
