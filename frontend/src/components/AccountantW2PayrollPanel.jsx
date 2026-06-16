import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Chip,
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
import PayPeriodSelect from "./PayPeriodSelect";
import { getPayrollPeriodSettings, getPayoutBatch, getPayoutBatches } from "../api";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import {
  ACCOUNTANT_BATCH_READY_MESSAGE,
  PAYROLL_ESTIMATE_PURPOSE,
} from "../payroll/payrollTaxMessages";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEFAULT_OT_MULTIPLIER = 1.5;

const READY_STATUSES = [
  "sent_to_accountant",
  "accountant_reviewed",
  "approved_for_payment",
  "paid",
  "closed",
];

function lineStatusLabel(st) {
  if (st === "pending" || st === "pending_approval") return "Pending approval";
  if (st === "approved") return "Approved";
  return st || "—";
}

function lineStatusColor(st) {
  if (st === "pending" || st === "pending_approval") return "warning";
  if (st === "approved") return "success";
  return "default";
}

function batchStatusLabel(st) {
  const map = {
    draft: "Draft",
    hours_reviewed: "Awaiting confirm",
    sent_to_accountant: "Ready for you",
    accountant_reviewed: "Reviewed",
    approved_for_payment: "Approved",
    paid: "Paid",
    closed: "Closed",
  };
  return map[st] || st || "—";
}

function computeLinePay(ln, otMultiplier = DEFAULT_OT_MULTIPLIER) {
  const regHours = Number(ln.approved_hours || 0);
  const otHours = Number(ln.ot_hours || 0);
  const rate = Number(ln.rate || 0);
  const regularAmount = regHours * rate;
  const otRate = otHours > 0 && rate > 0 ? rate * otMultiplier : 0;
  const otAmount = otHours * otRate;
  const gross = Number(ln.gross_wages || ln.gross_amount || 0);
  return {
    totalHours: regHours + otHours,
    regularRate: rate,
    regularAmount,
    otRate,
    otAmount,
    gross,
  };
}

