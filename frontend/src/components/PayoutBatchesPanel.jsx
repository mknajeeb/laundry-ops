import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import {
  getContractors,
  getPayoutBatch,
  getPayoutBatches,
  patchPayoutBatch,
  postPayoutBatch,
} from "../api";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { ContractorPrintLetterhead } from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const BATCH_STATUSES = [
  "draft",
  "hours_reviewed",
  "sent_to_accountant",
  "accountant_reviewed",
  "approved_for_payment",
  "paid",
  "closed",
];

const CATEGORY_BATCH = WORKER_CATEGORY_OPTIONS.filter((o) => o.value !== "all");

function PayoutBatchSummaryPrint({ batch }) {
  const b = batch || {};
  const lines = b.lines || [];
  return (
    <div className="contractor-print-root">
      <ContractorPrintLetterhead
        prefill={{ company_name: "VeeWash / Washpro" }}
        documentTitle="Payroll / Contractor Payout Summary"
      />
      <p className="cform-p">
        <strong>Pay period:</strong> {b.pay_period_start} – {b.pay_period_end}
        <br />
        <strong>Category:</strong> {b.worker_category_label || b.worker_category}
        <br />
        <strong>Status:</strong> {b.status}
        <br />
        <strong>Frequency:</strong> {b.payout_frequency}
      </p>
      <table className="contractor-payment-table" style={{ marginBottom: "0.2in" }}>
        <tbody>
          {[
            ["Total people", b.worker_count],
            ["Total approved hours", Number(b.total_approved_hours || 0).toFixed(2)],
            ["Total gross/service", `$${Number(b.total_gross_amount || 0).toFixed(2)}`],
            ["Total adjustments", `$${Number(b.total_adjustments || 0).toFixed(2)}`],
            ["Total payout", `$${Number(b.total_payout_amount || 0).toFixed(2)}`],
            ["Missing documents", b.documents_missing_count ?? 0],
          ].map(([label, val]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="contractor-payment-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Worker</th>
            <th>Hours</th>
            <th>Rate</th>
            <th>Gross</th>
            <th>Adj.</th>
            <th>Payout</th>
            <th>Method</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((ln) => (
            <tr key={ln.id}>
              <td style={{ textAlign: "left" }}>{ln.worker_name_snapshot}</td>
              <td>{Number(ln.approved_hours || 0).toFixed(2)}</td>
              <td>${Number(ln.rate || 0).toFixed(2)}</td>
              <td>${Number(ln.gross_amount || 0).toFixed(2)}</td>
              <td>${Number(ln.adjustments || 0).toFixed(2)}</td>
              <td>
                <strong>${Number(ln.total_amount || 0).toFixed(2)}</strong>
              </td>
              <td style={{ textAlign: "left" }}>{ln.payment_method || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PayoutBatchesPanel() {
  const printRef = useRef(null);
  const [filterCat, setFilterCat] = useState("all");
  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState({
    batch_name: "",
    worker_category: "w2",
    pay_period_start: "",
    pay_period_end: "",
    payout_frequency: "biweekly",
    notes: "",
  });
  const [contractors, setContractors] = useState([]);
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);

  const loadList = useCallback(async () => {
    setError("");
    try {
      const params = filterCat !== "all" ? { worker_category: filterCat } : {};
      const res = await getPayoutBatches(params);
      setBatches(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [filterCat]);

  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const res = await getPayoutBatch(id);
      setDetail(res.data);
      setSelectedId(id);
    } catch (e) {
      setError(e.response?.data?.error || "Load batch failed");
    }
  }, []);

  useEffect(() => {
    loadList();
    getContractors()
      .then((r) => setContractors(r.data?.contractors || []))
      .catch(() => {});
  }, [loadList]);

  const createBatch = async () => {
    try {
      const res = await postPayoutBatch(draft);
      setCreateOpen(false);
      await loadList();
      await loadDetail(res.data.id);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Create failed");
    }
  };

  const runAction = async (action, extra = {}) => {
    if (!selectedId) return;
    try {
      const res = await patchPayoutBatch(selectedId, { action, ...extra });
      setDetail(res.data);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Action failed");
    }
  };

  const downloadCsv = () => {
    if (!detail?.lines?.length) return;
    const header = ["Worker", "Category", "Hours", "Rate", "Gross", "Adjustments", "Total", "Method"];
    const lines = detail.lines.map((ln) =>
      [
        ln.worker_name_snapshot,
        ln.worker_category,
        ln.approved_hours,
        ln.rate,
        ln.gross_amount,
        ln.adjustments,
        ln.total_amount,
        ln.payment_method,
      ].join(","),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `payout-batch-${detail.id}.csv`;
    a.click();
  };

  const filteredContractors = useMemo(() => {
    if (!detail?.worker_category) return contractors;
    return contractors.filter((c) => {
      if (detail.worker_category === "w2") return c.worker_kind !== "short_term" && c.worker_kind !== "1099";
      if (detail.worker_category === "contractor_1099") return c.worker_kind === "1099" || c.worker_kind === "1099_and_temp";
      return c.worker_kind === "short_term" || c.worker_kind === "1099_and_temp";
    });
  }, [contractors, detail?.worker_category]);

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }} className="no-print">
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
          <Typography variant="h6">Payout Batches</Typography>
          <Stack direction="row" spacing={1}>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Category</InputLabel>
              <Select label="Category" value={filterCat} onChange={(e) => setFilterCat(e.target.value)}>
                {WORKER_CATEGORY_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" onClick={() => setCreateOpen(true)}>
              New batch
            </Button>
          </Stack>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          One batch per worker category — never mix W-2, 1099, and temp in the same batch.
        </Typography>
      </Paper>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Paper sx={{ maxHeight: 420, overflow: "auto" }}>
            {batches.map((b) => (
              <Box
                key={b.id}
                sx={{
                  p: 1.5,
                  cursor: "pointer",
                  bgcolor: selectedId === b.id ? "action.selected" : undefined,
                  borderBottom: "1px solid",
                  borderColor: "divider",
                }}
                onClick={() => loadDetail(b.id)}
              >
                <Typography variant="subtitle2">{b.batch_name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {b.worker_category_label || b.worker_category} · {b.pay_period_start} – {b.pay_period_end}
                </Typography>
                <Chip size="small" label={b.status} sx={{ mt: 0.5 }} />
              </Box>
            ))}
            {!batches.length ? (
              <Typography sx={{ p: 2 }} color="text.secondary">
                No batches yet.
              </Typography>
            ) : null}
          </Paper>
        </Grid>
        <Grid item xs={12} md={8}>
          {detail ? (
            <Paper sx={{ p: 2 }} className="no-print">
              <Typography variant="h6">{detail.batch_name}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {detail.worker_category_label} · ${Number(detail.total_payout_amount || 0).toFixed(2)} ·{" "}
                {detail.worker_count} workers
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
                <Button size="small" variant="outlined" onClick={() => runAction("build_from_time_records", {
                  from_date: detail.pay_period_start,
                  to_date: detail.pay_period_end,
                })}>
                  Pull approved hours
                </Button>
                <Button size="small" variant="outlined" onClick={() => runAction("add_line", {
                  user_id: filteredContractors[0]?.user_id,
                  worker_name_snapshot: filteredContractors[0]?.full_name,
                  approved_hours: 0,
                  rate: filteredContractors[0]?.rate_per_hour || 0,
                })} disabled={!filteredContractors.length}>
                  Add worker line
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<PrintIcon />}
                  onClick={() => setPrintPreviewOpen(true)}
                >
                  Print preview
                </Button>
                <Button
                  size="small"
                  startIcon={<PrintIcon />}
                  onClick={() => openPrintWindow(printRef.current)}
                >
                  Print
                </Button>
                <Button size="small" onClick={downloadCsv}>
                  Download CSV
                </Button>
                {BATCH_STATUSES.map((st) => (
                  <Button key={st} size="small" onClick={() => patchPayoutBatch(selectedId, { status: st }).then((r) => { setDetail(r.data); loadList(); })}>
                    → {st.replace(/_/g, " ")}
                  </Button>
                ))}
              </Stack>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Worker</TableCell>
                    <TableCell>Hours</TableCell>
                    <TableCell>Rate</TableCell>
                    <TableCell>Total</TableCell>
                    <TableCell>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(detail.lines || []).map((ln) => (
                    <TableRow key={ln.id}>
                      <TableCell>{ln.worker_name_snapshot}</TableCell>
                      <TableCell>{Number(ln.approved_hours || 0).toFixed(2)}</TableCell>
                      <TableCell>${Number(ln.rate || 0).toFixed(2)}</TableCell>
                      <TableCell>${Number(ln.total_amount || 0).toFixed(2)}</TableCell>
                      <TableCell>{ln.line_status}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Paper>
          ) : (
            <Alert severity="info">Select or create a payout batch.</Alert>
          )}
        </Grid>
      </Grid>

      <ContractorPrintPreviewDialog
        open={printPreviewOpen}
        onClose={() => setPrintPreviewOpen(false)}
        title="Payroll / Contractor Payout Summary"
        printRef={printRef}
      />
      <Box
        ref={printRef}
        className="contractor-print-area"
        sx={{
          position: "absolute",
          left: -9999,
          visibility: detail ? "hidden" : "hidden",
          width: "7.5in",
        }}
      >
        {detail ? <PayoutBatchSummaryPrint batch={detail} /> : null}
      </Box>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New payout batch</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Batch name" value={draft.batch_name} onChange={(e) => setDraft({ ...draft, batch_name: e.target.value })} />
            <FormControl fullWidth>
              <InputLabel>Worker category</InputLabel>
              <Select label="Worker category" value={draft.worker_category} onChange={(e) => setDraft({ ...draft, worker_category: e.target.value })}>
                {CATEGORY_BATCH.map((o) => (
                  <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField type="date" label="Period start" InputLabelProps={{ shrink: true }} value={draft.pay_period_start} onChange={(e) => setDraft({ ...draft, pay_period_start: e.target.value })} />
            <TextField type="date" label="Period end" InputLabelProps={{ shrink: true }} value={draft.pay_period_end} onChange={(e) => setDraft({ ...draft, pay_period_end: e.target.value })} />
            <FormControl fullWidth>
              <InputLabel>Frequency</InputLabel>
              <Select label="Frequency" value={draft.payout_frequency} onChange={(e) => setDraft({ ...draft, payout_frequency: e.target.value })}>
                <MenuItem value="weekly">Weekly</MenuItem>
                <MenuItem value="biweekly">Biweekly</MenuItem>
              </Select>
            </FormControl>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={createBatch}>Create</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
