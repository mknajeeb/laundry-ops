import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
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
  Tooltip,
  Typography,
} from "@mui/material";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import PayPeriodSelect from "./PayPeriodSelect";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import { getPayoutBatchDetails, getPayoutBatches } from "../api";
import {
  accountantPeriodStatusColor,
  accountantPeriodStatusLabel,
  pickDefaultAccountantBatch,
} from "../payroll/accountantBatchPick";
import { resolveAccountantBatchById } from "../payroll/payPeriodOptions";
import {
  PAYROLL_REGISTER_DEDUCTION_COLUMNS,
  sumEmployeeRegisterTaxes,
} from "../payroll/payrollRegisterTaxFields";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import {
  OT_PREMIUM_TOOLTIP,
  computeEarningsBreakdown,
} from "../payroll/payrollOtDisplay";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEDUCTION_COLUMNS = PAYROLL_REGISTER_DEDUCTION_COLUMNS;

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function lineGross(ln) {
  return num(ln.gross_amount || ln.total_amount || ln.gross_wages);
}

function deductionAmount(ln, col) {
  const ded = ln.payout_details?.employee_deductions || {};
  return num(ded[col.key]);
}

function lineTotalTax(ln) {
  if (ln.tax_withheld != null && ln.tax_withheld !== "") return num(ln.tax_withheld);
  const ded = ln.payout_details?.employee_deductions || {};
  return sumEmployeeRegisterTaxes(ded);
}

function formatMoney(v) {
  return `$${num(v).toFixed(2)}`;
}

function formatHours(v) {
  const n = num(v);
  return n > 0 ? n.toFixed(2) : "";
}

function formatMoneyOrBlank(finalized, v) {
  if (!finalized) return "";
  return formatMoney(v);
}

function paymentStatusColor(status) {
  if (status === "paid") return "success";
  if (status === "approved_unpaid") return "warning";
  return "default";
}

