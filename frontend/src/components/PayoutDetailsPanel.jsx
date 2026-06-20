import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
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
  FormControlLabel,
  Checkbox,
  IconButton,
  Menu,
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
  Tooltip,
  Typography,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import PrintIcon from "@mui/icons-material/Print";
import VisibilityIcon from "@mui/icons-material/Visibility";
import SaveIcon from "@mui/icons-material/Save";
import LockIcon from "@mui/icons-material/Lock";
import LockOpenIcon from "@mui/icons-material/LockOpen";
import { useAuth } from "../context/AuthContext";
import {
  finalizePayoutDetails,
  unfinalizePayoutDetails,
  estimatePayoutTaxes,
  getPaymentReceiptHtml,
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  getBatchPaystubsHtml,
  getEmployerPayrollPacketHtml,
  getPayRegisterHtml,
  postPaystubPreviewHtml,
  putPayoutBatchDetails,
  setPayoutDocumentMode,
} from "../api";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import {
  batchVisibleForDetails,
  displayStatusColor,
  displayStatusLabel,
  formatPayrollMoney,
} from "../payroll/payrollBatchStatus";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import {
  downloadHtmlFromFetch,
  paystubDownloadFilename,
} from "../payroll/paystubDownload";
import { ESTIMATE_DISCLAIMER } from "../payroll/payrollTaxMessages";

