import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
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
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HighlightOffIcon from "@mui/icons-material/HighlightOff";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import PrintIcon from "@mui/icons-material/Print";
import {
  deletePayoutBatch,
  getContractors,
  getPayoutBatch,
  getPayoutBatches,
  patchPayoutBatch,
  postPayoutBatch,
} from "../api";
import PayrollDueSummary from "./PayrollDueSummary";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { ContractorPrintLetterhead } from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import {
  ACCOUNTANT_BATCH_READY_MESSAGE,
  ESTIMATE_DISCLAIMER,
  PAYROLL_ESTIMATE_PURPOSE,
  SEND_TO_ACCOUNTANT_W2_CONFIRM,
  formatTaxAmount,
  isLineTaxIncomplete,
} from "../payroll/payrollTaxMessages";

const BATCH_STATUS_FLOW = [
  { value: "draft", label: "Draft" },
  { value: "hours_reviewed", label: "Hours reviewed" },
  { value: "sent_to_accountant", label: "Sent to accountant" },
  { value: "accountant_reviewed", label: "Accountant reviewed" },
  { value: "approved_for_payment", label: "Approved for payment" },
  { value: "paid", label: "Paid" },
  { value: "closed", label: "Closed" },
];

const CATEGORY_BATCH = WORKER_CATEGORY_OPTIONS.filter((o) => o.value !== "all");

function batchPaymentLabel(st) {
  if (st === "paid") return "Paid";
  if (st === "partially_paid") return "Partially paid";
  if (st === "approved_unpaid") return "Approved — unpaid";
  return "Pending";
}

