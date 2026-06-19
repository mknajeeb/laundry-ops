import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  Menu,
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
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import PrintIcon from "@mui/icons-material/Print";
import {
  deletePayoutBatch,
  getPayoutBatch,
  getPayoutBatches,
  patchPayoutBatch,
  postPayoutBatch,
} from "../api";
import ContractorPrintPreviewDialog from "../contractorForms/ContractorPrintPreviewDialog";
import { ContractorPrintLetterhead } from "../contractorForms/ContractorPrintShell";
import { openPrintWindow } from "../contractorForms/contractorPrint";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import {
  ACCOUNTANT_BATCH_READY_MESSAGE,
  SEND_TO_ACCOUNTANT_W2_CONFIRM,
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

function formatStatusLabel(status) {
  return String(status || "draft").replace(/_/g, " ");
}

function compactReadiness(readiness = []) {
  const applicable = readiness.filter((item) => item.applicable !== false);
  if (!applicable.length) return { ready: true, needs: [] };
  const needs = applicable.filter((item) => !item.ok).map((item) => item.label);
  return { ready: needs.length === 0, needs };
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

const BatchWorkerTable = memo(function BatchWorkerTable({
  lines,
  isW2,
  isGrossOnly,
  isEditable,
  batchStatus,
  onEditLine,
  onRemoveLine,
  onMarkPaid,
  onMarkUnpaid,
}) {
  const canMarkPaid = ["sent_to_accountant", "accountant_reviewed", "approved_for_payment", "paid"].includes(
    batchStatus,
  );

  return (
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
                <TableCell align="right">Sick used</TableCell>
                <TableCell align="right">Gross</TableCell>
              </>
            ) : isGrossOnly ? (
              <TableCell align="right">Health credit</TableCell>
            ) : null}
            <TableCell>Payment</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {lines.map((ln) => (
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
                    {ln.suggested_rate ? ` (suggest $${Number(ln.suggested_rate).toFixed(2)})` : ""}
                  </Typography>
                ) : (
                  `$${Number(ln.rate || 0).toFixed(2)}`
                )}
              </TableCell>
              <TableCell align="right">${Number(ln.total_amount || 0).toFixed(2)}</TableCell>
              {isW2 ? (
                <>
                  <TableCell align="right">{Number(ln.sick_hours_used || 0).toFixed(2)}</TableCell>
                  <TableCell align="right">
                    ${Number(ln.gross_wages || ln.gross_amount || 0).toFixed(2)}
                  </TableCell>
                </>
              ) : isGrossOnly ? (
                <TableCell align="right">${Number(ln.health_credit_amount || 0).toFixed(2)}</TableCell>
              ) : null}
              <TableCell>
                <Chip
                  size="small"
                  color={ln.payment_status === "paid" ? "success" : "warning"}
                  label={ln.payment_status_label || ln.payment_status || "Pending"}
                />
              </TableCell>
              <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                {canMarkPaid && ln.payment_status !== "paid" ? (
                  <Button size="small" onClick={() => onMarkPaid(ln.id)}>
                    Mark paid
                  </Button>
                ) : null}
                {ln.payment_status === "paid" ? (
                  <Button size="small" onClick={() => onMarkUnpaid(ln.id)}>
                    Unpaid
                  </Button>
                ) : null}
                <IconButton size="small" onClick={() => onEditLine(ln)} disabled={!isEditable}>
                  <EditIcon fontSize="small" />
                </IconButton>
                <IconButton size="small" color="error" onClick={() => onRemoveLine(ln.id)} disabled={!isEditable}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </TableCell>
            </TableRow>
          ))}
          {!lines.length ? (
            <TableRow>
              <TableCell colSpan={isW2 ? 9 : isGrossOnly ? 7 : 6}>
                <Typography variant="body2" color="text.secondary">
                  No workers yet. Approve time on Time Records, then refresh from time records.
                </Typography>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </TableContainer>
  );
});

