import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import PayPeriodSelect from "./PayPeriodSelect";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import { getPayoutBatchDetails, getPayoutBatches, processPayoutBatch } from "../api";
import {
  accountantPeriodStatusColor,
  accountantPeriodStatusLabel,
  pickDefaultAccountantBatch,
} from "../payroll/accountantBatchPick";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEFAULT_OT_MULTIPLIER = 1.5;

const DEDUCTION_COLUMNS = [
  { key: "fit", label: "FIT" },
  { key: "ss", label: "SS" },
  { key: "medicare", label: "Medicare" },
  { key: "state", label: "State" },
  { key: "local", label: "Local" },
  { key: "other", label: "Other", keys: ["other1", "other2"] },
];

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function lineGross(ln) {
  return num(ln.gross_amount || ln.total_amount || ln.gross_wages);
}

function deductionAmount(ln, col) {
  const ded = ln.payout_details?.employee_deductions || {};
  if (col.keys) {
    return col.keys.reduce((s, k) => s + num(ded[k]), 0);
  }
  return num(ded[col.key]);
}

function lineTotalTax(ln) {
  if (ln.tax_withheld != null && ln.tax_withheld !== "") return num(ln.tax_withheld);
  const ded = ln.payout_details?.employee_deductions || {};
  return DEDUCTION_COLUMNS.reduce((s, col) => s + deductionAmount({ payout_details: { employee_deductions: ded } }, col), 0);
}

function formatMoney(v) {
  return `$${num(v).toFixed(2)}`;
}

function formatMoneyOrPending(finalized, v) {
  if (!finalized) return "—";
  return formatMoney(v);
}

function formatRate(rate) {
  const n = num(rate);
  return n > 0 ? `$${n.toFixed(2)}` : "—";
}

function computeLineRates(ln, otMultiplier = DEFAULT_OT_MULTIPLIER) {
  const regRate = num(ln.rate);
  const otHours = num(ln.ot_hours);
  const otRate = otHours > 0 && regRate > 0 ? regRate * otMultiplier : 0;
  return { regRate, otRate };
}

function paymentStatusColor(status) {
  if (status === "paid") return "success";
  if (status === "approved_unpaid") return "warning";
  return "default";
}

function WorkflowStep({ active, done, label, description }) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start">
      <Box
        sx={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          bgcolor: done ? "success.main" : active ? VEEWASH_BRAND.primary : "action.hover",
          color: done || active ? "common.white" : "text.secondary",
          fontSize: "0.75rem",
          fontWeight: 700,
        }}
      >
        {done ? <CheckCircleOutlineIcon sx={{ fontSize: 18 }} /> : active ? "●" : "○"}
      </Box>
      <Box>
        <Typography variant="body2" fontWeight={active || done ? 600 : 400}>
          {label}
        </Typography>
        {description ? (
          <Typography variant="caption" color="text.secondary">{description}</Typography>
        ) : null}
      </Box>
    </Stack>
  );
}

function TaxCell({ line, workerName, onOpen }) {
  const finalized = isPayoutDetailsFinalized(line);
  const label = formatTaxWithheldDisplay(line);
  const clickable = finalized && (hasTaxWithheldBreakdown(line) || label !== "Pending");
  if (!clickable) {
    return <Typography variant="body2">{finalized ? label : "—"}</Typography>;
  }
  return (
    <Link
      component="button"
      type="button"
      variant="body2"
      underline="hover"
      onClick={() => onOpen(line, workerName)}
      sx={{ cursor: "pointer" }}
    >
      {label}
    </Link>
  );
}