function batchPaymentColor(st) {
  if (st === "paid") return "success";
  if (st === "partially_paid") return "warning";
  if (st === "approved_unpaid") return "info";
  return "default";
}
function lineStatusLabel(st) {
  if (st === "pending" || st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  return st || "—";
}

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
      </p>
      <table className="contractor-payment-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Worker</th>
            <th>Hours</th>
            <th>Rate</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((ln) => (
            <tr key={ln.id}>
              <td style={{ textAlign: "left" }}>{ln.worker_name_snapshot}</td>
              <td>{Number(ln.approved_hours || 0).toFixed(2)}</td>
              <td>${Number(ln.rate || 0).toFixed(2)}</td>
              <td>
                <strong>${Number(ln.total_amount || 0).toFixed(2)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PayrollReadinessChecklist({ items }) {
  if (!items?.length) return null;
  return (
    <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Payroll readiness
      </Typography>
      <Stack spacing={1}>
        {items.map((item) => (
          <Stack key={item.key} direction="row" spacing={1} alignItems="flex-start">
            {item.ok ? (
              <CheckCircleOutlineIcon fontSize="small" color="success" sx={{ mt: 0.25 }} />
            ) : (
              <HighlightOffIcon fontSize="small" color="warning" sx={{ mt: 0.25 }} />
            )}
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2">{item.label}</Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {item.detail}
              </Typography>
            </Box>
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}

export default function PayoutBatchesPanel({
  payPeriodStart = "",
  payPeriodEnd = "",
  onPayPeriodChange,
}) {
  const printRef = useRef(null);
  const [filterCat, setFilterCat] = useState("all");
  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [lineEdit, setLineEdit] = useState(null);
  const [draft, setDraft] = useState({
    batch_name: "",
    worker_category: "temp",
    pay_period_start: payPeriodStart || "",
    pay_period_end: payPeriodEnd || "",
    payout_frequency: "biweekly",
    notes: "",
  });
  const [printPreviewOpen, setPrintPreviewOpen] = useState(false);
  const [sendConfirmOpen, setSendConfirmOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

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

  const loadDetail = useCallback(
    async (id, { quiet = false, sync = false } = {}) => {
      if (!id) return;
      setDetailLoading(true);
      try {
        const res = await getPayoutBatch(id, sync ? { sync: 1 } : {});
        const batch = res.data;
        setDetail(batch);
        setSelectedId(id);
        if (batch?.pay_period_start && batch?.pay_period_end) {
          onPayPeriodChange?.({
            start: batch.pay_period_start,
            end: batch.pay_period_end,
            category: batch.worker_category,
          });
        }
        if (!quiet && sync && batch?.status === "draft") {
          const n = batch?.lines?.length || 0;
          if (n) {
            setInfo(`Synced ${n} worker line(s) from approved time records for this pay period.`);
          } else {
            setInfo(
              "No approved time in this period yet. Approve rows on Time Records — they will appear here on refresh.",
            );
          }
        }
      } catch (e) {
        setError(e.response?.data?.error || "Load batch failed");
      } finally {
        setDetailLoading(false);
      }
    },
    [onPayPeriodChange],
  );

  useEffect(() => {
    loadList();
    getContractors().catch(() => {});
  }, [loadList]);

  /** Open batch matching the pay-period search bar when dates align. */
  useEffect(() => {
    if (!payPeriodStart || !payPeriodEnd || !batches.length) return;
    const ps = normPayPeriodYmd(payPeriodStart);
    const pe = normPayPeriodYmd(payPeriodEnd);
    const match = batches.find(
      (b) =>
        normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
    );
    if (match && selectedId !== match.id) {
      loadDetail(match.id, { quiet: true });
    }
  }, [payPeriodStart, payPeriodEnd, batches, selectedId, loadDetail]);

  const openCreateBatch = () => {
    setDraft((d) => ({
      ...d,
      pay_period_start: payPeriodStart || d.pay_period_start,
      pay_period_end: payPeriodEnd || d.pay_period_end,
    }));
    setCreateOpen(true);
  };

  const createBatch = async () => {
    try {
      const res = await postPayoutBatch(draft);
      setCreateOpen(false);
      onPayPeriodChange?.({
        start: draft.pay_period_start,
        end: draft.pay_period_end,
        category: draft.worker_category,
      });
      const n = res.data?.lines?.length || 0;
      setInfo(
        n
          ? `Batch created with ${n} worker line(s) from approved time records.`
          : "Batch created. Approve time on Time Records for this period — lines update when you open the batch.",
      );
      await loadList();
      await loadDetail(res.data.id, { quiet: true });
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Create failed");
    }
  };

  const saveBatchEdit = async () => {
    try {
      const res = await patchPayoutBatch(selectedId, {
        action: "update_batch",
        batch_name: draft.batch_name,
        pay_period_start: draft.pay_period_start,
        pay_period_end: draft.pay_period_end,
        payout_frequency: draft.payout_frequency,
        notes: draft.notes,
      });
      setDetail(res.data);
      setEditOpen(false);
      onPayPeriodChange?.({
        start: draft.pay_period_start,
        end: draft.pay_period_end,
        category: detail?.worker_category || draft.worker_category,
      });
      await loadList();
      await loadDetail(selectedId, { quiet: true });
      const n = res.data?.lines?.length || 0;
      setInfo(
        n
          ? `Pay period updated — synced ${n} worker line(s) from approved time records.`
          : "Pay period updated. No approved time in range yet.",
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    }
  };

  const confirmDeleteBatch = async (batchId = selectedId) => {
    if (!batchId) return;
    try {
      await deletePayoutBatch(batchId);
      setDeleteOpen(false);
      if (selectedId === batchId) {
        setDetail(null);
        setSelectedId(null);
      }
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    }
  };

  const promptDeleteBatch = (batch) => {
    setSelectedId(batch.id);
    if (detail?.id !== batch.id) {
      setDetail({ batch_name: batch.batch_name, status: batch.status });
    }
    setDeleteOpen(true);
  };

  const refreshHours = async () => {
    if (!selectedId) return;
    setInfo("");
    setError("");
    await loadDetail(selectedId, { sync: true });
    await loadList();
  };

  const runWorkflowAction = async (action, extra = {}) => {
    if (!selectedId) return;
    setError("");
    setInfo("");
    try {
      const res = await patchPayoutBatch(selectedId, { action, ...extra });
      setDetail(res.data);
      await loadList();
      const labels = {
        hours_reviewed: "Hours marked reviewed.",
        send_to_accountant: "Batch confirmed ready for accountant.",
        mark_paid: "Batch marked paid.",
        mark_line_paid: "Worker marked paid.",
        mark_line_unpaid: "Worker marked unpaid.",
        refresh_rates: "Scheduling/profile rates applied.",
        recalculate_taxes: "W-2 tax estimates recalculated.",
      };
      setInfo(labels[action] || "Updated.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Action failed");
    }
  };

  const markLinePaid = (lineId) => runWorkflowAction("mark_line_paid", { line_id: lineId });
  const markLineUnpaid = (lineId) => runWorkflowAction("mark_line_unpaid", { line_id: lineId });

  const setBatchStatus = async (status) => {
    try {
      const res = await patchPayoutBatch(selectedId, { status });
      setDetail(res.data);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Status update failed");
    }
  };

  const saveLineEdit = async () => {
    if (!lineEdit?.id) return;
    try {
      await patchPayoutBatch(selectedId, {
        action: "update_line",
        line_id: lineEdit.id,
        approved_hours: lineEdit.approved_hours,
        ot_hours: lineEdit.ot_hours,
        rate: lineEdit.rate,
        adjustments: lineEdit.adjustments,
        sick_hours_used: lineEdit.sick_hours_used,
        allow_sick_over_balance: lineEdit.allow_sick_over_balance,
        sick_override_note: lineEdit.sick_override_note,
        health_credit_amount: lineEdit.health_credit_amount,
        health_credit_note: lineEdit.health_credit_note,
      });
      setLineEdit(null);
      await loadDetail(selectedId);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Line save failed");
    }
  };

  const removeLine = async (lineId) => {
    if (!window.confirm("Remove this worker from the batch?")) return;
    try {
      const res = await patchPayoutBatch(selectedId, { action: "delete_line", line_id: lineId });
      setDetail(res.data);
      await loadList();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete line failed");
    }
  };

  const downloadCsv = () => {
    if (!detail?.lines?.length) return;
    const header = ["Worker", "Hours", "Rate", "Gross", "Adjustments", "Total"];
    const lines = detail.lines.map((ln) =>
      [ln.worker_name_snapshot, ln.approved_hours, ln.rate, ln.gross_amount, ln.adjustments, ln.total_amount].join(
        ",",
      ),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `payout-batch-${detail.id}.csv`;
    a.click();
  };

  const isDraft = detail?.status === "draft";
  const isEditable = detail?.status === "draft" || detail?.status === "hours_reviewed";
  const isW2 = detail?.worker_category === "w2";
  const isGrossOnly = detail?.worker_category === "temp" || detail?.worker_category === "contractor_1099";
  const summary = detail?.summary || {};
  const batchWarnings = detail?.warnings || [];
  const readiness = detail?.readiness || [];

  const openEditBatch = () => {
    setDraft({
      batch_name: detail.batch_name || "",
      worker_category: detail.worker_category || "temp",
      pay_period_start: detail.pay_period_start || "",
      pay_period_end: detail.pay_period_end || "",
      payout_frequency: detail.payout_frequency || "biweekly",
      notes: detail.notes || "",
    });
    setEditOpen(true);
  };

  const batchFormFields = (
    <Stack spacing={2}>
      <TextField
        label="Batch name"
        size="small"
        value={draft.batch_name}
        onChange={(e) => setDraft({ ...draft, batch_name: e.target.value })}
      />
      <FormControl fullWidth size="small" disabled={!!detail}>
        <InputLabel>Worker category</InputLabel>
        <Select
          label="Worker category"
          value={draft.worker_category}
          onChange={(e) => setDraft({ ...draft, worker_category: e.target.value })}
        >
          {CATEGORY_BATCH.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          fullWidth
          size="small"
          type="date"
          label="Period start"
          InputLabelProps={{ shrink: true }}
          value={draft.pay_period_start}
          onChange={(e) => setDraft({ ...draft, pay_period_start: e.target.value })}
        />
        <TextField
          fullWidth
          size="small"
          type="date"
          label="Period end"
          InputLabelProps={{ shrink: true }}
          value={draft.pay_period_end}
          onChange={(e) => setDraft({ ...draft, pay_period_end: e.target.value })}
        />
      </Stack>
      <FormControl fullWidth size="small">
        <InputLabel>Frequency</InputLabel>
        <Select
          label="Frequency"
          value={draft.payout_frequency}
          onChange={(e) => setDraft({ ...draft, payout_frequency: e.target.value })}
        >
          <MenuItem value="weekly">Weekly</MenuItem>
          <MenuItem value="biweekly">Biweekly</MenuItem>
        </Select>
      </FormControl>
      <TextField
        label="Notes"
        size="small"
        multiline
        minRows={2}
        value={draft.notes}
        onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
      />
    </Stack>
  );

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {info ? (
        <Alert severity="info" onClose={() => setInfo("")}>
          {info}
        </Alert>
      ) : null}

      <PayrollDueSummary fromDate={payPeriodStart} toDate={payPeriodEnd} />

      <Paper sx={{ p: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Box>
            <Typography variant="h6">Payout batches</Typography>
            <Typography variant="body2" color="text.secondary">
              1) Approve time on Time Records · 2) Create/open W-2 batch for that week · 3) Mark hours
              reviewed · 4) Confirm batch ready for accountant.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Filter</InputLabel>
              <Select label="Filter" value={filterCat} onChange={(e) => setFilterCat(e.target.value)}>
                {WORKER_CATEGORY_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateBatch}>
              New batch
            </Button>
          </Stack>
        </Stack>
      </Paper>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch">
        <Paper sx={{ width: { xs: "100%", lg: 280 }, flexShrink: 0 }}>
          <Typography variant="subtitle2" sx={{ px: 2, pt: 1.5 }}>
            Batches
          </Typography>
          <List dense sx={{ maxHeight: 480, overflow: "auto" }}>
            {batches.map((b) => (
              <ListItemButton
                key={b.id}
                selected={selectedId === b.id}
                onClick={() => loadDetail(b.id)}
                sx={{ pr: 0.5 }}
              >
                <ListItemText
                  primary={b.batch_name}
                  secondary={`${b.pay_period_start} – ${b.pay_period_end}`}
                  primaryTypographyProps={{ noWrap: true }}
                />
                <Chip size="small" label={b.status} sx={{ ml: 0.5, flexShrink: 0 }} />
                {b.status === "draft" || b.status === "hours_reviewed" ? (
                  <Tooltip title="Delete batch">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={(e) => {
                        e.stopPropagation();
                        promptDeleteBatch(b);
                      }}
                      sx={{ ml: 0.5, flexShrink: 0 }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                ) : null}
              </ListItemButton>
            ))}
            {!batches.length ? (
              <Typography sx={{ p: 2 }} variant="body2" color="text.secondary">
                No batches yet.
              </Typography>
            ) : null}
          </List>
        </Paper>

        <Paper sx={{ flex: 1, p: 2, minWidth: 0 }}>
          {detailLoading ? (
            <Typography color="text.secondary">Loading batch…</Typography>
          ) : !detail ? (
            <Typography color="text.secondary">Select a batch to view or edit.</Typography>
          ) : (
            <>
              <Stack
                direction={{ xs: "column", md: "row" }}
                justifyContent="space-between"
                spacing={1}
                sx={{ mb: 2 }}
              >
                <Box>
                  <Typography variant="h6">{detail.batch_name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {detail.worker_category_label} · {detail.pay_period_start} –{" "}
                    {detail.pay_period_end}
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 0.5 }}>
                    <strong>${Number(detail.total_payout_amount || 0).toFixed(2)}</strong> ·{" "}
                    {detail.worker_count} worker(s) · {Number(detail.total_approved_hours || 0).toFixed(2)}{" "}
                    hrs
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                    <Chip
                      size="small"
                      label={`Batch: ${detail.status}`}
                      color={detail.status === "paid" ? "success" : "default"}
                    />
                    <Chip
                      size="small"
                      label={`Payment: ${batchPaymentLabel(detail.payment_status)}`}
                      color={batchPaymentColor(detail.payment_status)}
                    />
                  </Stack>
                </Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                  <Button
                    size="small"
                    variant="contained"
                    startIcon={<EditIcon />}
                    onClick={openEditBatch}
                    disabled={!isEditable}
                  >
                    Edit batch
                  </Button>
                  <Button
                    size="small"
                    variant="contained"
                    color="error"
                    startIcon={<DeleteIcon />}
                    onClick={() => setDeleteOpen(true)}
                    disabled={!isEditable}
                  >
                    Delete batch
                  </Button>
                </Stack>
              </Stack>

              {!isEditable ? (
                <Alert severity="info" sx={{ mb: 2 }}>
                  This batch is past review. Set <strong>Batch status</strong> back to Draft below to
                  edit, delete, or refresh lines.
                </Alert>
              ) : null}

              {batchWarnings.length ? (
                <Stack spacing={1} sx={{ mb: 2 }}>
                  {batchWarnings.map((w) => (
                    <Alert key={w} severity="warning">
                      {w}
                    </Alert>
                  ))}
                </Stack>
              ) : null}

              {isW2 ? (
                <Alert severity="info" sx={{ mb: 2 }}>
                  {detail.payroll_estimate_purpose_notice || PAYROLL_ESTIMATE_PURPOSE}
                  <Typography variant="body2" sx={{ mt: 1, fontWeight: 600 }}>
                    {detail.estimated_withholding_notice || ESTIMATE_DISCLAIMER}
                  </Typography>
                </Alert>
              ) : null}

              {detail.accountant_ready_message ? (
                <Alert severity="success" sx={{ mb: 2 }}>
                  {detail.accountant_ready_message}
                </Alert>
              ) : null}

              {isGrossOnly ? (
                <Alert severity="info" sx={{ mb: 2 }}>
                  {detail.payroll_estimate_purpose_notice ||
                    "Gross payout tracking only — tax engine does not run for Temp/1099 batches."}
                </Alert>
              ) : null}

              <PayrollReadinessChecklist items={readiness} />

              {isGrossOnly ? (
                <Alert severity="info" variant="outlined" sx={{ mb: 2 }}>
                  Health / attendance credit is an internal discretionary payment tracking field.
                  It does not classify the worker as a W-2 employee and should be verified with
                  accountant/legal advisor.
                </Alert>
              ) : null}
              <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Batch summary — {detail.worker_category_label}
                </Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2} flexWrap="wrap" useFlexGap>
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Gross
                    </Typography>
                    <Typography>${Number(summary.gross_total || 0).toFixed(2)}</Typography>
                  </Box>
                  {isW2 ? (
                    <>
                      <Box>
                        <Typography variant="caption" color="text.secondary">
                          Employee taxes (est.)
                        </Typography>
                        <Typography>
                          {summary.taxes_withheld_total != null
                            ? `$${Number(summary.taxes_withheld_total).toFixed(2)}`
                            : "—"}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          {ESTIMATE_DISCLAIMER}
                        </Typography>
                      </Box>
                      <Box>
                        <Typography variant="caption" color="text.secondary">
                          Net pay (est.)
                        </Typography>
                        <Typography>
                          {summary.net_pay_total != null
                            ? `$${Number(summary.net_pay_total).toFixed(2)}`
                            : summary.net_pay_note || "—"}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          {ESTIMATE_DISCLAIMER}
                        </Typography>
                      </Box>
                      <Box>
                        <Typography variant="caption" color="text.secondary">
                          Employer taxes (est.)
                        </Typography>
                        <Typography>
                          {summary.employer_taxes_total != null
                            ? `$${Number(summary.employer_taxes_total).toFixed(2)}`
                            : "—"}
                        </Typography>
                      </Box>
                      <Box>
                        <Typography variant="caption" color="text.secondary">
                          Total payroll cost
                        </Typography>
                        <Typography>
                          {summary.employer_cost_total != null
                            ? `$${Number(summary.employer_cost_total).toFixed(2)}`
                            : "—"}
                        </Typography>
                      </Box>
                    </>
                  ) : null}
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Paid
                    </Typography>
                    <Typography>${Number(summary.paid_amount || 0).toFixed(2)}</Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Unpaid
                    </Typography>
                    <Typography>${Number(summary.unpaid_amount || 0).toFixed(2)}</Typography>
                  </Box>
                </Stack>
              </Paper>

              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
                <Button size="small" variant="outlined" onClick={refreshHours} disabled={!isEditable}>
                  Refresh from time records
                </Button>
                {isEditable ? (
                  <Button size="small" variant="outlined" onClick={() => runWorkflowAction("refresh_rates")}>
                    Apply scheduling rates
                  </Button>
                ) : null}
                {isEditable && isW2 ? (
                  <Button size="small" variant="outlined" onClick={() => runWorkflowAction("recalculate_taxes")}>
                    Recalculate W-2 taxes
                  </Button>
                ) : null}
                {detail.status === "draft" ? (
                  <Button
                    size="small"
                    variant="contained"
                    onClick={() => runWorkflowAction("hours_reviewed")}
                    disabled={!detail.lines?.length}
                  >
                    Mark hours reviewed
                  </Button>
                ) : null}
                {detail.status === "hours_reviewed" ? (
                  <Button
                    size="small"
                    variant="contained"
                    color="primary"
                    onClick={() => (isW2 ? setSendConfirmOpen(true) : runWorkflowAction("send_to_accountant"))}
                  >
                    Confirm batch ready for accountant
                  </Button>
                ) : null}
                {["sent_to_accountant", "accountant_reviewed", "approved_for_payment", "paid"].includes(
                  detail.status,
                ) ? (
                  <Button
                    size="small"
                    variant="contained"
                    color="success"
                    onClick={() => runWorkflowAction("mark_paid")}
                    disabled={detail.payment_status === "paid"}
                  >
                    Mark batch paid
                  </Button>
                ) : null}
                <FormControl size="small" sx={{ minWidth: 200 }}>
                  <InputLabel>Batch status</InputLabel>
                  <Select
                    label="Batch status"
                    value={detail.status || "draft"}
                    onChange={(e) => setBatchStatus(e.target.value)}
                  >
                    {BATCH_STATUS_FLOW.map((s) => (
                      <MenuItem key={s.value} value={s.value}>
                        {s.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button size="small" variant="outlined" startIcon={<PrintIcon />} onClick={() => setPrintPreviewOpen(true)}>
                  Print preview
                </Button>
                <Button size="small" variant="outlined" onClick={() => openPrintWindow(printRef.current)}>
                  Print
                </Button>
                <Button size="small" variant="outlined" onClick={downloadCsv} disabled={!detail.lines?.length}>
                  CSV
                </Button>
              </Stack>

              <Divider sx={{ mb: 2 }} />

              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Worker</TableCell>
                      <TableCell align="right">Reg hrs</TableCell>
                      {isW2 ? <TableCell align="right">OT</TableCell> : null}
                      <TableCell align="right">Rate</TableCell>
                      <TableCell align="right">Total</TableCell>
                      {isW2 ? (
                        <>
                          <TableCell align="right">Sick +</TableCell>
                          <TableCell align="right">Sick used</TableCell>
                          <TableCell align="right">Sick bal</TableCell>
                          <TableCell align="right">Sick pay</TableCell>
                          <TableCell align="right">Gross</TableCell>
                          <TableCell align="right">
                            Taxes (est.)
                            <Typography variant="caption" color="text.secondary" display="block">
                              {ESTIMATE_DISCLAIMER}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            Net pay (est.)
                            <Typography variant="caption" color="text.secondary" display="block">
                              {ESTIMATE_DISCLAIMER}
                            </Typography>
                          </TableCell>
                        </>
                      ) : isGrossOnly ? (
                        <TableCell align="right">Health credit</TableCell>
                      ) : null}
                      <TableCell>Payment</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(detail.lines || []).map((ln) => (
                      <TableRow key={ln.id} hover>
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                        <TableCell align="right">{Number(ln.approved_hours || 0).toFixed(2)}</TableCell>
                        {isW2 ? (
                          <TableCell align="right">{Number(ln.ot_hours || 0).toFixed(2)}</TableCell>
                        ) : null}
                        <TableCell align="right">
                          {Number(ln.rate || 0) <= 0 ? (
                            <Typography component="span" color="warning.main" variant="body2">
                              Missing
                              {ln.suggested_rate
                                ? ` (suggest $${Number(ln.suggested_rate).toFixed(2)})`
                                : ""}
                            </Typography>
                          ) : (
                            `$${Number(ln.rate || 0).toFixed(2)}`
                          )}
                        </TableCell>
                        <TableCell align="right">${Number(ln.total_amount || 0).toFixed(2)}</TableCell>
                        {isW2 ? (
                          <>
                            <TableCell align="right">
                              {Number(ln.sick_hours_accrued || 0).toFixed(2)}
                            </TableCell>
                            <TableCell align="right">
                              {Number(ln.sick_hours_used || 0).toFixed(2)}
                            </TableCell>
                            <TableCell align="right">
                              {Number(ln.sick_balance_hours ?? ln.sick_balance_after ?? 0).toFixed(2)}
                            </TableCell>
                            <TableCell align="right">
                              ${Number(ln.sick_pay_amount || 0).toFixed(2)}
                            </TableCell>
                            <TableCell align="right">
                              ${Number(ln.gross_wages || ln.gross_amount || 0).toFixed(2)}
                            </TableCell>
                            <TableCell align="right">
                              <Tooltip title={isLineTaxIncomplete(ln) ? ln.net_pay_note || "Profile incomplete" : ""}>
                                <Typography variant="caption" color="text.secondary">
                                  {ln.tax_calc_status === "estimated"
                                    ? formatTaxAmount(ln.employee_taxes_total)
                                    : ln.tax_calc_status === "profile_incomplete"
                                      ? "—"
                                      : "Pending"}
                                </Typography>
                              </Tooltip>
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption" color="text.secondary">
                                {ln.net_pay_display != null
                                  ? formatTaxAmount(ln.net_pay_display)
                                  : ln.net_pay_note || "—"}
                              </Typography>
                            </TableCell>
                          </>
                        ) : isGrossOnly ? (
                          <TableCell align="right">
                            ${Number(ln.health_credit_amount || 0).toFixed(2)}
                          </TableCell>
                        ) : null}
                        <TableCell>
                          <Chip
                            size="small"
                            color={ln.payment_status === "paid" ? "success" : "warning"}
                            label={ln.payment_status_label || ln.payment_status || "Pending"}
                          />
                        </TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={ln.line_status === "approved" ? "success" : "warning"}
                            label={lineStatusLabel(ln.line_status)}
                          />
                        </TableCell>
                        <TableCell align="right">
                          {ln.payment_status !== "paid" &&
                          ["sent_to_accountant", "accountant_reviewed", "approved_for_payment", "paid"].includes(
                            detail.status,
                          ) ? (
                            <Button size="small" onClick={() => markLinePaid(ln.id)}>
                              Mark paid
                            </Button>
                          ) : null}
                          {ln.payment_status === "paid" ? (
                            <Button size="small" onClick={() => markLineUnpaid(ln.id)}>
                              Unpaid
                            </Button>
                          ) : null}
                          <IconButton size="small" onClick={() => setLineEdit({ ...ln })} disabled={!isEditable}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => removeLine(ln.id)}
                            disabled={!isEditable}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    ))}
                    {!detail.lines?.length ? (
                      <TableRow>
                        <TableCell colSpan={isW2 ? 15 : isGrossOnly ? 8 : 7}>
                          <Typography variant="body2" color="text.secondary">
                            No workers in this batch yet. Approve time on Time Records for this pay period,
                            then refresh.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </Paper>
      </Stack>

      <ContractorPrintPreviewDialog
        open={printPreviewOpen}
        onClose={() => setPrintPreviewOpen(false)}
        title="Payout summary"
        printRef={printRef}
      />
      <Box ref={printRef} sx={{ position: "absolute", left: -9999, visibility: "hidden", width: "7.5in" }}>
        {detail ? <PayoutBatchSummaryPrint batch={detail} /> : null}
      </Box>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New payout batch</DialogTitle>
        <DialogContent>{batchFormFields}</DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={createBatch}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit batch</DialogTitle>
        <DialogContent>{batchFormFields}</DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveBatchEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={sendConfirmOpen} onClose={() => setSendConfirmOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Confirm batch ready for accountant?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mt: 1, mb: 1 }}>
            {detail?.send_to_accountant_confirm_message || SEND_TO_ACCOUNTANT_W2_CONFIRM}
          </Typography>
          <Alert severity="success" sx={{ mt: 1 }}>
            {ACCOUNTANT_BATCH_READY_MESSAGE}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSendConfirmOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={async () => {
              setSendConfirmOpen(false);
              await runWorkflowAction("send_to_accountant");
            }}
          >
            Confirm batch ready
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}>
        <DialogTitle>Delete batch?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Delete <strong>{detail?.batch_name}</strong>? Only draft or hours-reviewed batches can be
            deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => confirmDeleteBatch(selectedId)}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!lineEdit} onClose={() => setLineEdit(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Edit line</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2">{lineEdit?.worker_name_snapshot}</Typography>
            <TextField
              size="small"
              type="number"
              label="Hours"
              value={lineEdit?.approved_hours ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, approved_hours: e.target.value })}
            />
            {isW2 ? (
              <>
                <TextField
                  size="small"
                  type="number"
                  label="OT hours"
                  value={lineEdit?.ot_hours ?? ""}
                  onChange={(e) => setLineEdit({ ...lineEdit, ot_hours: e.target.value })}
                />
                <TextField
                  size="small"
                  type="number"
                  label="Sick hours used"
                  value={lineEdit?.sick_hours_used ?? ""}
                  onChange={(e) => setLineEdit({ ...lineEdit, sick_hours_used: e.target.value })}
                />
                <TextField
                  size="small"
                  label="Sick override note (if over balance)"
                  value={lineEdit?.sick_override_note ?? ""}
                  onChange={(e) => setLineEdit({ ...lineEdit, sick_override_note: e.target.value })}
                />
              </>
            ) : null}
            {isGrossOnly ? (
              <>
                <TextField
                  size="small"
                  type="number"
                  label="Health credit $"
                  value={lineEdit?.health_credit_amount ?? ""}
                  onChange={(e) => setLineEdit({ ...lineEdit, health_credit_amount: e.target.value })}
                />
                <TextField
                  size="small"
                  label="Health credit note"
                  value={lineEdit?.health_credit_note ?? ""}
                  onChange={(e) => setLineEdit({ ...lineEdit, health_credit_note: e.target.value })}
                />
              </>
            ) : null}
            <TextField
              size="small"
              type="number"
              label="Rate"
              value={lineEdit?.rate ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, rate: e.target.value })}
            />
            <TextField
              size="small"
              type="number"
              label="Adjustments"
              value={lineEdit?.adjustments ?? ""}
              onChange={(e) => setLineEdit({ ...lineEdit, adjustments: e.target.value })}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLineEdit(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveLineEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