export default function PayoutBatchesPanel({
  payPeriodStart = "",
  payPeriodEnd = "",
  onPayPeriodChange,
}) {
  const printRef = useRef(null);
  const autoPickRef = useRef(false);
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [moreAnchor, setMoreAnchor] = useState(null);

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
            setInfo(`Synced ${n} worker line(s) from approved time records.`);
          } else {
            setInfo("No approved time in this period yet — approve rows on Time Records first.");
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
  }, [loadList]);

  useEffect(() => {
    if (!payPeriodStart || !payPeriodEnd || !batches.length || autoPickRef.current) return;
    const ps = normPayPeriodYmd(payPeriodStart);
    const pe = normPayPeriodYmd(payPeriodEnd);
    const match = batches.find(
      (b) =>
        normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
    );
    if (match && selectedId !== match.id) {
      autoPickRef.current = true;
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
          ? `Batch created with ${n} worker line(s).`
          : "Batch created. Approve time on Time Records for this period.",
      );
      await loadList();
      setDetail(res.data);
      setSelectedId(res.data.id);
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
      const n = res.data?.lines?.length || 0;
      setInfo(n ? `Pay period updated — ${n} worker line(s) synced.` : "Pay period updated.");
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
        send_to_accountant: "Batch sent to accountant.",
        mark_paid: "Batch marked paid.",
        mark_line_paid: "Worker marked paid.",
        mark_line_unpaid: "Worker marked unpaid.",
        refresh_rates: "Scheduling rates applied.",
      };
      setInfo(labels[action] || "Updated.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Action failed");
    }
  };

  const markLinePaid = useCallback(
    (lineId) => runWorkflowAction("mark_line_paid", { line_id: lineId }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedId],
  );
  const markLineUnpaid = useCallback(
    (lineId) => runWorkflowAction("mark_line_unpaid", { line_id: lineId }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedId],
  );

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
      const res = await patchPayoutBatch(selectedId, {
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
      setDetail(res.data);
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

  const isEditable = detail?.status === "draft" || detail?.status === "hours_reviewed";
  const isW2 = detail?.worker_category === "w2";
  const isGrossOnly = detail?.worker_category === "temp" || detail?.worker_category === "contractor_1099";
  const summary = detail?.summary || {};
  const batchWarnings = detail?.warnings || [];
  const readinessState = useMemo(() => compactReadiness(detail?.readiness), [detail?.readiness]);
  const workerLines = detail?.lines || [];

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

      <Paper sx={{ p: 1.5 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Typography variant="subtitle1">Payout batches</Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Filter</InputLabel>
              <Select label="Filter" value={filterCat} onChange={(e) => setFilterCat(e.target.value)}>
                {WORKER_CATEGORY_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={openCreateBatch}>
              New batch
            </Button>
          </Stack>
        </Stack>
      </Paper>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} alignItems="stretch">
        <Paper sx={{ width: { xs: "100%", lg: 260 }, flexShrink: 0 }}>
          <List dense sx={{ maxHeight: 520, overflow: "auto" }}>
            {batches.map((b) => (
              <ListItemButton
                key={b.id}
                selected={selectedId === b.id}
                onClick={() => loadDetail(b.id, { quiet: true })}
                sx={{ pr: 0.5 }}
              >
                <ListItemText
                  primary={b.batch_name}
                  secondary={`${b.pay_period_start} – ${b.pay_period_end}`}
                  primaryTypographyProps={{ noWrap: true, variant: "body2" }}
                  secondaryTypographyProps={{ variant: "caption" }}
                />
                <Chip size="small" label={formatStatusLabel(b.status)} sx={{ ml: 0.5, flexShrink: 0 }} />
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
            <Typography color="text.secondary">Select a batch from the list.</Typography>
          ) : (
            <>
              <Stack
                direction={{ xs: "column", md: "row" }}
                justifyContent="space-between"
                spacing={1}
                sx={{ mb: 1.5 }}
              >
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="h6" noWrap>
                    {detail.batch_name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {detail.worker_category_label} · {detail.pay_period_start} – {detail.pay_period_end}
                  </Typography>
                  <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap alignItems="center">
                    <Chip
                      size="small"
                      label={formatStatusLabel(detail.status)}
                      color={detail.status === "paid" ? "success" : "default"}
                    />
                    <Chip
                      size="small"
                      label={batchPaymentLabel(detail.payment_status)}
                      color={batchPaymentColor(detail.payment_status)}
                      variant="outlined"
                    />
                    {readinessState.ready ? (
                      <Chip size="small" color="success" label="Ready to send" variant="outlined" />
                    ) : (
                      readinessState.needs.map((need) => (
                        <Chip key={need} size="small" color="warning" label={`Needs: ${need}`} variant="outlined" />
                      ))
                    )}
                  </Stack>
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    <strong>${Number(detail.total_payout_amount || 0).toFixed(2)}</strong> gross ·{" "}
                    {detail.worker_count} workers · {Number(detail.total_approved_hours || 0).toFixed(2)} hrs
                    {summary.paid_amount || summary.unpaid_amount ? (
                      <>
                        {" "}
                        · Paid ${Number(summary.paid_amount || 0).toFixed(2)} · Unpaid $
                        {Number(summary.unpaid_amount || 0).toFixed(2)}
                      </>
                    ) : null}
                  </Typography>
                  {isW2 ? (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                      Tax estimates only — enter deductions on Payment &amp; Details.
                    </Typography>
                  ) : isGrossOnly ? (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                      Gross payout tracking only. Use Payment &amp; Details for payment records.
                    </Typography>
                  ) : null}
                  {!isEditable ? (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                      Locked for editing — set status to Draft in advanced options to change lines.
                    </Typography>
                  ) : null}
                </Box>
                <Stack direction="row" spacing={0.5} flexShrink={0}>
                  <Button size="small" startIcon={<EditIcon />} onClick={openEditBatch} disabled={!isEditable}>
                    Edit
                  </Button>
                  <Button
                    size="small"
                    color="error"
                    startIcon={<DeleteIcon />}
                    onClick={() => setDeleteOpen(true)}
                    disabled={!isEditable}
                  >
                    Delete
                  </Button>
                </Stack>
              </Stack>

              {batchWarnings.length ? (
                <Stack spacing={0.5} sx={{ mb: 1.5 }}>
                  {batchWarnings.map((w) => (
                    <Alert key={w} severity="warning" sx={{ py: 0 }}>
                      {w}
                    </Alert>
                  ))}
                </Stack>
              ) : null}

              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
                {detail.status === "draft" ? (
                  <Button
                    size="small"
                    variant="contained"
                    onClick={() => runWorkflowAction("hours_reviewed")}
                    disabled={!workerLines.length}
                  >
                    Mark hours reviewed
                  </Button>
                ) : null}
                {detail.status === "hours_reviewed" ? (
                  <Button
                    size="small"
                    variant="contained"
                    onClick={() => (isW2 ? setSendConfirmOpen(true) : runWorkflowAction("send_to_accountant"))}
                  >
                    Send to accountant
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
                <Button
                  size="small"
                  variant="text"
                  endIcon={
                    <ExpandMoreIcon
                      sx={{
                        transform: advancedOpen ? "rotate(180deg)" : "rotate(0deg)",
                        transition: "transform 0.2s",
                      }}
                    />
                  }
                  onClick={() => setAdvancedOpen((v) => !v)}
                >
                  Advanced
                </Button>
                <IconButton size="small" onClick={(e) => setMoreAnchor(e.currentTarget)} aria-label="More actions">
                  <MoreVertIcon />
                </IconButton>
              </Stack>

              <Collapse in={advancedOpen}>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
                  <Button size="small" variant="outlined" onClick={refreshHours} disabled={!isEditable}>
                    Refresh from time records
                  </Button>
                  {isEditable ? (
                    <Button size="small" variant="outlined" onClick={() => runWorkflowAction("refresh_rates")}>
                      Apply scheduling rates
                    </Button>
                  ) : null}
                  <FormControl size="small" sx={{ minWidth: 180 }}>
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
                  <Button size="small" variant="outlined" onClick={downloadCsv} disabled={!workerLines.length}>
                    CSV
                  </Button>
                </Stack>
              </Collapse>

              <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
                <MenuItem
                  onClick={() => {
                    setMoreAnchor(null);
                    refreshHours();
                  }}
                  disabled={!isEditable}
                >
                  Refresh from time records
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    setMoreAnchor(null);
                    runWorkflowAction("refresh_rates");
                  }}
                  disabled={!isEditable}
                >
                  Apply scheduling rates
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    setMoreAnchor(null);
                    setPrintPreviewOpen(true);
                  }}
                >
                  Print preview
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    setMoreAnchor(null);
                    openPrintWindow(printRef.current);
                  }}
                >
                  Print
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    setMoreAnchor(null);
                    downloadCsv();
                  }}
                  disabled={!workerLines.length}
                >
                  Download CSV
                </MenuItem>
              </Menu>

              <BatchWorkerTable
                lines={workerLines}
                isW2={isW2}
                isGrossOnly={isGrossOnly}
                isEditable={isEditable}
                batchStatus={detail.status}
                onEditLine={(ln) => setLineEdit({ ...ln })}
                onRemoveLine={removeLine}
                onMarkPaid={markLinePaid}
                onMarkUnpaid={markLineUnpaid}
              />
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
      {detail ? (
        <Box ref={printRef} sx={{ position: "absolute", left: -9999, visibility: "hidden", width: "7.5in" }}>
          <PayoutBatchSummaryPrint batch={detail} />
        </Box>
      ) : null}

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
        <DialogTitle>Send to accountant?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mt: 1 }}>
            {detail?.send_to_accountant_confirm_message || SEND_TO_ACCOUNTANT_W2_CONFIRM}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
            {ACCOUNTANT_BATCH_READY_MESSAGE}
          </Typography>
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
            Confirm
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)}>
        <DialogTitle>Delete batch?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Delete <strong>{detail?.batch_name}</strong>? Only draft or hours-reviewed batches can be deleted.
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
