import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Chip,
  FormControl,
  InputLabel,
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
  Typography,
} from "@mui/material";
import { getPayrollPeriodSettings, getPayoutBatch, getPayoutBatches } from "../api";
import { buildPayPeriodOptions, findPayPeriodOption } from "../payroll/payPeriodOptions";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import {
  ACCOUNTANT_BATCH_READY_MESSAGE,
  PAYROLL_ESTIMATE_PURPOSE,
} from "../payroll/payrollTaxMessages";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEFAULT_OT_MULTIPLIER = 1.5;

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

function batchStatusLabel(st) {
  const map = {
    draft: "Draft",
    hours_reviewed: "Hours reviewed — awaiting payroll confirmation",
    sent_to_accountant: "Ready for accountant",
    accountant_reviewed: "Accountant reviewed",
    approved_for_payment: "Approved for payment",
    paid: "Paid",
    closed: "Closed",
  };
  return map[st] || st || "—";
}

export default function AccountantW2PayrollPanel() {
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [batches, setBatches] = useState([]);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const periodOptions = useMemo(
    () => buildPayPeriodOptions(weekStartsOn),
    [weekStartsOn],
  );

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
    return (
      batches.find(
        (b) => b.pay_period_start === periodStart && b.pay_period_end === periodEnd,
      ) || null
    );
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

  const onPeriodSelect = (key) => {
    const opt = periodOptions.find((o) => o.key === key);
    if (!opt) return;
    setPeriodStart(opt.start);
    setPeriodEnd(opt.end);
  };

  const selectedKey =
    periodStart && periodEnd ? `${periodStart}|${periodEnd}` : "";
  const selectedLabel = findPayPeriodOption(periodOptions, periodStart, periodEnd)?.label;

  const readyStatuses = ["sent_to_accountant", "accountant_reviewed", "approved_for_payment", "paid"];
  const showReadyMessage = batch && readyStatuses.includes(batch.status);
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
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Review hours, rates, and gross wages for W-2 employees. Lines still awaiting approval are
          marked clearly. When payroll confirms the batch is ready, you will see a green notice here.
        </Typography>
        <FormControl size="small" sx={{ minWidth: 280 }}>
          <InputLabel>Pay period</InputLabel>
          <Select
            label="Pay period"
            value={selectedKey}
            onChange={(e) => onPeriodSelect(e.target.value)}
          >
            {periodOptions.map((o) => (
              <MenuItem key={o.key} value={o.key}>
                {o.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {selectedLabel ? (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            {periodStart} – {periodEnd}
          </Typography>
        ) : null}
      </Paper>

      {showReadyMessage ? (
        <Alert severity="success" sx={{ borderColor: VEEWASH_BRAND.teal }}>
          {batch.accountant_ready_message || ACCOUNTANT_BATCH_READY_MESSAGE}
        </Alert>
      ) : batch?.status === "hours_reviewed" ? (
        <Alert severity="info">
          Hours have been reviewed. Waiting for payroll to confirm this batch is ready for your
          review.
        </Alert>
      ) : batch?.status === "draft" ? (
        <Alert severity="warning">
          This pay period batch is still in draft. Some lines may show pending approval until payroll
          finishes review.
        </Alert>
      ) : null}

      {!periodBatch ? (
        <Alert severity="info">
          No W-2 payout batch exists for {selectedLabel || "this pay period"} yet. Payroll will create
          one on Payout Batches when hours are approved.
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
                        <Typography color="text.secondary">No lines in this batch yet.</Typography>
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