export default function AccountantPayrollPanel() {
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [periodExpanded, setPeriodExpanded] = useState(false);
  const [batches, setBatches] = useState([]);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const autoPickedRef = useRef(false);

  const loadBatches = useCallback(async () => {
    try {
      const res = await getPayoutBatches({ worker_category: "w2" });
      setBatches(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load batches");
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  const periodBatch = useMemo(() => {
    if (!periodStart || !periodEnd) return null;
    const ps = normPayPeriodYmd(periodStart);
    const pe = normPayPeriodYmd(periodEnd);
    return batches.find(
      (b) =>
        normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
    );
  }, [batches, periodStart, periodEnd]);

  const loadDetail = useCallback(async (batchId) => {
    if (!batchId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await getPayoutBatchDetails(batchId);
      setDetail(res.data);
    } catch (e) {
      setError(e.response?.data?.error || "Load failed");
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDetail(periodBatch?.id);
  }, [periodBatch?.id, loadDetail]);

  useEffect(() => {
    if (!batches.length || autoPickedRef.current) return;
    const pick = pickDefaultAccountantBatch(batches);
    if (pick) {
      setPeriodStart(normPayPeriodYmd(pick.pay_period_start));
      setPeriodEnd(normPayPeriodYmd(pick.pay_period_end));
    }
    autoPickedRef.current = true;
  }, [batches]);

  const tableTotals = useMemo(() => {
    const lines = detail?.lines || [];
    const totals = {
      count: lines.length,
      paidCount: 0,
      pendingCount: 0,
      regHours: 0,
      otHours: 0,
      gross: 0,
      deductions: Object.fromEntries(DEDUCTION_COLUMNS.map((c) => [c.key, 0])),
      totalTax: 0,
      net: 0,
      hasFinalizedLines: false,
    };
    for (const ln of lines) {
      totals.regHours += num(ln.approved_hours);
      totals.otHours += num(ln.ot_hours);
      totals.gross += lineGross(ln);
      if (ln.payment_status === "paid") totals.paidCount += 1;
      else totals.pendingCount += 1;
      if (!isPayoutDetailsFinalized(ln)) continue;
      totals.hasFinalizedLines = true;
      for (const col of DEDUCTION_COLUMNS) {
        totals.deductions[col.key] += deductionAmount(ln, col);
      }
      totals.totalTax += lineTotalTax(ln);
      totals.net += num(ln.net_paid);
    }
    return totals;
  }, [detail]);

  const periodStatus = accountantPeriodStatusLabel(periodBatch || detail);
  const status = String(detail?.status || "");
  const workflow = detail?.payout_workflow || {};
  const finalized = workflow.payout_details_finalized;

  const canConfirmProcessed = detail?.can_process_as_accountant && status === "sent_to_accountant";
  const financePending = status === "approved_for_payment" && !finalized;

  const confirmPayrollProcessed = async () => {
    if (!detail?.id) return;
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const res = await processPayoutBatch(detail.id);
      setDetail(res.data);
      setInfo("Payroll processed — finance admin can now enter tax details and finalize.");
      await loadBatches();
      await loadDetail(res.data.id);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not confirm payroll");
    } finally {
      setSubmitting(false);
    }
  };

  const colSpan = 5 + DEDUCTION_COLUMNS.length + 3;

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      <Paper
        variant="outlined"
        sx={{
          p: 2,
          borderTop: `3px solid ${VEEWASH_BRAND.primary}`,
          bgcolor: "background.paper",
        }}
      >
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          flexWrap="wrap"
          gap={1}
          sx={{ mb: 1.5 }}
        >
          <Typography variant="h6" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
            For Accountant
          </Typography>
          {periodStatus ? (
            <Chip
              size="small"
              label={periodStatus}
              color={accountantPeriodStatusColor(periodBatch || detail)}
            />
          ) : null}
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Confirm when payroll has been processed externally. Finance admin enters deductions,
          updates net pay, and prints or emails paystubs on the Finalize Payroll tab.
        </Typography>
        {batches.length ? (
          <PayPeriodSelect
            weekStartsOn={weekStartsOn}
            batches={batches}
            start={periodStart}
            end={periodEnd}
            expanded={periodExpanded}
            onExpandedChange={setPeriodExpanded}
            batchStatusLabel={accountantPeriodStatusLabel}
            batchOnly
            onChange={({ start, end }) => {
              setPeriodStart(start);
              setPeriodEnd(end);
            }}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            No W-2 batches awaiting review.
          </Typography>
        )}
      </Paper>

      {detail ? (
        <>
          <PayrollBatchSummaryCard batch={detail} compact />

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
              Workflow
            </Typography>
            <Stack spacing={1.5}>
              <WorkflowStep
                active={canConfirmProcessed}
                done={status !== "sent_to_accountant" && status !== "hours_reviewed"}
                label="Confirm payroll processed"
                description="You run payroll in your external system — no tax entry here."
              />
              <WorkflowStep
                active={financePending}
                done={finalized}
                label="Finance admin enters taxes & finalizes"
                description="Deductions, net pay, and paystubs on Finalize Payroll tab."
              />
            </Stack>
          </Paper>

          <Paper variant="outlined">
            <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider" }}>
              <Typography variant="subtitle2" fontWeight={700}>
                Employees in this batch
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {tableTotals.count} employee{tableTotals.count === 1 ? "" : "s"} · Reg{" "}
                {tableTotals.regHours.toFixed(2)}h · OT {tableTotals.otHours.toFixed(2)}h · Gross{" "}
                {formatMoney(tableTotals.gross)}
                {tableTotals.paidCount || tableTotals.pendingCount
                  ? ` · ${tableTotals.paidCount} paid · ${tableTotals.pendingCount} pending`
                  : null}
                {!finalized ? " · Tax and net pending finance finalize" : null}
              </Typography>
            </Box>
            {loading ? (
              <Box sx={{ p: 2 }}>
                <Typography color="text.secondary">Loading…</Typography>
              </Box>
            ) : (
              <TableContainer sx={{ overflowX: "auto" }}>
                <Table size="small" sx={{ minWidth: 1400 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Employee</TableCell>
                      <TableCell align="right">Reg hrs</TableCell>
                      <TableCell align="right">OT hrs</TableCell>
                      <TableCell align="right">Reg rate</TableCell>
                      <TableCell align="right">OT rate</TableCell>
                      <TableCell align="right">Gross</TableCell>
                      {DEDUCTION_COLUMNS.map((col) => (
                        <TableCell key={col.key} align="right">
                          {col.label}
                        </TableCell>
                      ))}
                      <TableCell align="right">Total tax</TableCell>
                      <TableCell align="right">Net</TableCell>
                      <TableCell>Status</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(detail.lines || []).map((ln) => {
                      const lineFinalized = isPayoutDetailsFinalized(ln);
                      const { regRate, otRate } = computeLineRates(ln);
                      return (
                        <TableRow key={ln.id} hover>
                          <TableCell>{ln.worker_name_snapshot}</TableCell>
                          <TableCell align="right">{num(ln.approved_hours).toFixed(2)}</TableCell>
                          <TableCell align="right">{num(ln.ot_hours).toFixed(2)}</TableCell>
                          <TableCell align="right">{formatRate(regRate)}</TableCell>
                          <TableCell align="right">{formatRate(otRate)}</TableCell>
                          <TableCell align="right">{formatMoney(lineGross(ln))}</TableCell>
                          {DEDUCTION_COLUMNS.map((col) => (
                            <TableCell key={col.key} align="right">
                              {formatMoneyOrPending(lineFinalized, deductionAmount(ln, col))}
                            </TableCell>
                          ))}
                          <TableCell align="right">
                            <TaxCell
                              line={ln}
                              workerName={ln.worker_name_snapshot}
                              onOpen={(line, workerName) =>
                                setTaxDialog({ open: true, line, workerName })
                              }
                            />
                          </TableCell>
                          <TableCell align="right">
                            {lineFinalized ? formatNetPaidDisplay(ln) : "—"}
                          </TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={ln.payment_status_label || ln.payment_status || "Pending"}
                              color={paymentStatusColor(ln.payment_status)}
                              variant="outlined"
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                    {(detail.lines || []).length > 0 ? (
                      <TableRow>
                        <TableCell sx={{ fontWeight: 700 }}>Totals</TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.regHours.toFixed(2)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.otHours.toFixed(2)}
                        </TableCell>
                        <TableCell />
                        <TableCell />
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatMoney(tableTotals.gross)}
                        </TableCell>
                        {DEDUCTION_COLUMNS.map((col) => (
                          <TableCell key={col.key} align="right" sx={{ fontWeight: 700 }}>
                            {tableTotals.hasFinalizedLines
                              ? formatMoney(tableTotals.deductions[col.key])
                              : "—"}
                          </TableCell>
                        ))}
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.hasFinalizedLines ? formatMoney(tableTotals.totalTax) : "—"}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.hasFinalizedLines ? formatMoney(tableTotals.net) : "—"}
                        </TableCell>
                        <TableCell sx={{ fontWeight: 700 }}>
                          {tableTotals.paidCount} paid · {tableTotals.pendingCount} pending
                        </TableCell>
                      </TableRow>
                    ) : null}
                    {(detail.lines || []).length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={colSpan}>
                          <Typography variant="body2" color="text.secondary">No employees</Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Paper>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {canConfirmProcessed ? (
              <Button
                variant="contained"
                size="large"
                disabled={submitting}
                onClick={confirmPayrollProcessed}
                startIcon={<CheckCircleOutlineIcon />}
                sx={{ bgcolor: VEEWASH_BRAND.primary, px: 3 }}
              >
                Confirm payroll processed
              </Button>
            ) : null}
            {financePending ? (
              <Chip
                icon={<HourglassEmptyIcon />}
                label="Awaiting finance admin — enter taxes on Finalize Payroll"
                color="info"
                variant="outlined"
              />
            ) : null}
            {finalized ? (
              <Chip
                icon={<CheckCircleOutlineIcon />}
                label="Finance finalized — paystubs on Finalize Payroll"
                color="success"
                variant="outlined"
              />
            ) : null}
          </Stack>
        </>
      ) : null}

      <TaxWithheldBreakdownDialog
        open={taxDialog.open}
        onClose={() => setTaxDialog({ open: false, line: null, workerName: "" })}
        line={taxDialog.line}
        workerName={taxDialog.workerName}
      />
    </Stack>
  );
}
