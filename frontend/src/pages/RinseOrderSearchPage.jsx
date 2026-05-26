import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import OrderSearchDetailDrawer from "../components/orderSearch/OrderSearchDetailDrawer";

const LIFECYCLE_CHIPS = [
  { key: "completed", label: "Completed", param: { lifecycle_filter: "completed" }, color: "success" },
  { key: "incomplete", label: "Incomplete", param: { lifecycle_filter: "incomplete" } },
  { key: "in_checkout", label: "In checkout", param: { lifecycle_filter: "in_checkout" }, color: "info" },
  { key: "folding_exceptions", label: "Folding exceptions", param: { lifecycle_filter: "folding_exceptions" }, color: "warning" },
];

export default function RinseOrderSearchPage() {
  const [searchParams] = useSearchParams();
  const [bagId, setBagId] = useState("");
  const [customerSearch, setCustomerSearch] = useState("");
  const [dateFrom, setDateFrom] = useState(() => searchParams.get("date_clean_from") || "");
  const [dateTo, setDateTo] = useState(() => searchParams.get("date_clean_to") || "");
  const [completionStatus, setCompletionStatus] = useState("");
  const [foldingStatus, setFoldingStatus] = useState("");
  const [lifecycleFilter, setLifecycleFilter] = useState(
    () => searchParams.get("lifecycle_filter") || ""
  );
  const [rushType, setRushType] = useState(
    () => searchParams.get("rush_type") || searchParams.get("rush") || ""
  );
  const [serviceType, setServiceType] = useState(
    () => searchParams.get("service_type") || searchParams.get("service") || ""
  );
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selectedBag, setSelectedBag] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

  const buildSearchParams = useCallback(
    (extra = {}) => {
      const params = { limit: 100 };
      if (bagId.trim()) params.bag_id = bagId.trim();
      if (customerSearch.trim()) {
        params.wild_search = customerSearch.trim();
        params.customer_name = customerSearch.trim();
      }
      const df = extra.date_clean_from !== undefined ? extra.date_clean_from : dateFrom;
      const dt = extra.date_clean_to !== undefined ? extra.date_clean_to : dateTo;
      if (df) params.date_clean_from = df;
      if (dt) params.date_clean_to = dt;
      if (completionStatus.trim()) params.completion_status = completionStatus.trim();
      if (foldingStatus.trim()) params.folding_status = foldingStatus.trim();
      const lf =
        extra.lifecycle_filter !== undefined ? extra.lifecycle_filter : lifecycleFilter;
      if (lf) params.lifecycle_filter = lf;
      const rt = extra.rush_type !== undefined ? extra.rush_type : rushType;
      const st = extra.service_type !== undefined ? extra.service_type : serviceType;
      if (rt) params.rush_type = rt;
      if (st) params.service_type = st;
      return params;
    },
    [
      bagId,
      customerSearch,
      dateFrom,
      dateTo,
      completionStatus,
      foldingStatus,
      lifecycleFilter,
      rushType,
      serviceType,
    ]
  );

  useEffect(() => {
    const df = searchParams.get("date_clean_from") || "";
    const dt = searchParams.get("date_clean_to") || "";
    const lf = searchParams.get("lifecycle_filter") || "";
    const rf = searchParams.get("rush_type") || searchParams.get("rush") || "";
    const sf = searchParams.get("service_type") || searchParams.get("service") || "";
    if (df) setDateFrom(df);
    if (dt) setDateTo(dt);
    if (lf) {
      setLifecycleFilter(lf);
      if (lf === "completed") setCompletionStatus("COMPLETED");
      if (lf === "folding_exceptions") setFoldingStatus("EXCEPTION");
    }
    if (rf) setRushType(rf);
    if (sf) setServiceType(sf);
    if (df || dt || lf || rf || sf) {
      search({
        date_clean_from: df || undefined,
        date_clean_to: dt || undefined,
        lifecycle_filter: lf || undefined,
        rush_type: rf || undefined,
        service_type: sf || undefined,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const search = async (extra = {}) => {
    try {
      setLoading(true);
      setMessage({ type: "", text: "" });
      const res = await searchRinseOrders(buildSearchParams(extra));
      setRows(res.data?.rows || []);
      setSummary(res.data?.summary || null);
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Search failed" });
    } finally {
      setLoading(false);
    }
  };

  const applyLifecycleChip = (key) => {
    const next = lifecycleFilter === key ? "" : key;
    setLifecycleFilter(next);
    if (next === "completed") setCompletionStatus("COMPLETED");
    else if (next === "incomplete") setCompletionStatus("");
    else if (next === "folding_exceptions") setFoldingStatus("EXCEPTION");
    else {
      setCompletionStatus("");
      setFoldingStatus("");
    }
    search({ lifecycle_filter: next || "" });
  };

  const [detailError, setDetailError] = useState("");

  const openDetail = async (id) => {
    const bid = String(id || "").trim();
    if (!bid) return;
    setDrawerOpen(true);
    setSelectedBag(bid);
    setDetail({ bag_id: bid, scan_events: [], upload_history: [], staging_history: [], section_errors: {} });
    setDetailError("");
    setMessage({ type: "", text: "" });
    try {
      setDetailLoading(true);
      const res = await getRinseOrderArchiveDetail(bid);
      setDetail(res.data);
      const errs = res.data?.section_errors;
      if (errs && Object.keys(errs).length) {
        setDetailError(`Some sections could not load: ${Object.keys(errs).join(", ")}`);
      }
    } catch (e) {
      const errText = e?.response?.data?.error || e?.message || "Detail failed";
      setDetailError(errText);
      setDetail((prev) => ({
        ...(prev || {}),
        bag_id: bid,
        scan_events: [],
        upload_history: [],
        staging_history: [],
        section_errors: { _request: errText },
      }));
      setMessage({ type: "error", text: errText });
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDrawer = () => {
    setDrawerOpen(false);
    setDetail(null);
    setDetailError("");
    setSelectedBag("");
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} gutterBottom>
        Rinse Order Search
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Full bag lifecycle archive — registry, uploads, checkout, scans, folding, and scrape source.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} flexWrap="wrap">
          <TextField size="small" label="Bag ID (partial OK)" value={bagId} onChange={(e) => setBagId(e.target.value)} />
          <TextField
            size="small"
            label="Customer / user search"
            value={customerSearch}
            onChange={(e) => setCustomerSearch(e.target.value)}
            placeholder="step, davis, stephanie…"
          />
          <TextField size="small" type="date" label="Cleaning date from" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="date" label="Cleaning date to" value={dateTo} onChange={(e) => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" label="Completion status" value={completionStatus} onChange={(e) => setCompletionStatus(e.target.value)} placeholder="COMPLETED" />
          <TextField size="small" label="Folding status" value={foldingStatus} onChange={(e) => setFoldingStatus(e.target.value)} placeholder="CALCULATED / EXCEPTION" />
          <Button variant="contained" onClick={() => search()} disabled={loading}>
            Search
          </Button>
          {lifecycleFilter ? (
            <Button size="small" onClick={() => { setLifecycleFilter(""); search(); }}>
              Clear filter
            </Button>
          ) : null}
        </Stack>
      </Paper>

      {message.text ? <Alert severity={message.type || "info"} sx={{ mb: 2 }}>{message.text}</Alert> : null}

      {summary ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Chip label={`Registry: ${summary.registry_total ?? 0}`} />
          {LIFECYCLE_CHIPS.map((c) => (
            <Chip
              key={c.key}
              label={`${c.label}: ${summary[c.key] ?? 0}`}
              color={lifecycleFilter === c.key ? c.color || "primary" : c.color}
              variant={lifecycleFilter === c.key ? "filled" : "outlined"}
              onClick={() => applyLifecycleChip(c.key)}
              sx={{ cursor: "pointer" }}
            />
          ))}
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

      <OrderSearchDetailDrawer
        open={drawerOpen}
        onClose={closeDrawer}
        detail={detail}
        bagId={selectedBag}
        loading={detailLoading}
        detailError={detailError}
      />
    </Box>
  );
}