function OtPremiumHeader() {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end">
      <span>OT Premium</span>
      <Tooltip title={OT_PREMIUM_TOOLTIP}>
        <InfoOutlinedIcon sx={{ fontSize: 14, color: "text.secondary" }} />
      </Tooltip>
    </Stack>
  );
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
  const label = formatTaxWithheldDisplay(line, { pendingLabel: "" });
  const clickable = finalized && label && (hasTaxWithheldBreakdown(line) || label !== "Pending");
  if (!clickable) {
    return <Typography variant="body2">{label || ""}</Typography>;
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
  const [selectedBatchId, setSelectedBatchId] = useState(null);
  const [batches, setBatches] = useState([]);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const autoPickedRef = useRef(false);

  const loadBatches = useCallback(async () => {
    try {
      // Server scopes accountant users to send_to_accountant=Yes batches.
      const res = await getPayoutBatches({});
      setBatches(res.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load batches");
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  const selectedBatch = useMemo(
    () => resolveAccountantBatchById(batches, selectedBatchId),
    [batches, selectedBatchId],
  );

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
    loadDetail(selectedBatchId);
  }, [selectedBatchId, loadDetail]);

  useEffect(() => {
    if (!batches.length || autoPickedRef.current) return;
    const pick = pickDefaultAccountantBatch(batches);
    if (pick?.id != null) setSelectedBatchId(pick.id);
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
      baseEarnings: 0,
      otPremium: 0,
      otherEarnings: 0,
      gross: 0,
      deductions: Object.fromEntries(DEDUCTION_COLUMNS.map((c) => [c.key, 0])),
      totalTax: 0,
      net: 0,
      hasFinalizedLines: false,
    };
    for (const ln of lines) {
      const earn = computeEarningsBreakdown(ln);
      totals.regHours += earn.regular_hours;
      totals.otHours += earn.ot_hours;
      totals.baseEarnings += earn.base_earnings;
      totals.otPremium += earn.ot_premium;
      totals.otherEarnings += earn.other_earnings;
      totals.gross += earn.gross_pay || lineGross(ln);
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

  const periodStatus = accountantPeriodStatusLabel(selectedBatch || detail);
  const status = String(detail?.status || "");
  const workflow = detail?.payout_workflow || {};
  const finalized = workflow.payout_details_finalized;
  const financePending = ["sent_to_accountant", "accountant_reviewed", "approved_for_payment"].includes(status) && !finalized;

  const colSpan = 7 + DEDUCTION_COLUMNS.length + 3;

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
              color={accountantPeriodStatusColor(selectedBatch || detail)}
            />
          ) : null}
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Batches routed to accountant (Send to Accountant = Yes). Finance enters deductions,
          updates net pay, and prints or emails paystubs on the Finalize Payroll tab — no
          accountant acknowledgement is required to unblock Finance.
        </Typography>
        {batches.length ? (
          <PayPeriodSelect
            batches={batches}
            batchId={selectedBatchId}
            start={selectedBatch?.pay_period_start}
            end={selectedBatch?.pay_period_end}
            batchStatusLabel={accountantPeriodStatusLabel}
            batchOnly
            minWidth={420}
            onChange={({ batchId }) => {
              if (batchId == null || batchId === "") return;
              setSelectedBatchId(batchId);
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
          <PayrollBatchSummaryCard batch={detail} compact moneyEmpty="" />

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
              Workflow
            </Typography>
            <Stack spacing={1.5}>
              <WorkflowStep
                active={false}
                done={Boolean(detail?.sent_to_accountant_at) || status !== "hours_reviewed"}
                label="Batch released to accountant"
                description="Manager sent this batch. Review documents as needed — no action required here to unblock Finance."
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
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                Regular/Base + OT Premium + Other Earnings = Gross Pay. {OT_PREMIUM_TOOLTIP}
              </Typography>
            </Box>
            {loading ? (
              <Box sx={{ p: 2 }}>
                <Typography color="text.secondary">Loading…</Typography>
              </Box>
            ) : (
              <TableContainer sx={{ overflowX: "auto" }}>
                <Table size="small" sx={{ minWidth: 1500 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Employee</TableCell>
                      <TableCell align="right">Reg hrs</TableCell>
                      <TableCell align="right">OT Hours</TableCell>
                      <TableCell align="right">Regular/Base Earnings</TableCell>
                      <TableCell align="right">
                        <OtPremiumHeader />
                      </TableCell>
                      <TableCell align="right">Other Earnings</TableCell>
                      <TableCell align="right">Gross Pay</TableCell>
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
                      const earn = computeEarningsBreakdown(ln);
                      return (
                        <TableRow key={ln.id} hover>
                          <TableCell>{ln.worker_name_snapshot}</TableCell>
                          <TableCell align="right">{formatHours(earn.regular_hours)}</TableCell>
                          <TableCell align="right">{formatHours(earn.ot_hours)}</TableCell>
                          <TableCell align="right">{formatMoney(earn.base_earnings)}</TableCell>
                          <TableCell align="right">
                            {earn.ot_hours > 0 ? formatMoney(earn.ot_premium) : ""}
                          </TableCell>
                          <TableCell align="right">
                            {earn.other_earnings ? formatMoney(earn.other_earnings) : ""}
                          </TableCell>
                          <TableCell align="right">{formatMoney(earn.gross_pay)}</TableCell>
                          {DEDUCTION_COLUMNS.map((col) => (
                            <TableCell key={col.key} align="right">
                              {formatMoneyOrBlank(lineFinalized, deductionAmount(ln, col))}
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
                            {lineFinalized ? formatNetPaidDisplay(ln, { pendingLabel: "" }) : ""}
                          </TableCell>
                          <TableCell>
                            {ln.payment_status_label || ln.payment_status ? (
                              <Chip
                                size="small"
                                label={ln.payment_status_label || ln.payment_status}
                                color={paymentStatusColor(ln.payment_status)}
                                variant="outlined"
                              />
                            ) : null}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                    {(detail.lines || []).length > 0 ? (
                      <TableRow>
                        <TableCell sx={{ fontWeight: 700 }}>Totals</TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatHours(tableTotals.regHours)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatHours(tableTotals.otHours)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatMoney(tableTotals.baseEarnings)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatMoney(tableTotals.otPremium)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatMoney(tableTotals.otherEarnings)}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {formatMoney(tableTotals.gross)}
                        </TableCell>
                        {DEDUCTION_COLUMNS.map((col) => (
                          <TableCell key={col.key} align="right" sx={{ fontWeight: 700 }}>
                            {tableTotals.hasFinalizedLines
                              ? formatMoney(tableTotals.deductions[col.key])
                              : ""}
                          </TableCell>
                        ))}
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.hasFinalizedLines ? formatMoney(tableTotals.totalTax) : ""}
                        </TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {tableTotals.hasFinalizedLines ? formatMoney(tableTotals.net) : ""}
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
