import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Typography,
} from "@mui/material";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import PayPeriodSelect from "./PayPeriodSelect";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import {
  confirmPayoutPayment,
  getPayoutBatchDetails,
  getPayoutBatches,
  processPayoutBatch,
} from "../api";
import {
  accountantPeriodStatusColor,
  accountantPeriodStatusLabel,
  pickDefaultAccountantBatch,
} from "../payroll/accountantBatchPick";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function lineGross(ln) {
  return num(ln.gross_amount || ln.total_amount || ln.gross_wages);
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

  const totals = useMemo(() => {
    const lines = detail?.lines || [];
    let gross = 0;
    for (const ln of lines) gross += lineGross(ln);
    return { gross, count: lines.length };
  }, [detail]);

  const periodStatus = accountantPeriodStatusLabel(periodBatch || detail);
  const status = String(detail?.status || "");
  const workflow = detail?.payout_workflow || {};
  const accountantConfirmed = workflow.accountant_payment_confirmed;
  const finalized = workflow.payout_details_finalized;

  const canConfirmProcessed = detail?.can_process_as_accountant && status === "sent_to_accountant";
  const awaitingPaymentConfirm =
    status === "approved_for_payment" && finalized && workflow.awaiting_accountant_confirmation;
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

  const markPaymentInitiated = async () => {
    if (!detail?.id) return;
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const res = await confirmPayoutPayment(detail.id);
      setDetail(res.data);
      setInfo("Payment confirmed — recorded for this pay period.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not record payment");
    } finally {
      setSubmitting(false);
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
          Confirm when payroll has been processed externally. Tax details and paystubs are entered
          by finance admin on the Finalize Payroll tab.
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
                description="Federal, state, and payment details on Finalize Payroll tab."
              />
              <WorkflowStep
                active={awaitingPaymentConfirm}
                done={accountantConfirmed}
                label="Confirm payment initiated"
                description="After finance finalizes, confirm employees were paid."
              />
            </Stack>
          </Paper>

          <Paper variant="outlined">
            <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider" }}>
              <Typography variant="subtitle2" fontWeight={700}>
                Employees in this batch
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {totals.count} employee{totals.count === 1 ? "" : "s"} · Gross ${totals.gross.toFixed(2)}
              </Typography>
            </Box>
            {loading ? (
              <Box sx={{ p: 2 }}>
                <Typography color="text.secondary">Loading…</Typography>
              </Box>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Employee</TableCell>
                    <TableCell align="right">Gross</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(detail.lines || []).map((ln) => (
                    <TableRow key={ln.id}>
                      <TableCell>{ln.worker_name_snapshot}</TableCell>
                      <TableCell align="right">${lineGross(ln).toFixed(2)}</TableCell>
                    </TableRow>
                  ))}
                  {(detail.lines || []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={2}>
                        <Typography variant="body2" color="text.secondary">No employees</Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
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
            {awaitingPaymentConfirm ? (
              <Button
                variant="contained"
                color="success"
                size="large"
                disabled={submitting}
                onClick={markPaymentInitiated}
                startIcon={<CheckCircleOutlineIcon />}
              >
                Confirm payment initiated
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
            {accountantConfirmed && finalized ? (
              <Chip
                icon={<CheckCircleOutlineIcon />}
                label="Payment confirmed for this period"
                color="success"
                variant="outlined"
              />
            ) : null}
          </Stack>
        </>
      ) : null}
    </Stack>
  );
}
