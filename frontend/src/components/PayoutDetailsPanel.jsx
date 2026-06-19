import { useCallback, useEffect, useMemo, useState } from "react";
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
  FormControlLabel,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
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
import { useAuth } from "../context/AuthContext";
import {
  confirmPayoutPayment,
  finalizePayoutDetails,
  getPaymentReceiptHtml,
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  putPayoutBatchDetails,
  setPayoutDocumentMode,
} from "../api";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";

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
  { value: "zelle", label: "Zelle" },
  { value: "other", label: "Other" },
];

const DOCUMENT_MODES = [
  { value: "payment_receipt", label: "Payment Receipts" },
  { value: "official_paystub", label: "Official Paystubs" },
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
    use_payment_receipt: Boolean(pd.use_payment_receipt),
    employee_note: pd.employee_note || "",
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

async function printHtmlDocument(fetchFn) {
  const res = await fetchFn();
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.open();
  win.document.write(res.data);
  win.document.close();
  win.onload = () => win.print();
}

export default function PayoutDetailsPanel() {
  const { hasPerm, user } = useAuth();
  const rolesUpper = useMemo(() => {
    const roles = user?.roles;
    if (Array.isArray(roles) && roles.length) {
      return roles.map((r) => String(r).toUpperCase());
    }
    if (user?.role_code) return [String(user.role_code).toUpperCase()];
    return [];
  }, [user?.roles, user?.role_code]);
  const isAccountantRole = rolesUpper.includes("ACCOUNTANT");
  const canConfirmPayment =
    isAccountantRole &&
    (hasPerm("users.view") || hasPerm("ta.settings") || hasPerm("users.edit"));

  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [lineDrafts, setLineDrafts] = useState({});
  const [batchNote, setBatchNote] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });

  const loadBatches = useCallback(async () => {
    try {
      const res = await getPayoutBatches();
      const all = res.data?.items || [];
      setBatches(
        all.filter((b) =>
          ["approved_for_payment", "paid", "closed"].includes(b.status),
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
      setBatchNote(batch.batch_note || "");
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
  const readOnlyAccountant = isAccountantRole && !canEdit;
  const awaitingConfirm = detail?.payout_workflow?.awaiting_accountant_confirmation;
  const documentMode =
    detail?.payout_workflow?.document_mode ||
    detail?.document_mode ||
    "official_paystub";
  const isReceiptMode = documentMode === "payment_receipt";
  const canSetDocumentMode = detail?.payout_workflow?.can_set_document_mode;

  const readyBatches = useMemo(() => batches, [batches]);

  const confirmPayment = async () => {
    if (!selectedId || !canConfirmPayment) return;
    setError("");
    setInfo("");
    try {
      const res = await confirmPayoutPayment(selectedId);
      setDetail(res.data);
      setInfo("Payment confirmed.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Confirm failed");
    }
  };

  const updateDraft = (lineId, section, key, value) => {
    setLineDrafts((prev) => ({
      ...prev,
      [lineId]: {
        ...prev[lineId],
        [section]: { ...prev[lineId][section], [key]: value },
      },
    }));
  };

  const updateLineFlag = (lineId, key, value) => {
    setLineDrafts((prev) => ({
      ...prev,
      [lineId]: { ...prev[lineId], [key]: value },
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
        use_payment_receipt: d.use_payment_receipt,
        employee_note: d.employee_note || "",
      },
    }));
    try {
      const res = await putPayoutBatchDetails(selectedId, { lines, batch_note: batchNote });
      setDetail(res.data);
      setBatchNote(res.data.batch_note || "");
      setInfo("Payout details saved.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    }
  };

  const changeDocumentMode = async (mode) => {
    if (!selectedId || !canSetDocumentMode) return;
    setError("");
    try {
      const res = await setPayoutDocumentMode(selectedId, mode);
      setDetail(res.data);
      setInfo(
        mode === "payment_receipt"
          ? "Batch set to Payment Receipt mode."
          : "Batch set to Official Paystub mode.",
      );
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Mode change failed");
    }
  };

  const doFinalize = async () => {
    if (!selectedId) return;
    try {
      const res = await finalizePayoutDetails(selectedId);
      setDetail(res.data);
      setFinalizeOpen(false);
      setInfo(
        isReceiptMode
          ? "Payout details finalized. Payment receipts are now available."
          : "Payout details finalized. Paystubs are now available.",
      );
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Finalize failed");
    }
  };

  const printPaystub = async (lineId) => {
    if (!selectedId) return;
    try {
      await printHtmlDocument(() => getPaystubHtml(selectedId, lineId));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub load failed");
    }
  };

  const printReceipt = async (lineId) => {
    if (!selectedId) return;
    try {
      await printHtmlDocument(() => getPaymentReceiptHtml(selectedId, lineId));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Receipt load failed");
    }
  };

  const finalizeMessage = isReceiptMode
    ? "This locks payment edits and enables payment receipt generation for all workers in this batch."
    : "This locks tax/deduction edits and enables official paystub generation. Cash payments still require a payment receipt.";

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
          Payment &amp; payout details
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Enter deductions, payment method, and settlement for approved batches. Accountants
          may optionally confirm payment after processing on W-2 Payroll.
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
              ) : b.payout_workflow?.can_edit_details || b.status === "approved_for_payment" ? (
                <Chip size="small" label="Ready" color="info" />
              ) : (
                <Chip size="small" label="Pending approval" />
              )}
            </ListItemButton>
          ))}
          {!readyBatches.length ? (
            <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
              No approved batches ready for payout details yet.
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
              {awaitingConfirm && canConfirmPayment ? (
                <Button
                  variant="contained"
                  onClick={confirmPayment}
                  sx={{ bgcolor: VEEWASH_BRAND.primary }}
                >
                  Confirm payment
                </Button>
              ) : null}
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

          {awaitingConfirm && !canConfirmPayment ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              Accountant payment confirmation is optional — you can enter payout details now.
            </Alert>
          ) : null}
          {awaitingConfirm && canConfirmPayment ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              Confirm payment after processing this batch on W-2 Payroll, or proceed directly to
              payout details below.
            </Alert>
          ) : null}

          {canSetDocumentMode ? (
            <Stack direction="row" alignItems="center" gap={2} sx={{ mt: 2 }}>
              <FormControl size="small" sx={{ minWidth: 220 }}>
                <InputLabel>Batch document mode</InputLabel>
                <Select
                  label="Batch document mode"
                  value={documentMode}
                  onChange={(e) => changeDocumentMode(e.target.value)}
                >
                  {DOCUMENT_MODES.map((m) => (
                    <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary">
                {isReceiptMode
                  ? "Payment receipts — no tax section. For manual/cash or non-withholding periods."
                  : "Official paystubs — enter tax deductions. Cash payments still need a receipt."}
              </Typography>
            </Stack>
          ) : finalized ? (
            <Chip
              size="small"
              sx={{ mt: 2 }}
              label={
                isReceiptMode ? "Document mode: Payment Receipts" : "Document mode: Official Paystubs"
              }
            />
          ) : null}

          {finalized ? (
            <Alert severity="success" sx={{ mt: 2 }}>
              {isReceiptMode
                ? "Finalized — payment receipts available for download/print."
                : "Finalized — paystubs and receipts (cash/check) available for download/print."}
            </Alert>
          ) : null}

          <TextField
            fullWidth
            multiline
            minRows={2}
            label="Batch note (shown on all paystubs)"
            disabled={!canEdit}
            value={batchNote}
            onChange={(e) => setBatchNote(e.target.value)}
            sx={{ mt: 2 }}
            placeholder="e.g. Payroll taxes were not withheld for this pay period..."
          />

          {(detail.lines || []).map((ln) => {
            const draft = lineDrafts[ln.id] || emptyLineState(ln);
            const totals = computeLocalTotals(ln, draft);
            const doc = ln.document || {};
            const method = draft.payment?.method || "direct_deposit";
            const cashSelected = method === "cash";
            const receiptRequired = cashSelected || doc.receipt_required;
            const showPaystubBtn = finalized && doc.paystub_available;
            const showReceiptBtn = finalized && doc.receipt_available;

            return (
              <Paper key={ln.id} variant="outlined" sx={{ p: 2, mt: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
                  <Box>
                    <Typography fontWeight={600}>{ln.worker_name_snapshot}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {num(ln.approved_hours).toFixed(2)} hrs · ${num(ln.rate).toFixed(2)}/hr · Gross $
                      {totals.gross.toFixed(2)}
                      {finalized || readOnlyAccountant ? (
                        <>
                          {" · Net paid "}
                          {formatNetPaidDisplay(ln)}
                          {" · Tax withheld "}
                          {(() => {
                            const label = formatTaxWithheldDisplay(ln);
                            const clickable =
                              isPayoutDetailsFinalized(ln) &&
                              (hasTaxWithheldBreakdown(ln) || label !== "Pending");
                            if (!clickable) return label;
                            return (
                              <Button
                                size="small"
                                variant="text"
                                sx={{ minWidth: 0, p: 0, verticalAlign: "baseline", fontSize: "inherit" }}
                                onClick={() =>
                                  setTaxDialog({
                                    open: true,
                                    line: ln,
                                    workerName: ln.worker_name_snapshot || "",
                                  })
                                }
                              >
                                {label}
                              </Button>
                            );
                          })()}
                        </>
                      ) : null}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={1} alignItems="center">
                    {showPaystubBtn && !readOnlyAccountant ? (
                      <Button size="small" startIcon={<PrintIcon />} onClick={() => printPaystub(ln.id)}>
                        Paystub
                      </Button>
                    ) : null}
                    {showReceiptBtn && !readOnlyAccountant ? (
                      <Button size="small" startIcon={<PrintIcon />} onClick={() => printReceipt(ln.id)}>
                        Receipt
                      </Button>
                    ) : null}
                    {!finalized ? (
                      <Chip size="small" label="Documents locked" />
                    ) : null}
                  </Stack>
                </Stack>

                {cashSelected && !finalized ? (
                  <Alert severity="info" sx={{ mt: 1 }}>
                    Cash payment — a payment receipt is required when finalized.
                  </Alert>
                ) : null}

                {!readOnlyAccountant ? (
                  <>
                {!isReceiptMode && canEdit ? (
                  <FormControlLabel
                    sx={{ mt: 1 }}
                    control={
                      <Switch
                        size="small"
                        checked={Boolean(draft.use_payment_receipt)}
                        onChange={(e) =>
                          updateLineFlag(ln.id, "use_payment_receipt", e.target.checked)
                        }
                      />
                    }
                    label="Use payment receipt for this employee (override)"
                  />
                ) : null}

                {!isReceiptMode ? (
                  <>
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
                  </>
                ) : null}

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Payment{!isReceiptMode ? ` · Net $${totals.net.toFixed(2)}` : ""}
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                  <TextField
                    size="small"
                    type="date"
                    label="Date"
                    disabled={!canEdit}
                    required={receiptRequired}
                    InputLabelProps={{ shrink: true }}
                    value={draft.payment?.date || ""}
                    onChange={(e) => updateDraft(ln.id, "payment", "date", e.target.value)}
                  />
                  <FormControl size="small" disabled={!canEdit} required={receiptRequired}>
                    <InputLabel>Method</InputLabel>
                    <Select
                      label="Method"
                      value={method}
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
                  <TextField
                    size="small"
                    label="Notes"
                    disabled={!canEdit}
                    value={draft.payment?.notes || ""}
                    onChange={(e) => updateDraft(ln.id, "payment", "notes", e.target.value)}
                  />
                </Stack>

                <Typography variant="subtitle2" sx={{ mt: 2, color: VEEWASH_BRAND.primaryDark }}>
                  Settlement
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                  {[
                    { key: "amount_paid", label: "Amount paid", required: isReceiptMode || receiptRequired },
                    { key: "amount_withheld", label: "Withheld" },
                    { key: "outstanding_balance", label: "Outstanding" },
                    { key: "prior_unpaid_taxes", label: "Prior unpaid taxes" },
                    { key: "prior_period_adjustment", label: "Prior-period adjustment" },
                  ].map((f) => (
                    <TextField
                      key={f.key}
                      size="small"
                      label={f.label}
                      type="number"
                      required={f.required}
                      disabled={!canEdit}
                      value={draft.settlement?.[f.key] ?? ""}
                      onChange={(e) => updateDraft(ln.id, "settlement", f.key, e.target.value)}
                    />
                  ))}
                </Stack>

                <TextField
                  fullWidth
                  multiline
                  minRows={2}
                  label="Employee note (optional, shown on this paystub)"
                  disabled={!canEdit}
                  value={draft.employee_note || ""}
                  onChange={(e) => updateLineFlag(ln.id, "employee_note", e.target.value)}
                  sx={{ mt: 2 }}
                  placeholder="e.g. Employee requested payment in cash..."
                />
                  </>
                ) : null}
              </Paper>
            );
          })}
        </Paper>
      ) : null}

      <TaxWithheldBreakdownDialog
        open={taxDialog.open}
        onClose={() => setTaxDialog({ open: false, line: null, workerName: "" })}
        line={taxDialog.line}
        workerName={taxDialog.workerName}
      />

      <Dialog open={finalizeOpen} onClose={() => setFinalizeOpen(false)}>
        <DialogTitle>Finalize payout details?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">{finalizeMessage}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFinalizeOpen(false)}>Cancel</Button>
          <Button onClick={doFinalize} variant="contained">Finalize</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
