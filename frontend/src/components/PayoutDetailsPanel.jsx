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
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import DownloadIcon from "@mui/icons-material/Download";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
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
  setOfficialPayDate,
  unfinalizePayoutDetails,
  estimatePayoutTaxes,
  getPaymentReceiptHtml,
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  getBatchPaystubsHtml,
  getEmployerPayrollPacketHtml,
  getPayRegisterHtml,
  getVendorReceiptHtml,
  getBatchVendorReceiptsHtml,
  listPayrollVendors,
  patchPayoutBatch,
  postPaystubPreviewHtml,
  postRefreshPriorBalances,
  putPayoutBatchDetails,
  setPayoutDocumentMode,
} from "../api";
import { PayrollDateField } from "./PayrollDateTimeField";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import EmployeePaystubArchivePanel from "./EmployeePaystubArchivePanel";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import FinancePayrollFinalizeRow from "./FinancePayrollFinalizeRow";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
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
  isPaymentRecordedPaid,
  isPaymentRecordedUnpaid,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import {
  isVendorReceiptCategory,
  paymentVendorDisplayName,
} from "../payroll/employmentCategory";
import {
  downloadPdfFromFetch,
  paystubBatchDownloadFilename,
  paystubDownloadFilename,
} from "../payroll/paystubDownload";
import { downloadEmployeeRecentPaystubsPdf } from "../payroll/downloadEmployeePaystubArchive";
import { DEFAULT_RECENT_PAYSTUB_BATCHES } from "../payroll/paystubArchive";
import { ESTIMATE_DISCLAIMER } from "../payroll/payrollTaxMessages";
import {
  PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS,
  PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS,
  sumEmployeeRegisterTaxes,
  sumEmployerRegisterTaxes,
} from "../payroll/payrollRegisterTaxFields";

const DEDUCTION_FIELDS = PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS;
const ER_TAX_FIELDS = PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS;

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
  const category = batch?.worker_category || line?.worker_category || "";
  const isVendorReceipt = isVendorReceiptCategory(category);
  const settlement = { ...(pd.settlement || {}) };
  // Temp / 1099 / Try Out: Paid full gross ON by default; show tax balance OFF.
  if (isVendorReceipt && settlement.paid_full_gross_without_withholding === undefined) {
    settlement.paid_full_gross_without_withholding = true;
  }
  if (!settlement.payment_recorded) {
    if (String(line?.payment_status || "").toLowerCase() === "unpaid") {
      settlement.payment_recorded = "unpaid";
    } else if (!batch?.payout_details_finalized_at && String(line?.payment_status || "").toLowerCase() !== "paid") {
      settlement.payment_recorded = "paid";
    }
  }
  let showTax =
    pd.show_tax_payment_section === undefined
      ? !isVendorReceipt
      : Boolean(pd.show_tax_payment_section);
  return {
    line_id: line.id,
    employee_deductions: { ...(pd.employee_deductions || {}) },
    employer_taxes: { ...(pd.employer_taxes || {}) },
    payment,
    settlement,
    tax_summary: { ...(pd.tax_summary || {}) },
    use_payment_receipt: Boolean(pd.use_payment_receipt),
    show_tax_payment_section: showTax,
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
  return roundMoney(Math.min(priorAdj, priorBalance));
}

function withheldForCurrentPeriod(settlement, currentTax, paidFullGross) {
  if (paidFullGross) return 0;
  const raw = settlement?.withheld_from_payment;
  if (raw !== null && raw !== undefined && raw !== "") {
    return Math.min(num(raw), currentTax);
  }
  if (num(settlement?.prior_period_adjustment) > 0) {
    return 0;
  }
  return currentTax;
}