const DEDUCTION_FIELDS = [
  { key: "fit", label: "FIT" },
  { key: "ss", label: "SS" },
  { key: "medicare", label: "Medicare" },
  { key: "state", label: "State" },
  { key: "local", label: "Local" },
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

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function emptyLineState(line, batch = null) {
  const pd = line?.payout_details || {};
  const defaultPayDate = batch?.pay_period_end || batch?.pay_period_start || "";
  const payment = { ...(pd.payment || {}) };
  if (!payment.date && defaultPayDate) {
    payment.date = defaultPayDate;
  }
  return {
    line_id: line.id,
    employee_deductions: { ...(pd.employee_deductions || {}) },
    employer_taxes: { ...(pd.employer_taxes || {}) },
    payment,
    settlement: { ...(pd.settlement || {}) },
    tax_summary: { ...(pd.tax_summary || {}) },
    use_payment_receipt: Boolean(pd.use_payment_receipt),
    show_tax_payment_section:
      pd.show_tax_payment_section === undefined ? true : Boolean(pd.show_tax_payment_section),
    employee_note: pd.employee_note || "",
  };
}

function roundMoney(n) {
  return Math.round(num(n) * 100) / 100;
}

function effectivePriorTaxBalance(priorBalance, priorAdj) {
  return roundMoney(Math.max(0, priorBalance - priorAdj));
}

function priorCollectedFromPay(settlement) {
  const catchUp = num(settlement?.catch_up_withholding);
  if (catchUp > 0) return roundMoney(catchUp);
  const priorBalance = num(settlement?.prior_unpaid_taxes);
  const priorAdj = num(settlement?.prior_period_adjustment);
  if (priorAdj <= 0) return 0;
  const effectivePrior = effectivePriorTaxBalance(priorBalance, priorAdj);
  if (effectivePrior > 0) return roundMoney(priorAdj);
  return 0;
}

function withheldForCurrentPeriod(settlement, currentTax, paidFullGross) {
  if (paidFullGross) return 0;
  const raw = settlement?.withheld_from_payment;
  if (raw !== null && raw !== undefined && raw !== "") {
    return Math.min(num(raw), currentTax);
  }
  const priorBalance = num(settlement?.prior_unpaid_taxes);
  const priorAdj = num(settlement?.prior_period_adjustment);
  if (priorAdj > 0 && effectivePriorTaxBalance(priorBalance, priorAdj) > 0) {
    return 0;
  }
  return currentTax;
}

function computeLocalTotals(line, draft) {
  const gross = num(line.gross_amount || line.total_amount);
  const currentTax = DEDUCTION_FIELDS.reduce(
    (s, f) => s + num(draft.employee_deductions?.[f.key]),
    0,
  );
  const catchUp = num(draft.settlement?.catch_up_withholding);
  const priorCollected = priorCollectedFromPay(draft.settlement);
  const paidFullGross = Boolean(draft.settlement?.paid_full_gross_without_withholding);
  const withheldCurrent = withheldForCurrentPeriod(
    draft.settlement,
    currentTax,
    paidFullGross,
  );
  const er = ER_TAX_FIELDS.reduce((s, f) => s + num(draft.employer_taxes?.[f.key]), 0);
  const withheld = paidFullGross ? 0 : roundMoney(withheldCurrent + priorCollected);
  const net = paidFullGross ? gross : Math.max(0, roundMoney(gross - withheld));
  return {
    gross,
    totalDed: currentTax,
    totalEr: er,
    net,
    withheld,
    withheldCurrent,
    catchUp,
    priorCollected,
    paidFullGross,
  };
}

function priorStillOwed(priorBalance, effectivePrior, priorAdj, priorCollected) {
  if (priorAdj > 0) return roundMoney(effectivePrior);
  if (priorCollected > 0) return roundMoney(Math.max(0, priorBalance - priorCollected));
  return roundMoney(effectivePrior);
}

function reconcileLocalTaxSummary(draft, totals) {
  const settlement = { ...(draft.settlement || {}) };
  const taxSummary = { ...(draft.tax_summary || {}) };
  const currentPeriod = totals.totalDed;
  const priorBalance = num(settlement.prior_unpaid_taxes);
  const priorAdj = num(settlement.prior_period_adjustment);
  const effectivePrior = effectivePriorTaxBalance(priorBalance, priorAdj);
  const priorCollected = totals.priorCollected;
  const paidFullGross = totals.paidFullGross;

  if (paidFullGross) {
    settlement.catch_up_withholding = 0;
  }

  const actualWithheld = totals.withheld;
  const totalLiability = roundMoney(currentPeriod + effectivePrior);

  let periodBalance;
  if (paidFullGross) {
    periodBalance = roundMoney(currentPeriod);
  } else {
    const withheldForCurrent = roundMoney(
      Math.min(currentPeriod, Math.max(0, actualWithheld - priorCollected)),
    );
    periodBalance = roundMoney(currentPeriod - withheldForCurrent);
  }

  const priorStill = priorStillOwed(
    priorBalance,
    effectivePrior,
    priorAdj,
    priorCollected,
  );
  const remaining = roundMoney(priorStill + periodBalance);

  settlement.tax_balance_owed = periodBalance;
  taxSummary.current_period_taxes = currentPeriod;
  taxSummary.prior_tax_balance = priorBalance;
  taxSummary.total_tax_liability = totalLiability;
  taxSummary.actual_tax_withheld = actualWithheld;
  taxSummary.tax_balance_owed = periodBalance;
  taxSummary.remaining_balance = remaining;
  taxSummary.tax_catch_up_adjustment = priorCollected;

  return { ...draft, settlement, tax_summary: taxSummary };
}

function applyLocalSettlementMath(draft, line) {
  const totals = computeLocalTotals(line, draft);
  const settlement = { ...(draft.settlement || {}) };
  if (totals.paidFullGross) {
    settlement.catch_up_withholding = 0;
    settlement.withheld_from_payment = null;
    settlement.amount_withheld = 0;
    settlement.amount_paid = totals.gross;
  } else {
    settlement.amount_withheld = totals.withheld;
    settlement.amount_paid = totals.net;
  }
  settlement.outstanding_balance = 0;
  const withSettlement = { ...draft, settlement };
  return reconcileLocalTaxSummary(withSettlement, totals);
}

async function previewHtmlDocument(fetchFn) {
  const res = await fetchFn();
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.open();
  win.document.write(res.data);
  win.document.close();
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

function payoutDetailsPayload(draft) {
  return {
    employee_deductions: draft.employee_deductions,
    employer_taxes: draft.employer_taxes,
    payment: draft.payment,
    settlement: draft.settlement,
    tax_summary: draft.tax_summary,
    use_payment_receipt: draft.use_payment_receipt,
    show_tax_payment_section: draft.show_tax_payment_section,
    employee_note: draft.employee_note || "",
  };
}

function lineTaxTotal(draft) {
  return DEDUCTION_FIELDS.reduce((s, f) => s + num(draft.employee_deductions?.[f.key]), 0);
}

function formatDraftMoney(v) {
  return `$${num(v).toFixed(2)}`;
}

function LineDetailsReadonly({ draft, ln, totals, isReceiptMode }) {
  const method =
    PAYMENT_METHODS.find((m) => m.value === draft.payment?.method)?.label ||
    draft.payment?.method ||
    "—";

  return (
    <Stack spacing={1.25}>
      {!isReceiptMode ? (
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Employee taxes (estimated)
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={2}>
            {DEDUCTION_FIELDS.map((f) => (
              <Typography key={f.key} variant="body2">
                {f.label}: <strong>{formatDraftMoney(draft.employee_deductions?.[f.key])}</strong>
              </Typography>
            ))}
          </Stack>
        </Box>
      ) : null}
      <Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
          Payment
        </Typography>
        <Stack direction="row" flexWrap="wrap" gap={2}>
          <Typography variant="body2">
            Method: <strong>{method}</strong>
          </Typography>
          <Typography variant="body2">
            Date: <strong>{draft.payment?.date || "—"}</strong>
          </Typography>
          {draft.payment?.check_number ? (
            <Typography variant="body2">
              Check #: <strong>{draft.payment.check_number}</strong>
            </Typography>
          ) : null}
          {draft.payment?.reference ? (
            <Typography variant="body2">
              Reference: <strong>{draft.payment.reference}</strong>
            </Typography>
          ) : null}
          {draft.payment?.method === "cash" && draft.payment?.cash_amount != null ? (
            <Typography variant="body2">
              Cash amount: <strong>{formatDraftMoney(draft.payment.cash_amount)}</strong>
            </Typography>
          ) : null}
        </Stack>
      </Box>
      {!isReceiptMode ? (
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Settlement
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={2}>
            <Typography variant="body2">
              Amount paid: <strong>{formatDraftMoney(draft.settlement?.amount_paid ?? totals.net)}</strong>
            </Typography>
            <Typography variant="body2">
              Withheld: <strong>{formatDraftMoney(draft.settlement?.amount_withheld)}</strong>
            </Typography>
            <Typography variant="body2">
              Estimated tax balance:{" "}
              <strong>{formatDraftMoney(draft.tax_summary?.remaining_balance)}</strong>
            </Typography>
            <Typography variant="body2">
              Total estimated liability:{" "}
              <strong>{formatDraftMoney(draft.tax_summary?.total_tax_liability)}</strong>
            </Typography>
            <Typography variant="body2">
              Prior tax balance: <strong>{formatDraftMoney(draft.settlement?.prior_unpaid_taxes)}</strong>
            </Typography>
            <Typography variant="body2">
              Tax on paystub:{" "}
              <strong>{draft.show_tax_payment_section ? "Shown" : "Hidden"}</strong>
            </Typography>
            {totals.paidFullGross ? (
              <Typography variant="body2" color="warning.main">
                Paid full gross (no withholding)
              </Typography>
            ) : null}
          </Stack>
        </Box>
      ) : null}
      {!isReceiptMode ? (
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Employer taxes
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={2}>
            {ER_TAX_FIELDS.map((f) => (
              <Typography key={f.key} variant="body2">
                {f.label}: <strong>{formatDraftMoney(draft.employer_taxes?.[f.key])}</strong>
              </Typography>
            ))}
          </Stack>
        </Box>
      ) : null}
      {draft.employee_note ? (
        <Typography variant="body2">
          Employee note: <strong>{draft.employee_note}</strong>
        </Typography>
      ) : null}
      {ln.payment_status === "paid" ? (
        <Typography variant="caption" color="success.main">Line marked paid</Typography>
      ) : null}
    </Stack>
  );
}

export default function PayoutDetailsPanel({ initialBatchId = null } = {}) {
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
  const canEditDetails =
    hasPerm("ta.settings") || hasPerm("users.edit") || rolesUpper.includes("ADMIN");

  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(initialBatchId);
  const [detail, setDetail] = useState(null);
  const [lineDrafts, setLineDrafts] = useState({});
  const [batchNote, setBatchNote] = useState("");
  const [expanded, setExpanded] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [unfinalizeOpen, setUnfinalizeOpen] = useState(false);
  const [moreAnchor, setMoreAnchor] = useState(null);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const [paystubCopyMode, setPaystubCopyMode] = useState("employee");

  const loadBatches = useCallback(async () => {
    try {
      const res = await getPayoutBatches();
      const all = (res.data?.items || []).filter(batchVisibleForDetails);
      setBatches(all);
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
        drafts[ln.id] = emptyLineState(ln, batch);
      });
      setLineDrafts(drafts);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  useEffect(() => {
    if (initialBatchId) loadDetail(initialBatchId);
  }, [initialBatchId, loadDetail]);

  useEffect(() => {
    if (!selectedId && batches.length && !initialBatchId) {
      loadDetail(batches[0].id);
    }
  }, [batches, selectedId, initialBatchId, loadDetail]);

  const canEdit = detail?.payout_workflow?.can_edit_details && canEditDetails;
  const finalized = detail?.payout_workflow?.payout_details_finalized;
  const documentMode =
    detail?.payout_workflow?.document_mode || detail?.document_mode || "official_paystub";
  const isReceiptMode = documentMode === "payment_receipt";
  const canFinalize = detail?.payout_workflow?.can_finalize;
  const canUnfinalize = detail?.payout_workflow?.can_unfinalize && canEditDetails;
  const finalizeBlockers = detail?.payout_workflow?.finalize_blockers || [];
  const canSetDocumentMode = detail?.payout_workflow?.can_set_document_mode && canEditDetails;

  const updateDraft = (lineId, section, key, value) => {
    setLineDrafts((prev) => {
      const line = (detail?.lines || []).find((ln) => ln.id === lineId);
      const nextDraft = {
        ...prev[lineId],
        [section]: { ...prev[lineId][section], [key]: value },
      };
      const shouldRecalc =
        section === "employee_deductions" ||
        section === "settlement";
      return {
        ...prev,
        [lineId]: shouldRecalc && line ? applyLocalSettlementMath(nextDraft, line) : nextDraft,
      };
    });
  };

  const updateLineFlag = (lineId, key, value) => {
    setLineDrafts((prev) => ({ ...prev, [lineId]: { ...prev[lineId], [key]: value } }));
  };

  const saveDetails = async ({ silent = false } = {}) => {
    if (!selectedId || !canEdit) return false;
    if (!silent) {
      setError("");
      setInfo("");
    }
    const lines = Object.values(lineDrafts).map((d) => ({
      line_id: d.line_id,
      payout_details: payoutDetailsPayload(d),
    }));
    try {
      const res = await putPayoutBatchDetails(selectedId, { lines, batch_note: batchNote });
      setDetail(res.data);
      setBatchNote(res.data.batch_note || "");
      const drafts = {};
      (res.data.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln);
      });
      setLineDrafts(drafts);
      if (!silent) setInfo("Saved.");
      await loadBatches();
      return true;
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
      return false;
    }
  };

  const changeDocumentMode = async (mode) => {
    if (!selectedId || !canSetDocumentMode) return;
    setError("");
    try {
      const res = await setPayoutDocumentMode(selectedId, mode);
      setDetail(res.data);
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Mode change failed");
    }
  };

  const autoFillEstimates = async () => {
    if (!selectedId || !canEdit) return;
    setError("");
    setInfo("");
    try {
      const res = await estimatePayoutTaxes(selectedId);
      const batch = res.data;
      setDetail(batch);
      const drafts = {};
      (batch.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln, batch);
      });
      setLineDrafts(drafts);
      setInfo("Minimum estimated withholding applied — review and edit before finalizing.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Auto-fill failed");
    }
  };

  const doFinalize = async () => {
    setError("");
    try {
      const saved = await saveDetails({ silent: true });
      if (!saved) return;
      const res = await finalizePayoutDetails(selectedId);
      setDetail(res.data);
      setFinalizeOpen(false);
      setInfo("Finalized — ready to pay.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Finalize failed");
    }
  };

  const doUnfinalize = async () => {
    setError("");
    try {
      const res = await unfinalizePayoutDetails(selectedId);
      setDetail(res.data);
      setUnfinalizeOpen(false);
      setInfo("Reopened for editing — remember to finalize again after changes.");
      const drafts = {};
      (res.data.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln, res.data);
      });
      setLineDrafts(drafts);
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Unfinalize failed");
    }
  };

  const showPaystubActions =
    !isReceiptMode &&
    Boolean(
      detail?.payout_workflow?.paystub_preview_available ||
        detail?.payout_workflow?.paystub_available ||
        detail?.payout_workflow?.can_edit_details ||
        detail?.status === "approved_for_payment",
    );

  const fetchPaystubHtml = (lineId, draft) => {
    const copy = paystubCopyMode;
    if (finalized) {
      return () => getPaystubHtml(selectedId, lineId, { copy });
    }
    return () =>
      postPaystubPreviewHtml(selectedId, lineId, {
        payout_details: payoutDetailsPayload(draft),
        batch_note: batchNote,
        copy,
      });
  };

  const previewPaystub = async (lineId) => {
    if (!selectedId || !showPaystubActions) return;
    const draft = lineDrafts[lineId];
    if (!draft) return;
    setError("");
    try {
      await previewHtmlDocument(fetchPaystubHtml(lineId, draft));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub preview failed");
    }
  };

  const printPaystub = async (lineId) => {
    if (!selectedId || !showPaystubActions) return;
    const draft = lineDrafts[lineId];
    if (!draft) return;
    setError("");
    try {
      await printHtmlDocument(fetchPaystubHtml(lineId, draft));
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub load failed");
    }
  };

  const paystubFilenameForLine = (ln) =>
    paystubDownloadFilename(
      ln?.worker_name_snapshot,
      detail?.pay_period_start,
      detail?.pay_period_end,
    );

  const downloadPaystub = async (lineId) => {
    if (!selectedId || !showPaystubActions) return;
    const draft = lineDrafts[lineId];
    const ln = (detail?.lines || []).find((row) => row.id === lineId);
    if (!draft || !ln) return;
    setError("");
    try {
      await downloadHtmlFromFetch(
        fetchPaystubHtml(lineId, draft),
        paystubFilenameForLine(ln),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub download failed");
    }
  };

  const downloadAllPaystubs = async () => {
    if (!selectedId || !showPaystubActions) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      const lines = (detail?.lines || []).filter((ln) => lineDrafts[ln.id]);
      for (let i = 0; i < lines.length; i += 1) {
        await downloadPaystub(lines[i].id);
        if (i < lines.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Download all paystubs failed");
    }
  };

  const previewAllPaystubs = async () => {
    if (!selectedId || !showPaystubActions) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      const copy = paystubCopyMode;
      if (copy === "employer") {
        await previewHtmlDocument(() =>
          getEmployerPayrollPacketHtml(selectedId, { preview: !finalized }),
        );
      } else {
        await previewHtmlDocument(() =>
          getBatchPaystubsHtml(selectedId, { preview: !finalized, copy: "employee" }),
        );
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Preview all paystubs failed");
    }
  };

  const printAllPaystubs = async () => {
    if (!selectedId || !showPaystubActions) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      const copy = paystubCopyMode;
      if (copy === "employer") {
        await printHtmlDocument(() =>
          getEmployerPayrollPacketHtml(selectedId, { preview: !finalized }),
        );
      } else {
        await printHtmlDocument(() =>
          getBatchPaystubsHtml(selectedId, { preview: !finalized, copy: "employee" }),
        );
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Print all paystubs failed");
    }
  };

  const printPayRegister = async () => {
    if (!selectedId) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      await printHtmlDocument(() =>
        getPayRegisterHtml(selectedId, { preview: !finalized }),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Pay register failed");
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

  const toggleExpand = (lineId) => {
    setExpanded((prev) => ({ ...prev, [lineId]: !prev[lineId] }));
  };

  return (
    <Stack spacing={1.5}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      {batches.length > 1 ? (
        <Stack direction="row" flexWrap="wrap" gap={0.5}>
          {batches.map((b) => (
            <Chip
              key={b.id}
              size="small"
              label={`${b.batch_name} · ${displayStatusLabel(b)}`}
              color={displayStatusColor(b)}
              variant={selectedId === b.id ? "filled" : "outlined"}
              onClick={() => loadDetail(b.id)}
              sx={{ cursor: "pointer" }}
            />
          ))}
        </Stack>
      ) : null}

      {!batches.length ? (
        <Typography variant="body2" color="text.secondary">
          Approve hours on a payout batch to enter payroll details.
        </Typography>
      ) : null}

      {detail ? (
        <>
          <PayrollBatchSummaryCard batch={detail} compact />

          <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end" flexWrap="wrap">
            {showPaystubActions ? (
              <>
                <Select
                  size="small"
                  value={paystubCopyMode}
                  onChange={(e) => setPaystubCopyMode(e.target.value)}
                  sx={{ minWidth: 170, fontSize: "0.8rem" }}
                >
                  <MenuItem value="employee">Employee Copy</MenuItem>
                  <MenuItem value="employer">Employer Copy / Packet</MenuItem>
                </Select>
                <Button size="small" startIcon={<VisibilityIcon />} onClick={previewAllPaystubs}>
                  Preview All Paystubs
                </Button>
                <Button size="small" startIcon={<PrintIcon />} onClick={printAllPaystubs}>
                  Print All Paystubs
                </Button>
                <Button size="small" startIcon={<DownloadIcon />} onClick={downloadAllPaystubs}>
                  Download All Paystubs
                </Button>
              </>
            ) : null}
            <Button size="small" startIcon={<PrintIcon />} onClick={printPayRegister} disabled={!detail}>
              Print Pay Register
            </Button>
            {canEdit ? (
              <Button size="small" onClick={autoFillEstimates} disabled={finalized}>
                Auto-fill minimum withholding
              </Button>
            ) : null}
            {canEdit ? (
              <Button size="small" startIcon={<SaveIcon />} onClick={() => saveDetails()}>
                Save
              </Button>
            ) : null}
            {canEdit ? (
              <Button
                size="small"
                startIcon={<LockIcon />}
                variant="contained"
                onClick={() => setFinalizeOpen(true)}
                disabled={!canFinalize}
              >
                Finalize
              </Button>
            ) : null}
            {canUnfinalize ? (
              <Button
                size="small"
                startIcon={<LockOpenIcon />}
                color="warning"
                onClick={() => setUnfinalizeOpen(true)}
              >
                Unfinalize
              </Button>
            ) : null}
            <IconButton size="small" onClick={(e) => setMoreAnchor(e.currentTarget)}>
              <MoreVertIcon fontSize="small" />
            </IconButton>
            <Tooltip title="Enter estimated withholding and payment details per employee. Edit before finalize.">
              <InfoOutlinedIcon fontSize="small" color="action" sx={{ opacity: 0.5 }} />
            </Tooltip>
          </Stack>

          {finalizeBlockers.length && !finalized ? (
            <Alert severity="warning" sx={{ mt: 1 }}>
              Before finalize: {finalizeBlockers.join("; ")}
            </Alert>
          ) : null}

          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            {ESTIMATE_DISCLAIMER}
          </Typography>

          <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
            {canSetDocumentMode ? (
              <MenuItem
                onClick={() => {
                  setMoreAnchor(null);
                  changeDocumentMode(isReceiptMode ? "official_paystub" : "payment_receipt");
                }}
              >
                Switch to {isReceiptMode ? "Official Paystubs" : "Payment Receipts"}
              </MenuItem>
            ) : null}
            <MenuItem
              onClick={() => {
                setMoreAnchor(null);
                setBatchNote((n) => n);
              }}
              disabled={!canEdit}
            >
              Batch note on paystubs
            </MenuItem>
          </Menu>

          {canEdit ? (
            <TextField
              fullWidth
              size="small"
              multiline
              minRows={1}
              label="Batch note (paystubs)"
              value={batchNote}
              onChange={(e) => setBatchNote(e.target.value)}
              sx={{ mt: 0.5 }}
            />
          ) : null}

          <Paper variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell width={32} />
                  <TableCell>Employee</TableCell>
                  <TableCell align="right">Gross</TableCell>
                  <TableCell align="right">Est. withholding liability</TableCell>
                  <TableCell align="right">Estimated withholding</TableCell>
                  <TableCell align="right">Net paid</TableCell>
                  <TableCell>Method</TableCell>
                  <TableCell align="right">Paid</TableCell>
                  <TableCell align="right" width={72} />
                </TableRow>
              </TableHead>
              <TableBody>
                {(detail.lines || []).map((ln) => {
                  const draft = lineDrafts[ln.id] || emptyLineState(ln);
                  const totals = computeLocalTotals(ln, draft);
                  const method = draft.payment?.method || "direct_deposit";
                  const doc = ln.document || {};
                  const isOpen = expanded[ln.id];
                  const linePaid = ln.payment_status === "paid";
                  const outstanding = totals.net - (linePaid ? totals.net : 0);
                  const taxLiability = finalized
                    ? ln.tax_liability != null
                      ? formatPayrollMoney(ln.tax_liability)
                      : `$${lineTaxTotal(draft).toFixed(2)}`
                    : `$${lineTaxTotal(draft).toFixed(2)}`;
                  const priorBalance = num(
                    draft.settlement?.prior_unpaid_taxes ?? ln.prior_tax_balance,
                  );
                  const catchUp = num(draft.settlement?.catch_up_withholding);
                  const taxWithheldDisplay = finalized
                    ? formatTaxWithheldDisplay(ln)
                    : totals.paidFullGross
                      ? "$0.00"
                      : `$${totals.withheld.toFixed(2)}`;
                  const netDisplay = finalized
                    ? formatNetPaidDisplay(ln)
                    : `$${totals.net.toFixed(2)}`;

                  return (
                    <Fragment key={ln.id}>
                      <TableRow hover sx={{ "& td": { py: 0.75 } }}>
                        <TableCell>
                          <IconButton size="small" onClick={() => toggleExpand(ln.id)}>
                            <ExpandMoreIcon
                              fontSize="small"
                              sx={{ transform: isOpen ? "rotate(180deg)" : "none" }}
                            />
                          </IconButton>
                        </TableCell>
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                        <TableCell align="right">${totals.gross.toFixed(2)}</TableCell>
                        <TableCell align="right">
                          <Stack direction="row" alignItems="center" justifyContent="flex-end" gap={0.25}>
                            <span>{taxLiability}</span>
                            {finalized && hasTaxWithheldBreakdown(ln) ? (
                              <IconButton
                                size="small"
                                onClick={() =>
                                  setTaxDialog({
                                    open: true,
                                    line: ln,
                                    workerName: ln.worker_name_snapshot,
                                  })
                                }
                              >
                                <InfoOutlinedIcon fontSize="small" />
                              </IconButton>
                            ) : null}
                          </Stack>
                        </TableCell>
                        <TableCell align="right">
                          {priorBalance > 0 ? (
                            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                              Prior: ${priorBalance.toFixed(2)}
                            </Typography>
                          ) : null}
                          {taxWithheldDisplay}
                        </TableCell>
                        <TableCell align="right">{netDisplay}</TableCell>
                        <TableCell>
                          {PAYMENT_METHODS.find((m) => m.value === method)?.label || method}
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip
                            title={
                              linePaid
                                ? "Paid"
                                : outstanding > 0
                                  ? `Outstanding $${outstanding.toFixed(2)}`
                                  : "Not yet paid"
                            }
                          >
                            <span>{linePaid ? formatPayrollMoney(totals.net) : "—"}</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell align="right">
                          {showPaystubActions ? (
                            <Stack direction="row" justifyContent="flex-end" spacing={0.25}>
                              <Tooltip title="Preview paystub">
                                <IconButton size="small" onClick={() => previewPaystub(ln.id)}>
                                  <VisibilityIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Print paystub">
                                <IconButton size="small" onClick={() => printPaystub(ln.id)}>
                                  <PrintIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Download paystub">
                                <IconButton size="small" onClick={() => downloadPaystub(ln.id)}>
                                  <DownloadIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Stack>
                          ) : null}
                          {finalized && doc.receipt_available ? (
                            <Tooltip
                              title={
                                method === "cash" ? "Generate cash receipt" : "Print payment receipt"
                              }
                            >
                              <IconButton size="small" onClick={() => printReceipt(ln.id)}>
                                <PrintIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </TableCell>
                      </TableRow>
                      <TableRow key={`${ln.id}-exp`}>
                        <TableCell colSpan={9} sx={{ py: 0, borderBottom: isOpen ? undefined : "none" }}>
                          <Collapse in={isOpen}>
                            <Box sx={{ py: 1, pl: 1 }}>
                              {canEdit ? (
                                <>
                                  {!isReceiptMode ? (
                                    <>
                                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
                                        Estimated withholding (editable before finalize)
                                      </Typography>
                                      <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
                                        {DEDUCTION_FIELDS.map((f) => (
                                          <TextField
                                            key={f.key}
                                            size="small"
                                            label={f.label}
                                            type="number"
                                            value={draft.employee_deductions?.[f.key] ?? ""}
                                            onChange={(e) =>
                                              updateDraft(ln.id, "employee_deductions", f.key, e.target.value)
                                            }
                                            inputProps={{ style: { width: 64 } }}
                                          />
                                        ))}
                                      </Stack>
                                    </>
                                  ) : null}
                                  <Stack direction="row" flexWrap="wrap" gap={1}>
                                    <TextField
                                      size="small"
                                      select
                                      label="Method"
                                      value={method}
                                      onChange={(e) => updateDraft(ln.id, "payment", "method", e.target.value)}
                                      SelectProps={{ native: true }}
                                      sx={{ minWidth: 120 }}
                                    >
                                      {PAYMENT_METHODS.map((m) => (
                                        <option key={m.value} value={m.value}>{m.label}</option>
                                      ))}
                                    </TextField>
                                    <TextField
                                      size="small"
                                      type="date"
                                      label="Payment date"
                                      value={draft.payment?.date || ""}
                                      onChange={(e) => updateDraft(ln.id, "payment", "date", e.target.value)}
                                      InputLabelProps={{ shrink: true }}
                                      sx={{ minWidth: 150 }}
                                    />
                                    <TextField
                                      size="small"
                                      label="Check #"
                                      value={draft.payment?.check_number || ""}
                                      onChange={(e) =>
                                        updateDraft(ln.id, "payment", "check_number", e.target.value)
                                      }
                                    />
                                    <TextField
                                      size="small"
                                      label="Reference"
                                      value={draft.payment?.reference || ""}
                                      onChange={(e) =>
                                        updateDraft(ln.id, "payment", "reference", e.target.value)
                                      }
                                    />
                                    <TextField
                                      size="small"
                                      label="Employee note"
                                      value={draft.employee_note || ""}
                                      onChange={(e) => updateLineFlag(ln.id, "employee_note", e.target.value)}
                                    />
                                  </Stack>
                                  {method === "cash" ? (
                                    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                                      <TextField
                                        size="small"
                                        type="number"
                                        label="Cash amount"
                                        value={draft.payment?.cash_amount ?? ""}
                                        onChange={(e) => updateDraft(ln.id, "payment", "cash_amount", e.target.value)}
                                      />
                                      <TextField
                                        size="small"
                                        label="Paid by"
                                        value={draft.payment?.paid_by || ""}
                                        onChange={(e) => updateDraft(ln.id, "payment", "paid_by", e.target.value)}
                                      />
                                      <TextField
                                        size="small"
                                        label="Receipt number"
                                        value={draft.payment?.receipt_number || ""}
                                        onChange={(e) =>
                                          updateDraft(ln.id, "payment", "receipt_number", e.target.value)
                                        }
                                      />
                                      <TextField
                                        size="small"
                                        label="Employee signature"
                                        value={draft.payment?.employee_signature || ""}
                                        onChange={(e) =>
                                          updateDraft(ln.id, "payment", "employee_signature", e.target.value)
                                        }
                                      />
                                    </Stack>
                                  ) : null}
                                  <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Withheld this period"
                                      value={draft.settlement?.withheld_from_payment ?? ""}
                                      onChange={(e) =>
                                        updateDraft(
                                          ln.id,
                                          "settlement",
                                          "withheld_from_payment",
                                          e.target.value === "" ? null : e.target.value,
                                        )
                                      }
                                      disabled={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                                      helperText="Actual tax taken from this pay (blank = withhold full estimate)"
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Catch-up withholding"
                                      value={draft.settlement?.catch_up_withholding ?? ""}
                                      onChange={(e) =>
                                        updateDraft(ln.id, "settlement", "catch_up_withholding", e.target.value)
                                      }
                                      disabled={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                                      helperText="Collect prior balance only — not this week's partial withholding"
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Amount paid (net)"
                                      value={draft.settlement?.amount_paid ?? ""}
                                      InputProps={{ readOnly: true }}
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Estimated withholding (total)"
                                      value={draft.settlement?.amount_withheld ?? ""}
                                      InputProps={{ readOnly: true }}
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Prior tax balance"
                                      value={draft.settlement?.prior_unpaid_taxes ?? ""}
                                      onChange={(e) =>
                                        updateDraft(ln.id, "settlement", "prior_unpaid_taxes", e.target.value)
                                      }
                                      helperText="Shown for reference — does not reduce pay unless catch-up entered"
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Prior-period adj."
                                      value={draft.settlement?.prior_period_adjustment ?? ""}
                                      onChange={(e) =>
                                        updateDraft(ln.id, "settlement", "prior_period_adjustment", e.target.value)
                                      }
                                      helperText="Credits prior balance; partial amount is withheld from this pay"
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="Remaining estimated balance"
                                      value={draft.tax_summary?.remaining_balance ?? ""}
                                      InputProps={{ readOnly: true }}
                                      helperText="Net prior balance plus this period unpaid tax"
                                    />
                                    <TextField
                                      size="small"
                                      type="number"
                                      label="This period unpaid"
                                      value={draft.settlement?.tax_balance_owed ?? ""}
                                      InputProps={{ readOnly: true }}
                                      helperText="Current-period portion not withheld from pay"
                                    />
                                    <FormControlLabel
                                      control={
                                        <Checkbox
                                          size="small"
                                          checked={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                                          onChange={(e) =>
                                            updateDraft(
                                              ln.id,
                                              "settlement",
                                              "paid_full_gross_without_withholding",
                                              e.target.checked,
                                            )
                                          }
                                        />
                                      }
                                      label="Paid full gross (no withholding)"
                                    />
                                    <FormControlLabel
                                      control={
                                        <Checkbox
                                          size="small"
                                          checked={Boolean(draft.show_tax_payment_section)}
                                          onChange={(e) =>
                                            updateLineFlag(
                                              ln.id,
                                              "show_tax_payment_section",
                                              e.target.checked,
                                            )
                                          }
                                        />
                                      }
                                      label="Show tax balance on employee paystub"
                                      sx={{ alignItems: "flex-start" }}
                                    />
                                    <Typography
                                      variant="caption"
                                      color="text.secondary"
                                      sx={{ display: "block", mt: -0.5, mb: 0.5 }}
                                    >
                                      Temporary during catch-up period — uncheck after ~5–6 weeks when
                                      balances are cleared.
                                    </Typography>
                                  </Stack>
                                  {!isReceiptMode ? (
                                    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
                                      {ER_TAX_FIELDS.map((f) => (
                                        <TextField
                                          key={f.key}
                                          size="small"
                                          label={f.label}
                                          type="number"
                                          value={draft.employer_taxes?.[f.key] ?? ""}
                                          onChange={(e) =>
                                            updateDraft(ln.id, "employer_taxes", f.key, e.target.value)
                                          }
                                          inputProps={{ style: { width: 64 } }}
                                        />
                                      ))}
                                    </Stack>
                                  ) : null}
                                </>
                              ) : (
                                <LineDetailsReadonly
                                  draft={draft}
                                  ln={ln}
                                  totals={totals}
                                  isReceiptMode={isReceiptMode}
                                />
                              )}
                              {showPaystubActions ? (
                                <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                                  <Button
                                    size="small"
                                    startIcon={<VisibilityIcon />}
                                    onClick={() => previewPaystub(ln.id)}
                                  >
                                    Preview Paystub
                                  </Button>
                                  <Button
                                    size="small"
                                    startIcon={<PrintIcon />}
                                    onClick={() => printPaystub(ln.id)}
                                  >
                                    Print Paystub
                                  </Button>
                                  <Button
                                    size="small"
                                    startIcon={<DownloadIcon />}
                                    onClick={() => downloadPaystub(ln.id)}
                                  >
                                    Download Paystub
                                  </Button>
                                </Stack>
                              ) : null}
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </Paper>
        </>
      ) : null}

      <TaxWithheldBreakdownDialog
        open={taxDialog.open}
        onClose={() => setTaxDialog({ open: false, line: null, workerName: "" })}
        line={taxDialog.line}
        workerName={taxDialog.workerName}
      />

      <Dialog open={unfinalizeOpen} onClose={() => setUnfinalizeOpen(false)}>
        <DialogTitle>Reopen payroll details?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Unlocks tax and payment fields for editing. Official paystubs and receipts are hidden until you finalize again.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUnfinalizeOpen(false)}>Cancel</Button>
          <Button onClick={doUnfinalize} color="warning" variant="contained">Unfinalize</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={finalizeOpen} onClose={() => setFinalizeOpen(false)}>
        <DialogTitle>Finalize payroll details?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            Locks tax edits and marks payroll ready to pay.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFinalizeOpen(false)}>Cancel</Button>
          <Button onClick={doFinalize} variant="contained">Finalize</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
