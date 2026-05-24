import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
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
import { getRinseOrderArchiveDetail, searchRinseOrders } from "../api";
import { formatRinseApiDateTime } from "../utils/rinseTimeFormat";

export default function RinseOrderSearchPage() {
  const [bagId, setBagId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [completionStatus, setCompletionStatus] = useState("");
  const [foldingStatus, setFoldingStatus] = useState("");
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selectedBag, setSelectedBag] = useState("");
  const [message, setMessage] = useState({ type: "", text: "" });
  const [loading, setLoading] = useState(false);

  const search = async () => {
    try {
      setLoading(true);
      setMessage({ type: "", text: "" });
      const params = { limit: 100 };
      if (bagId.trim()) params.bag_id = bagId.trim();
      if (customerName.trim()) params.customer_name = customerName.trim();
      if (dateFrom) params.date_clean_from = dateFrom;
      if (dateTo) params.date_clean_to = dateTo;
      if (completionStatus.trim()) params.completion_status = completionStatus.trim();
      if (foldingStatus.trim()) params.folding_status = foldingStatus.trim();
      const res = await searchRinseOrders(params);
      setRows(res.data?.rows || []);
      setSummary(res.data?.summary || null);
      setDetail(null);
      setSelectedBag("");
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Search failed" });
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (id) => {
    const bid = String(id || "").trim();
    if (!bid) return;
    try {
      setLoading(true);
      setSelectedBag(bid);
      const res = await getRinseOrderArchiveDetail(bid);
      setDetail(res.data);
    } catch (e) {
      setDetail(null);
      setMessage({ type: "error", text: e?.response?.data?.error || "Detail failed" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} gutterBottom>Rinse Order Search</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Full bag lifecycle archive — registry, uploads, checkout, scans, folding, and scrape source.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} flexWrap="wrap">
          <TextField size="small" label="Bag ID / ticket" value={bagId} onChange={(e) => setBagId(e.target.value)} />
          <TextField size="small" label="Customer name" value={customerName} onChange={(e) => setCustomerName(e.target.value)} />
          <TextField size="small" type="date" label="Cleaning date from" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="date" label="Cleaning date to" value={dateTo} onChange={(e) => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" label="Completion status" value={completionStatus} onChange={(e) => setCompletionStatus(e.target.value)} placeholder="COMPLETED" />
          <TextField size="small" label="Folding status" value={foldingStatus} onChange={(e) => setFoldingStatus(e.target.value)} placeholder="CALCULATED / EXCEPTION" />
          <Button variant="contained" onClick={search} disabled={loading}>Search</Button>
        </Stack>
      </Paper>

      {message.text ? <Alert severity={message.type || "info"} sx={{ mb: 2 }}>{message.text}</Alert> : null}

      {summary ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Chip label={`Registry: ${summary.registry_total ?? 0}`} />
          <Chip label={`Completed: ${summary.completed ?? 0}`} color="success" variant="outlined" />
          <Chip label={`Incomplete: ${summary.incomplete ?? 0}`} variant="outlined" />
          <Chip label={`In checkout: ${summary.in_checkout ?? 0}`} color="info" variant="outlined" />
          <Chip label={`Folding exceptions: ${summary.folding_exceptions ?? 0}`} color="warning" variant="outlined" />
        </Stack>
      ) : null}

      <Paper variant="outlined" sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Bag ID</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell>Cleaning date</TableCell>
              <TableCell>Completion</TableCell>
              <TableCell>Folding</TableCell>
              <TableCell>Checkout</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.bag_id} hover selected={selectedBag === r.bag_id}>
                <TableCell>{r.bag_id}</TableCell>
                <TableCell>{r.name_clean || "—"}</TableCell>
                <TableCell>{r.date_clean || "—"}</TableCell>
                <TableCell>{r.completion_status || "—"}</TableCell>
                <TableCell>
                  {r.folding_status || "—"}
                  {r.folding_exception_code ? ` (${r.folding_exception_code})` : ""}
                </TableCell>
                <TableCell>{r.in_checkout ? "Active" : "—"}</TableCell>
                <TableCell>
                  <Button size="small" onClick={() => openDetail(r.bag_id)}>Detail</Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 3, color: "text.secondary" }}>
                  Run a search to see results.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      {detail ? (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>
            {detail.bag_id || selectedBag}
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {detail.registry?.name_clean} · {detail.registry?.date_clean} · {detail.registry?.completion_status}
          </Typography>
          {detail.staging ? (
            <Alert severity="info" sx={{ mb: 1 }}>Active in checkout (staging #{detail.staging.id})</Alert>
          ) : null}
          {detail.upload_history?.length ? (
            <>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1 }}>Upload history</Typography>
              <Typography variant="caption" color="text.secondary">
                {detail.upload_history.length} batch row(s)
              </Typography>
            </>
          ) : null}
          {detail.folding_performance ? (
            <Typography variant="body2" sx={{ mt: 1 }}>
              Folding: {detail.folding_performance.status}
              {detail.folding_performance.exception_code ? ` — ${detail.folding_performance.exception_code}` : ""}
            </Typography>
          ) : null}
          {detail.scheduled_scrape_status?.data_last_updated_at_et ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              Data last updated: {formatRinseApiDateTime(detail.scheduled_scrape_status.data_last_updated_at_et)}
            </Typography>
          ) : null}
        </Paper>
      ) : null}
    </Box>
  );
}
