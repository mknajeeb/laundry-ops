import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
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
import SaveIcon from "@mui/icons-material/Save";
import LockIcon from "@mui/icons-material/Lock";
import {
  finalizePayoutDetails,
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  putPayoutBatchDetails,
} from "../api";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEDUCTION_FIELDS = [
  { key: "fit", label: "FIT" },
  { key: "ss", label: "SS" },
  { key: "medicare", label: "Medicare" },
  { key: "state", label: "State" },
  { key: "local", label: "Local" },
  { key: "other1", label: "Other 1" },
  { key: "other2", label: "Other 2" },
];

const ER_TAX_FIELDS = [
  { key: "er_ss", label: "ER SS" },
  { key: "er_medicare", label: "ER Medicare" },
  { key: "futa", label: "FUTA" },
  { key: "suta", label: "SUTA" },
  { key: "other", label: "Other" },
];

const PAYMENT_METHODS = [
  { value: "direct_deposit", label: "Direct Deposit" },
  { value: "check", label: "Check" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function emptyLineState(line) {
  const pd = line?.payout_details || {};
  return {
    line_id: line.id,
    employee_deductions: { ...(pd.employee_deductions || {}) },
    employer_taxes: { ...(pd.employer_taxes || {}) },
    payment: { ...(pd.payment || {}) },
    settlement: { ...(pd.settlement || {}) },
  };
}

function computeLocalTotals(line, draft) {
  const gross = num(line.gross_amount || line.total_amount);
  const ded = DEDUCTION_FIELDS.reduce(
    (s, f) => s + num(draft.employee_deductions?.[f.key]),
    0,
  );
  const er = ER_TAX_FIELDS.reduce((s, f) => s + num(draft.employer_taxes?.[f.key]), 0);
  const net = gross - ded;
  return {
    gross,
    totalDed: ded,
    totalEr: er,
    employerCost: gross + er,
    net,
  };
}

export default function PayoutDetailsPanel() {
  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [lineDrafts, setLineDrafts] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [paystubLine, setPaystubLine] = useState(null);

  const loadBatches = useCallback(async () => {
    try {
      const res = await getPayoutBatches();
      const all = res.data?.items || [];
      setBatches(
        all.filter(
          (b) =>
            b.accountant_payment_confirmed_at ||
            b.status === "approved_for_payment" ||
            b.status === "paid",
        ),
      );
    } catch {
      setBatches([]);
    }
  }, []);

  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    setError("");
    try {
      const res = await getPayoutBatchDetails(id);
      const batch = res.data;
      setDetail(batch);
      setSelectedId(id);
      const drafts = {};
      (batch.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln);
      });
      setLineDrafts(drafts);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  const canEdit = detail?.payout_workflow?.can_edit_details;
  const finalized = detail?.payout_workflow?.payout_details_finalized;
  const awaitingConfirm = !detail?.payout_workflow?.accountant_payment_confirmed;

  const readyBatches = useMemo(
    () =>
      batches.filter((b) => {
        const wf = b.payout_workflow;
        if (wf) return wf.accountant_payment_confirmed || wf.can_edit_details;
        return b.accountant_payment_confirmed_at;
      }),
    [batches],
  );

  const updateDraft = (lineId, section, key, value) => {
    setLineDrafts((prev) => ({
      ...prev,
      [lineId]: {
        ...prev[lineId],
        [section]: { ...prev[lineId][section], [key]: value },
      },
    }));
  };

  const saveDetails = async () => {
    if (!selectedId || !canEdit) return;
    setError("");
    setInfo("");
    const lines = Object.values(lineDrafts).map((d) => ({
      line_id: d.line_id,
      payout_details: {
        employee_deductions: d.employee_deductions,
        employer_taxes: d.employer_taxes,
        payment: d.payment,
        settlement: d.settlement,
      },
    }));
    try {
      const res = await putPayoutBatchDetails(selectedId, { lines });
      setDetail(res.data);
      setInfo("Payout details saved.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    }
  };

  const doFinalize = async () => {
    if (!selectedId) return;
    try {
      const res = await finalizePayoutDetails(selectedId);
      setDetail(res.data);
      setFinalizeOpen(false);
      setInfo("Payout details finalized. Paystubs are now available.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Finalize failed");
    }
  };

  const printPaystub = async (lineId) => {
    if (!selectedId) return;
    try {
      const res = await getPaystubHtml(selectedId, lineId);
      const win = window.open("", "_blank");
      if (!win) return;
      win.document.open();
      win.document.write(res.data);
      win.document.close();
      win.onload = () => win.print();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub load failed");
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      <Paper sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}>
        <Typography variant="h6" sx={{ color: VEEWASH_BRAND.primaryDark }}>
          Payout details
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Enter taxes, deductions, payment info, and settlement after accountant confirms payment.
        </Typography>
      </Paper>

      <Paper sx={{ maxHeight: 220, overflow: "auto" }}>
        <List dense>
          {readyBatches.map((b) => (
            <ListItemButton
              key={b.id}
              selected={selectedId === b.id}
              onClick={() => loadDetail(b.id)}
            >
              <ListItemText
                primary={b.batch_name}
                secondary={`${b.pay_period_start} – ${b.pay_period_end} · ${b.worker_category}`}
              />
              {b.payout_details_finalized_at ? (
                <Chip size="small" label="Finalized" color="success" />
              ) : b.accountant_payment_confirmed_at ? (
                <Chip size="small" label="Ready" color="info" />
              ) : (
                <Chip size="small" label="Awaiting accountant" />
              )}
            </ListItemButton>
          ))}
          {!readyBatches.length ? (
            <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
              No batches ready for payout details yet.
            </Typography>
          ) : null}
        </List>
      </Paper>

      {detail ? (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
            <Typography variant="subtitle1" fontWeight={600}>
              {detail.batch_name}
            </Typography>
            <Stack direction="row" spacing={1}>
              {canEdit ? (
                <Button startIcon={<SaveIcon />} variant="outlined" onClick={saveDetails}>
                  Save details
                </Button>
              ) : null}
              {canEdit ? (
                <Button
                  startIcon={<LockIcon />}
                  variant="contained"
                  onClick={() => setFinalizeOpen(true)}
                  sx={{ bgcolor: VEEWASH_BRAND.primary }}
                >
                  Finalize
                </Button>
              ) : null}
            </Stack>
          </Stack>

          {awaitingConfirm ? (
            <Alert severity="warning" sx={{ mt: 2 }}>
              Accountant must confirm payment before you can enter payout details.
            </Alert>
          ) : null}
          {finalized ? (
            <Alert severity="success" sx={{ mt: 2 }}>
              Finalized — paystubs available for download/print.
            </Alert>
          ) : null}

          {(detail.lines || []).map((ln) => {
            const draft = lineDrafts[ln.id] || emptyLineState(ln);
            const totals = computeLocalTotals(ln, draft);
            return (
              <Paper key={ln.id} variant="outlined" sx={{ p: 2, mt: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography fontWeight={600}>{ln.worker_name_snapshot}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {num(ln.approved_hours).toFixed(2)} hrs · ${num(ln.rate).toFixed(2)}/hr · Gross $
                      {totals.gross.toFixed(2)}
                    </Typography>
                  </Box>
                  {finalized ? (
                    <Button
                      size="small"
                      startIcon={<PrintIcon />}
                      onClick={() => printPaystub(ln.id)}
                    >
                      Paystub
                    </Button>
                  ) : (
                    <Chip size="small" label="Paystub locked" />
                  )}
                </Stack>

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Employee deductions
                </Typography>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {DEDUCTION_FIELDS.map((f) => (
                        <TableCell key={f.key}>{f.label}</TableCell>
                      ))}
                      <TableCell>Total</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    <TableRow>
                      {DEDUCTION_FIELDS.map((f) => (
                        <TableCell key={f.key}>
                          <TextField
                            size="small"
                            type="number"
                            disabled={!canEdit}
                            value={draft.employee_deductions?.[f.key] ?? ""}
                            onChange={(e) =>
                              updateDraft(ln.id, "employee_deductions", f.key, e.target.value)
                            }
                            inputProps={{ style: { width: 72 } }}
                          />
                        </TableCell>
                      ))}
                      <TableCell>${totals.totalDed.toFixed(2)}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Employer taxes · Employer cost ${totals.employerCost.toFixed(2)}
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                  {ER_TAX_FIELDS.map((f) => (
                    <TextField
                      key={f.key}
                      size="small"
                      label={f.label}
                      type="number"
                      disabled={!canEdit}
                      value={draft.employer_taxes?.[f.key] ?? ""}
                      onChange={(e) =>
                        updateDraft(ln.id, "employer_taxes", f.key, e.target.value)
                      }
                    />
                  ))}
                </Stack>

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Payment · Net ${totals.net.toFixed(2)}
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                  <TextField
                    size="small"
                    type="date"
                    label="Date"
                    disabled={!canEdit}
                    InputLabelProps={{ shrink: true }}
                    value={draft.payment?.date || ""}
                    onChange={(e) => updateDraft(ln.id, "payment", "date", e.target.value)}
                  />
                  <FormControl size="small" disabled={!canEdit}>
                    <InputLabel>Method</InputLabel>
                    <Select
                      label="Method"
                      value={draft.payment?.method || "direct_deposit"}
                      onChange={(e) => updateDraft(ln.id, "payment", "method", e.target.value)}
                    >
                      {PAYMENT_METHODS.map((m) => (
                        <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    size="small"
                    label="Check #"
                    disabled={!canEdit}
                    value={draft.payment?.check_number || ""}
                    onChange={(e) => updateDraft(ln.id, "payment", "check_number", e.target.value)}
                  />
                  <TextField
                    size="small"
                    label="Reference"
                    disabled={!canEdit}
                    value={draft.payment?.reference || ""}
                    onChange={(e) => updateDraft(ln.id, "payment", "reference", e.target.value)}
                  />
                </Stack>

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Settlement
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                  {[
                    { key: "amount_paid", label: "Amount paid" },
                    { key: "amount_withheld", label: "Withheld" },
                    { key: "outstanding_balance", label: "Outstanding" },
                    { key: "prior_unpaid_taxes", label: "Prior unpaid taxes" },
                  ].map((f) => (
                    <TextField
                      key={f.key}
                      size="small"
                      label={f.label}
                      type="number"
                      disabled={!canEdit}
                      value={draft.settlement?.[f.key] ?? ""}
                      onChange={(e) => updateDraft(ln.id, "settlement", f.key, e.target.value)}
                    />
                  ))}
                </Stack>
              </Paper>
            );
          })}
        </Paper>
      ) : null}

      <Dialog open={finalizeOpen} onClose={() => setFinalizeOpen(false)}>
        <DialogTitle>Finalize payout details?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            This locks tax/deduction edits and enables paystub generation for all workers in this batch.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFinalizeOpen(false)}>Cancel</Button>
          <Button onClick={doFinalize} variant="contained">Finalize</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={paystubLine != null} onClose={() => setPaystubLine(null)} maxWidth="md" fullWidth>
        <DialogTitle>Paystub preview</DialogTitle>
        <DialogContent>
          <Typography variant="body2">Use Print to save as PDF.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPaystubLine(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