export default function AccountantW2PayrollPanel() {
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [periodExpanded, setPeriodExpanded] = useState(false);
  const [batches, setBatches] = useState([]);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const autoPickedRef = useRef(false);

  useEffect(() => {
    getPayrollPeriodSettings()
      .then((res) => {
        const ws = Number(res.data?.week_starts_on ?? 0);
        const week = Number.isFinite(ws) ? ws : 0;
        setWeekStartsOn(week);
        const r = defaultPayPeriodRange(week);
        setPeriodStart(r.start);
        setPeriodEnd(r.end);
      })
      .catch(() => {
        const r = defaultPayPeriodRange(0);
        setPeriodStart(r.start);
        setPeriodEnd(r.end);
      });
  }, []);

  const loadBatches = useCallback(async () => {
    setError("");
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
    return (
      batches.find(
        (b) =>
          normPayPeriodYmd(b.pay_period_start) === ps &&
          normPayPeriodYmd(b.pay_period_end) === pe,
      ) || null
    );
  }, [batches, periodStart, periodEnd]);

  /** After batches load, jump to latest ready (or any) batch if current week has none. */
  useEffect(() => {
    if (!batches.length || autoPickedRef.current) return;
    const ps = normPayPeriodYmd(periodStart);
    const pe = normPayPeriodYmd(periodEnd);
    const hasBatch = batches.some(
      (b) =>
        normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
    );
    if (hasBatch) {
      autoPickedRef.current = true;
      return;
    }
    const ready = batches.find((b) => READY_STATUSES.includes(b.status));
    const pick = ready || batches[0];
    if (pick) {
      setPeriodStart(normPayPeriodYmd(pick.pay_period_start));
      setPeriodEnd(normPayPeriodYmd(pick.pay_period_end));
    }
    autoPickedRef.current = true;
  }, [batches, periodStart, periodEnd]);

  const loadBatchDetail = useCallback(async (batchId) => {
    if (!batchId) {
      setBatch(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await getPayoutBatch(batchId);
      setBatch(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load batch");
      setBatch(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatchDetail(periodBatch?.id);
  }, [periodBatch?.id, loadBatchDetail]);

  const showReadyMessage = batch && READY_STATUSES.includes(batch.status);
  const pendingLineCount =
    batch?.lines?.filter((ln) =>
      ln.line_status === "pending_approval" || ln.line_status === "pending",
    ).length || 0;

  const totals = useMemo(() => {
    const lines = batch?.lines || [];
    let hours = 0;
    let regular = 0;
    let ot = 0;
    let gross = 0;
    for (const ln of lines) {
      const p = computeLinePay(ln);
      hours += p.totalHours;
      regular += p.regularAmount;
      ot += p.otAmount;
      gross += p.gross;
    }
    return { hours, regular, ot, gross };
  }, [batch]);

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 0.5 }}>W-2 payroll by pay period</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Payroll approves time, builds a W-2 payout batch for the same week, then confirms it is
          ready. You will see a green notice when you can proceed.
        </Typography>
        <Alert severity="info" variant="outlined" sx={{ mb: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
            Payroll workflow (admin)
          </Typography>
          <Typography variant="body2" component="ol" sx={{ pl: 2, m: 0 }}>
            <li>Time Records — approve hours for the pay period</li>
            <li>Payout Batches — create/open <strong>W-2</strong> batch for that week (syncs approved time)</li>
            <li>Mark hours reviewed → <strong>Confirm batch ready for accountant</strong></li>
          </Typography>
        </Alert>
        <PayPeriodSelect
          weekStartsOn={weekStartsOn}
          batches={batches}
          start={periodStart}
          end={periodEnd}
          expanded={periodExpanded}
          onExpandedChange={setPeriodExpanded}
          batchStatusLabel={batchStatusLabel}
          onChange={({ start, end }) => {
            setPeriodStart(start);
            setPeriodEnd(end);
          }}
        />
      </Paper>

      {showReadyMessage ? (
        <Alert severity="success" sx={{ borderColor: VEEWASH_BRAND.teal }}>
          {batch.accountant_ready_message || ACCOUNTANT_BATCH_READY_MESSAGE}
        </Alert>
      ) : batch?.status === "hours_reviewed" ? (
        <Alert severity="info">
          Hours reviewed — waiting for payroll to confirm this batch is ready for your review.
        </Alert>
      ) : batch?.status === "draft" ? (
        <Alert severity="warning">
          Batch is still in draft. Payroll must review hours and confirm ready before you process
          payroll.
        </Alert>
      ) : null}

      {!periodBatch ? (
        <Alert severity="info">
          No W-2 payout batch for this pay period yet. Ask payroll to create one under{" "}
          <strong>Payout Batches</strong> (W-2 category) after approving time records.
        </Alert>
      ) : null}

      {batch ? (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mb: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              {batch.batch_name}
            </Typography>
            <Chip size="small" label={batchStatusLabel(batch.status)} />
            {pendingLineCount > 0 ? (
              <Chip
                size="small"
                color="warning"
                label={`${pendingLineCount} line(s) pending approval`}
              />
            ) : (
              <Chip size="small" color="success" label="All lines approved" />
            )}
          </Stack>
          <Alert severity="info" sx={{ mb: 2 }}>
            {PAYROLL_ESTIMATE_PURPOSE}
          </Alert>

          {loading ? (
            <Typography color="text.secondary">Loading batch lines…</Typography>
          ) : (
            <TableContainer>
              <Table size="small" sx={{ minWidth: 960 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Employee</TableCell>
                    <TableCell align="right">Hours</TableCell>
                    <TableCell align="right">Regular rate</TableCell>
                    <TableCell align="right">Regular amount</TableCell>
                    <TableCell align="right">OT rate</TableCell>
                    <TableCell align="right">OT amount</TableCell>
                    <TableCell align="right">W-2 gross</TableCell>
                    <TableCell>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(batch.lines || []).map((ln) => {
                    const pay = computeLinePay(ln);
                    return (
                      <TableRow key={ln.id} hover>
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                        <TableCell align="right">{pay.totalHours.toFixed(2)}</TableCell>
                        <TableCell align="right">
                          {pay.regularRate > 0 ? `$${pay.regularRate.toFixed(2)}` : "—"}
                        </TableCell>
                        <TableCell align="right">${pay.regularAmount.toFixed(2)}</TableCell>
                        <TableCell align="right">
                          {pay.otRate > 0 ? `$${pay.otRate.toFixed(2)}` : "—"}
                        </TableCell>
                        <TableCell align="right">${pay.otAmount.toFixed(2)}</TableCell>
                        <TableCell align="right">${pay.gross.toFixed(2)}</TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={lineStatusColor(ln.line_status)}
                            label={lineStatusLabel(ln.line_status)}
                            variant="outlined"
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {(batch.lines || []).length > 0 ? (
                    <TableRow>
                      <TableCell sx={{ fontWeight: 700 }}>Totals</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        {totals.hours.toFixed(2)}
                      </TableCell>
                      <TableCell />
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.regular.toFixed(2)}
                      </TableCell>
                      <TableCell />
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.ot.toFixed(2)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.gross.toFixed(2)}
                      </TableCell>
                      <TableCell />
                    </TableRow>
                  ) : null}
                  {!batch.lines?.length ? (
                    <TableRow>
                      <TableCell colSpan={8}>
                        <Typography color="text.secondary">
                          No lines yet — payroll must approve time and open/sync the W-2 batch for
                          this period.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      ) : null}
    </Stack>
  );
}