function computeLocalTotals(line, draft) {
  const gross = num(line.gross_amount || line.total_amount);
  const currentTax = sumEmployeeRegisterTaxes(draft.employee_deductions);
  const catchUp = num(draft.settlement?.catch_up_withholding);
  const priorCollected = priorCollectedFromPay(draft.settlement);
  const paidFullGross = Boolean(draft.settlement?.paid_full_gross_without_withholding);
  const withheldCurrent = withheldForCurrentPeriod(
    draft.settlement,
    currentTax,
    paidFullGross,
  );
  const er = sumEmployerRegisterTaxes(draft.employer_taxes) + num(draft.employer_taxes?.other);
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
  return sumEmployeeRegisterTaxes(draft.employee_deductions);
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
          <Typography variant="body2">
            Status:{" "}
            <strong>
              {isPaymentRecordedUnpaid({
                ...ln,
                settlement: draft.settlement,
                payment_recorded: draft.settlement?.payment_recorded,
              })
                ? "UNPAID"
                : isPaymentRecordedPaid({
                    ...ln,
                    settlement: draft.settlement,
                    payment_recorded: draft.settlement?.payment_recorded,
                  })
                  ? "Paid"
                  : "—"}
            </strong>
          </Typography>
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
            {isPaymentRecordedUnpaid({
              ...ln,
              settlement: draft.settlement,
              payment_recorded: draft.settlement?.payment_recorded,
            }) ? (
              <Typography variant="body2" color="warning.main" fontWeight={700}>
                UNPAID — not included in paid totals
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
      {isPaymentRecordedUnpaid(ln) ? (
        <Typography variant="caption" color="warning.main" fontWeight={700}>UNPAID — not treated as money paid</Typography>
      ) : ln.payment_status === "paid" || isPaymentRecordedPaid(ln) ? (
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
  const [finalizePayDate, setFinalizePayDate] = useState("");
  const [confirmPayDate, setConfirmPayDate] = useState(false);
  const [payDateCorrectOpen, setPayDateCorrectOpen] = useState(false);
  const [correctPayDate, setCorrectPayDate] = useState("");
  const [correctPayDateReason, setCorrectPayDateReason] = useState("");
  const [moreAnchor, setMoreAnchor] = useState(null);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const [paystubCopyMode, setPaystubCopyMode] = useState("employee");
  const [panelTab, setPanelTab] = useState("batch");
  const [archiveInitialUserId, setArchiveInitialUserId] = useState("");
  const [archiveInitialWorkerName, setArchiveInitialWorkerName] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState({});
  const [vendors, setVendors] = useState([]);

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

  const usesVendorReceiptCategory = isVendorReceiptCategory(detail?.worker_category);

  useEffect(() => {
    if (!usesVendorReceiptCategory) return;
    listPayrollVendors({ includeInactive: false, paymentOnly: true })
      .then((res) => setVendors(res.data?.vendors || []))
      .catch(() => setVendors([]));
  }, [usesVendorReceiptCategory]);

  const setLineVendor = async (lineId, vendorId) => {
    if (!selectedId) return;
    setError("");
    try {
      await putPayoutBatchDetails(selectedId, {
        lines: [{ line_id: lineId, vendor_id: vendorId || null }],
      });
      await loadDetail(selectedId);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Vendor update failed");
    }
  };

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
        drafts[ln.id] = emptyLineState(ln, res.data);
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

  const refreshPriorBalances = async () => {
    if (!selectedId || !canEdit || finalized) return;
    setError("");
    setInfo("");
    try {
      const res = await postRefreshPriorBalances(selectedId);
      const batch = res.data;
      setDetail(batch);
      const drafts = {};
      (batch.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln, batch);
      });
      setLineDrafts(drafts);
      const refresh = batch.prior_balance_refresh || {};
      const count = Number(refresh.updated || 0);
      if (count > 0) {
        setInfo(`Prior tax balances refreshed for ${count} employee(s) from last finalized pay.`);
      } else {
        setInfo("Prior tax balances already match last finalized pay — no changes.");
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Refresh prior balances failed");
    }
  };

  const doFinalize = async () => {
    setError("");
    if (!finalizePayDate) {
      setError("Official Pay Date is required to finalize.");
      return;
    }
    if (!confirmPayDate) {
      setError("Confirm the Official Pay Date explicitly before finalizing.");
      return;
    }
    try {
      const saved = await saveDetails({ silent: true });
      if (!saved) return;
      const res = await finalizePayoutDetails(selectedId, {
        official_pay_date: finalizePayDate,
        confirm_pay_date: true,
      });
      setDetail(res.data);
      setFinalizeOpen(false);
      setConfirmPayDate(false);
      setInfo("Finalized — batch closed and ready to pay.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Finalize failed");
    }
  };

  const openFinalizeDialog = () => {
    const suggested =
      detail?.suggested_pay_date ||
      detail?.payout_workflow?.suggested_pay_date ||
      "";
    setFinalizePayDate(suggested || "");
    setConfirmPayDate(false);
    setFinalizeOpen(true);
  };

  const doCorrectPayDate = async () => {
    setError("");
    if (!correctPayDate || String(correctPayDateReason || "").trim().length < 3) {
      setError("Official Pay Date and a reason (at least 3 characters) are required.");
      return;
    }
    try {
      const res = await setOfficialPayDate(selectedId, {
        official_pay_date: correctPayDate,
        reason: correctPayDateReason.trim(),
      });
      setDetail(res.data);
      setPayDateCorrectOpen(false);
      setCorrectPayDateReason("");
      setInfo("Official Pay Date updated — report membership only; wages unchanged.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Pay Date update failed");
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

  const setLinePaymentRecorded = async (lineId, recorded) => {
    if (!selectedId) return;
    setError("");
    try {
      const action = recorded === "unpaid" ? "mark_line_unpaid" : "mark_line_paid";
      const res = await patchPayoutBatch(selectedId, { action, line_id: lineId });
      setDetail(res.data);
      const drafts = {};
      (res.data.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln, res.data);
      });
      setLineDrafts(drafts);
      setInfo(recorded === "unpaid" ? "Marked UNPAID." : "Marked paid.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Payment status update failed");
    }
  };

  const usesVendorReceipt = Boolean(
    detail?.payout_workflow?.uses_vendor_receipt ||
      isVendorReceiptCategory(detail?.worker_category),
  );

  const showPaystubActions =
    !usesVendorReceipt &&
    !isReceiptMode &&
    Boolean(
      detail?.payout_workflow?.paystub_preview_available ||
        detail?.payout_workflow?.paystub_available ||
        detail?.payout_workflow?.can_edit_details ||
        detail?.status === "approved_for_payment",
    );

  const showVendorReceiptActions =
    usesVendorReceipt &&
    Boolean(
      detail?.payout_workflow?.vendor_receipt_available ||
        detail?.payout_workflow?.vendor_receipt_preview_available,
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
      await downloadPdfFromFetch(
        fetchPaystubHtml(lineId, draft),
        paystubFilenameForLine(ln),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub download failed");
    }
  };

  const downloadEmployeeRecentPaystubs = async (ln) => {
    if (!ln?.user_id) {
      setError("Employee ID missing — use Employee paystub archive tab");
      return;
    }
    setError("");
    try {
      await downloadEmployeeRecentPaystubsPdf({
        userId: ln.user_id,
        workerName: ln.worker_name_snapshot,
        workerCategory: detail?.worker_category,
        copy: paystubCopyMode,
        recentCount: DEFAULT_RECENT_PAYSTUB_BATCHES,
      });
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Recent paystub download failed");
    }
  };

  const openArchiveForEmployee = (ln) => {
    if (!ln?.user_id) return;
    setArchiveInitialUserId(String(ln.user_id));
    setArchiveInitialWorkerName(ln.worker_name_snapshot || "");
    setPanelTab("archive");
  };

  const downloadAllPaystubs = async () => {
    if (!selectedId || !showPaystubActions) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      const copy = paystubCopyMode;
      const filename = paystubBatchDownloadFilename(
        detail?.batch_name,
        detail?.pay_period_start,
        detail?.pay_period_end,
      );
      await downloadPdfFromFetch(
        () => getBatchPaystubsHtml(selectedId, { preview: !finalized, copy }),
        filename,
      );
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

  const previewVendorReceipt = async (lineId) => {
    if (!selectedId) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      await previewHtmlDocument(() =>
        getVendorReceiptHtml(selectedId, lineId, { preview: !finalized }),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Vendor receipt preview failed");
    }
  };

  const printVendorReceipt = async (lineId) => {
    if (!selectedId) return;
    setError("");
    try {
      await printHtmlDocument(() =>
        getVendorReceiptHtml(selectedId, lineId, { preview: !finalized }),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Vendor receipt load failed");
    }
  };

  const previewAllVendorReceipts = async () => {
    if (!selectedId) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      await previewHtmlDocument(() =>
        getBatchVendorReceiptsHtml(selectedId, { preview: !finalized }),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Preview all receipts failed");
    }
  };

  const printAllVendorReceipts = async () => {
    if (!selectedId) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      await printHtmlDocument(() =>
        getBatchVendorReceiptsHtml(selectedId, { preview: !finalized }),
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Print all receipts failed");
    }
  };

  const downloadAllVendorReceipts = async () => {
    if (!selectedId) return;
    setError("");
    try {
      if (canEdit && !finalized) {
        const ok = await saveDetails({ silent: true });
        if (!ok) return;
      }
      const filename = paystubBatchDownloadFilename(
        detail?.batch_name,
        detail?.pay_period_start,
        detail?.pay_period_end,
      );
      await downloadPdfFromFetch(
        () => getBatchVendorReceiptsHtml(selectedId, { preview: !finalized }),
        filename,
      );
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Download receipts failed");
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

      <Tabs
        value={panelTab}
        onChange={(_, value) => setPanelTab(value)}
        sx={{ borderBottom: 1, borderColor: "divider", minHeight: 36 }}
      >
        <Tab value="batch" label="Batch details" sx={{ minHeight: 36, py: 0.5 }} />
        <Tab value="archive" label="Employee paystub archive" sx={{ minHeight: 36, py: 0.5 }} />
      </Tabs>

      {panelTab === "archive" ? (
        <EmployeePaystubArchivePanel
          onError={setError}
          initialUserId={archiveInitialUserId}
          initialWorkerName={archiveInitialWorkerName}
        />
      ) : null}

      {panelTab === "batch" && batches.length > 1 ? (
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

      {panelTab === "batch" && !batches.length ? (
        <Typography variant="body2" color="text.secondary">
          Approve hours on a payout batch to enter payroll details.
        </Typography>
      ) : null}

      {panelTab === "batch" && detail ? (
        <>
          <PayrollBatchSummaryCard batch={detail} compact />

          {detail.worker_category === "w2" ? (
            <Paper
              variant="outlined"
              sx={{
                p: 1.5,
                borderLeft: `4px solid ${VEEWASH_BRAND.primary}`,
                bgcolor: finalized ? "rgba(46, 125, 50, 0.08)" : "rgba(2, 136, 209, 0.08)",
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                {finalized ? (
                  <CheckCircleOutlineIcon color="success" fontSize="small" />
                ) : (
                  <HourglassEmptyIcon color="info" fontSize="small" />
                )}
                <Box>
                  <Typography variant="subtitle2" fontWeight={700}>
                    {finalized
                      ? "Batch finalized — ready to pay or mark paid"
                      : detail.status === "sent_to_accountant"
                        ? "Awaiting accountant to confirm payroll processed"
                        : "Enter taxes from accountant payroll run, then finalize"}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {finalized
                      ? "Paystubs are available — print or email from this tab as needed."
                      : "Record Federal (FIT) and State taxes for each employee, payment method and date, then click Finalize & close batch."}
                  </Typography>
                  {finalized && (detail.pay_date_missing || detail.payout_workflow?.pay_date_missing) ? (
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                      <Chip size="small" color="warning" label="Pay Date Missing" />
                      <Typography variant="caption" color="text.secondary">
                        Excluded from Monthly Payroll Paid until an Official Pay Date is assigned.
                      </Typography>
                      <Button size="small" onClick={() => {
                        setCorrectPayDate("");
                        setCorrectPayDateReason("");
                        setPayDateCorrectOpen(true);
                      }}>
                        Assign Pay Date
                      </Button>
                    </Stack>
                  ) : null}
                  {finalized && detail.official_pay_date ? (
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                      <Chip size="small" color="success" label={`Pay Date ${detail.official_pay_date}`} />
                      <Button size="small" onClick={() => {
                        setCorrectPayDate(detail.official_pay_date || "");
                        setCorrectPayDateReason("");
                        setPayDateCorrectOpen(true);
                      }}>
                        Correct Pay Date
                      </Button>
                    </Stack>
                  ) : null}
                </Box>
              </Stack>
            </Paper>
          ) : null}

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
                  Download batch PDF
                </Button>
              </>
            ) : null}
            {showVendorReceiptActions ? (
              <>
                <Button
                  size="small"
                  startIcon={<VisibilityIcon />}
                  onClick={previewAllVendorReceipts}
                >
                  Preview All Receipts
                </Button>
                <Button
                  size="small"
                  startIcon={<PrintIcon />}
                  onClick={printAllVendorReceipts}
                >
                  Print All Receipts
                </Button>
                <Button
                  size="small"
                  startIcon={<DownloadIcon />}
                  onClick={downloadAllVendorReceipts}
                >
                  Download batch PDF
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
              <Button size="small" onClick={refreshPriorBalances} disabled={finalized}>
                Refresh prior balances
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
                onClick={openFinalizeDialog}
                disabled={!canFinalize}
              >
                Finalize & close batch
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
            <Tooltip title="Finance admin: enter taxes withheld by accountant, payment details, then finalize.">
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
                  <TableCell align="right">FWT</TableCell>
                  <TableCell align="right">NY State</TableCell>
                  <TableCell align="right">Total tax</TableCell>
                  <TableCell align="right">Net paid</TableCell>
                  <TableCell>Method</TableCell>
                  <TableCell align="right">Paid</TableCell>
                  <TableCell align="right" width={72} />
                </TableRow>
              </TableHead>
              <TableBody>
                {(detail.lines || []).map((ln) => {
                  const draft = lineDrafts[ln.id] || emptyLineState(ln, detail);
                  const totals = computeLocalTotals(ln, draft);
                  const method = draft.payment?.method || "direct_deposit";
                  const doc = ln.document || {};
                  const isOpen = expanded[ln.id];
                  const lineUnpaid = isPaymentRecordedUnpaid(ln);
                  const linePaid = isPaymentRecordedPaid(ln);
                  const outstanding = lineUnpaid
                    ? totals.net
                    : totals.net - (linePaid ? totals.net : 0);
                  const vendorLabel = paymentVendorDisplayName(
                    ln.vendor?.name || ln.vendor?.display_name || doc.vendor?.name || "",
                  );
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
                        <TableCell>
                          <Stack direction="row" spacing={0.75} alignItems="center">
                            <span>{ln.worker_name_snapshot}</span>
                            {finalized && lineUnpaid ? (
                              <Chip size="small" color="warning" label="UNPAID" sx={{ fontWeight: 700 }} />
                            ) : null}
                          </Stack>
                        </TableCell>
                        <TableCell align="right">${totals.gross.toFixed(2)}</TableCell>
                        <TableCell align="right">
                          ${num(draft.employee_deductions?.fit).toFixed(2)}
                        </TableCell>
                        <TableCell align="right">
                          ${num(draft.employee_deductions?.state).toFixed(2)}
                        </TableCell>
                        <TableCell align="right">
                          <Stack direction="row" alignItems="center" justifyContent="flex-end" gap={0.25}>
                            <span>
                              {finalized ? taxWithheldDisplay : `$${lineTaxTotal(draft).toFixed(2)}`}
                            </span>
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
                        <TableCell align="right">{netDisplay}</TableCell>
                        <TableCell>
                          {PAYMENT_METHODS.find((m) => m.value === method)?.label || method}
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip
                            title={
                              lineUnpaid
                                ? "UNPAID — not included in paid totals"
                                : linePaid
                                ? "Paid"
                                : outstanding > 0
                                  ? `Outstanding $${outstanding.toFixed(2)}`
                                  : "Not yet paid"
                            }
                          >
                            <span>
                              {lineUnpaid ? (
                                <Chip size="small" color="warning" label="UNPAID" sx={{ fontWeight: 700 }} />
                              ) : linePaid ? (
                                formatPayrollMoney(totals.net)
                              ) : (
                                "—"
                              )}
                            </span>
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
                          {finalized && doc.receipt_available && !usesVendorReceipt ? (
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
                          {usesVendorReceipt &&
                          (doc.vendor_receipt_available ||
                            doc.vendor_receipt_preview_available) ? (
                            <Stack direction="row" justifyContent="flex-end" spacing={0.25}>
                              <Tooltip title="Preview vendor receipt">
                                <IconButton
                                  size="small"
                                  onClick={() => previewVendorReceipt(ln.id)}
                                >
                                  <VisibilityIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Print vendor receipt">
                                <IconButton
                                  size="small"
                                  onClick={() => printVendorReceipt(ln.id)}
                                >
                                  <PrintIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Stack>
                          ) : null}
                        </TableCell>
                      </TableRow>
                      <TableRow key={`${ln.id}-exp`}>
                        <TableCell colSpan={10} sx={{ py: 0, borderBottom: isOpen ? undefined : "none" }}>
                          <Collapse in={isOpen}>
                            <Box sx={{ py: 1.5, pl: 1 }}>
                              {canEdit ? (
                                <FinancePayrollFinalizeRow
                                  ln={ln}
                                  draft={draft}
                                  totals={totals}
                                  method={method}
                                  isReceiptMode={isReceiptMode}
                                  advancedOpen={Boolean(advancedOpen[ln.id])}
                                  onToggleAdvanced={() =>
                                    setAdvancedOpen((prev) => ({ ...prev, [ln.id]: !prev[ln.id] }))
                                  }
                                  onUpdateDraft={updateDraft}
                                  onUpdateLineFlag={updateLineFlag}
                                />
                              ) : (
                                <LineDetailsReadonly
                                  draft={draft}
                                  ln={ln}
                                  totals={totals}
                                  isReceiptMode={isReceiptMode}
                                />
                              )}
                              {finalized && !usesVendorReceipt ? (
                                <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                                  {lineUnpaid ? (
                                    <Button
                                      size="small"
                                      variant="contained"
                                      color="success"
                                      onClick={() => setLinePaymentRecorded(ln.id, "paid")}
                                    >
                                      Mark as Paid
                                    </Button>
                                  ) : linePaid ? (
                                    <Button
                                      size="small"
                                      color="warning"
                                      onClick={() => setLinePaymentRecorded(ln.id, "unpaid")}
                                    >
                                      Mark UNPAID
                                    </Button>
                                  ) : null}
                                </Stack>
                              ) : null}
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
                                  {ln.user_id ? (
                                    <Button
                                      size="small"
                                      startIcon={<DownloadIcon />}
                                      onClick={() => downloadEmployeeRecentPaystubs(ln)}
                                    >
                                      Download last {DEFAULT_RECENT_PAYSTUB_BATCHES} paystubs
                                    </Button>
                                  ) : null}
                                  {ln.user_id ? (
                                    <Button
                                      size="small"
                                      onClick={() => openArchiveForEmployee(ln)}
                                    >
                                      Archive tab…
                                    </Button>
                                  ) : null}
                                </Stack>
                              ) : null}
                              {usesVendorReceipt ? (
                                <Stack
                                  direction="row"
                                  spacing={1}
                                  alignItems="center"
                                  flexWrap="wrap"
                                  useFlexGap
                                  sx={{ mt: 1.5 }}
                                >
                                  <Chip
                                    size="small"
                                    color="info"
                                    variant="outlined"
                                    label={`Vendor: ${vendorLabel || "Not assigned"}`}
                                  />
                                  {canEdit && !finalized ? (
                                    <Select
                                      size="small"
                                      displayEmpty
                                      required
                                      value={ln.vendor_id ?? ""}
                                      onChange={(e) =>
                                        setLineVendor(ln.id, e.target.value || null)
                                      }
                                      sx={{ minWidth: 190, fontSize: "0.8rem" }}
                                    >
                                      <MenuItem value="">
                                        <em>Select vendor…</em>
                                      </MenuItem>
                                      {vendors.map((v) => (
                                        <MenuItem key={v.id} value={v.id}>
                                          {v.display_name || paymentVendorDisplayName(v.name) || v.name}
                                        </MenuItem>
                                      ))}
                                    </Select>
                                  ) : null}
                                  {finalized && lineUnpaid ? (
                                    <Button
                                      size="small"
                                      variant="contained"
                                      color="success"
                                      onClick={() => setLinePaymentRecorded(ln.id, "paid")}
                                    >
                                      Mark as Paid
                                    </Button>
                                  ) : null}
                                  {finalized && linePaid && !lineUnpaid ? (
                                    <Button
                                      size="small"
                                      color="warning"
                                      onClick={() => setLinePaymentRecorded(ln.id, "unpaid")}
                                    >
                                      Mark UNPAID
                                    </Button>
                                  ) : null}
                                    </Select>
                                  ) : null}
                                  {doc.vendor_receipt_available ||
                                  doc.vendor_receipt_preview_available ? (
                                    <>
                                      <Button
                                        size="small"
                                        startIcon={<VisibilityIcon />}
                                        onClick={() => previewVendorReceipt(ln.id)}
                                      >
                                        Preview Receipt
                                      </Button>
                                      <Button
                                        size="small"
                                        startIcon={<PrintIcon />}
                                        onClick={() => printVendorReceipt(ln.id)}
                                      >
                                        Print Receipt
                                      </Button>
                                    </>
                                  ) : null}
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

      <Dialog open={finalizeOpen} onClose={() => setFinalizeOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Finalize & close this payroll batch?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Locks tax and payment fields, generates official paystubs, and marks the batch ready to pay.
            Print or email paystubs from this tab when employees are paid.
          </Typography>
          {(() => {
            const s = detail?.finalize_cost_summary || {};
            return (
              <Stack spacing={0.75} sx={{ mb: 2 }}>
                <Typography variant="body2">
                  <strong>Payroll period:</strong> {s.pay_period_start || detail?.pay_period_start} –{" "}
                  {s.pay_period_end || detail?.pay_period_end}
                </Typography>
                <Typography variant="body2">
                  <strong>Employee count:</strong> {s.employee_count ?? detail?.lines?.length ?? "—"}
                </Typography>
                <Typography variant="body2">
                  <strong>Gross pay:</strong> {formatPayrollMoney(s.gross_pay)}
                </Typography>
                <Typography variant="body2">
                  <strong>Net pay:</strong> {formatPayrollMoney(s.net_pay)}
                </Typography>
                <Typography variant="body2">
                  <strong>Employer taxes:</strong> {formatPayrollMoney(s.employer_taxes)}
                </Typography>
                <Typography variant="body2">
                  <strong>Total payroll cost:</strong> {formatPayrollMoney(s.total_payroll_cost)}
                </Typography>
              </Stack>
            );
          })()}
          <PayrollDateField
            label="Official Pay Date"
            value={finalizePayDate}
            onChange={(v) => {
              setFinalizePayDate(v);
              setConfirmPayDate(false);
            }}
            size="small"
            sx={{ mb: 1, mt: 1 }}
          />
          {detail?.suggested_pay_date || detail?.payout_workflow?.suggested_pay_date ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              Suggested (not applied unless you confirm):{" "}
              {detail?.suggested_pay_date || detail?.payout_workflow?.suggested_pay_date}
            </Typography>
          ) : null}
          <Alert severity="info" sx={{ mb: 1 }}>
            The Pay Date determines which monthly payroll report this batch appears in.
          </Alert>
          <FormControlLabel
            control={
              <Checkbox
                checked={confirmPayDate}
                onChange={(e) => setConfirmPayDate(e.target.checked)}
              />
            }
            label="I confirm this Official Pay Date is the date employees are actually paid"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFinalizeOpen(false)}>Cancel</Button>
          <Button
            onClick={doFinalize}
            variant="contained"
            disabled={!finalizePayDate || !confirmPayDate}
          >
            Finalize & close batch
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={payDateCorrectOpen} onClose={() => setPayDateCorrectOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {(detail?.pay_date_missing || detail?.payout_workflow?.pay_date_missing)
            ? "Assign Official Pay Date"
            : "Correct Official Pay Date"}
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 1.5 }}>
            Changes report membership only. Does not recalculate wages, taxes, gross, or net.
          </Alert>
          <PayrollDateField
            label="Official Pay Date"
            value={correctPayDate}
            onChange={setCorrectPayDate}
            size="small"
            sx={{ mb: 1.5, mt: 1 }}
          />
          <TextField
            label="Reason (required)"
            value={correctPayDateReason}
            onChange={(e) => setCorrectPayDateReason(e.target.value)}
            fullWidth
            multiline
            minRows={2}
            size="small"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPayDateCorrectOpen(false)}>Cancel</Button>
          <Button onClick={doCorrectPayDate} variant="contained">
            Save Pay Date
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
