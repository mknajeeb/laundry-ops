import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
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
import {
  getPayrollPeriodSettings,
  getPayoutBatch,
  getPayoutBatches,
  processPayoutBatch,
} from "../api";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const DEFAULT_OT_MULTIPLIER = 1.5;

function periodStatusLabel(batch) {
  const st = batch?.accountant_processing_status;
  if (st === "PENDING" || st === "PROCESSED") return st;
  if (batch?.status === "sent_to_accountant") return "PENDING";
  return "PROCESSED";
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
  const [processing, setProcessing] = useState(false);
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
    const pending = batches.find((b) => b.accountant_processing_status === "PENDING");
    const pick = pending || batches[0];
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

  const processingStatus = batch?.accountant_processing_status;
  const canProcess = batch?.can_process_as_accountant;

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

  const handleProcess = async () => {
    if (!batch?.id) return;
    setProcessing(true);
    setError("");
    try {
      const res = await processPayoutBatch(batch.id);
      setBatch(res.data);
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not process batch");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          flexWrap="wrap"
          gap={1}
          sx={{ mb: 2 }}
        >
          <Typography variant="h6" sx={{ color: VEEWASH_BRAND.primaryDark }}>
            W-2 Payroll
          </Typography>
          {processingStatus ? (
            <Chip
              size="small"
              label={processingStatus}
              color={processingStatus === "PROCESSED" ? "success" : "warning"}
            />
          ) : null}
        </Stack>

        {batches.length ? (
          <PayPeriodSelect
            weekStartsOn={weekStartsOn}
            batches={batches}
            start={periodStart}
            end={periodEnd}
            expanded={periodExpanded}
            onExpandedChange={setPeriodExpanded}
            batchStatusLabel={periodStatusLabel}
            batchOnly
            onChange={({ start, end }) => {
              setPeriodStart(start);
              setPeriodEnd(end);
            }}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            No payroll batches are available for review.
          </Typography>
        )}

        {canProcess ? (
          <Button
            variant="contained"
            sx={{ mt: 2, bgcolor: VEEWASH_BRAND.primary }}
            onClick={handleProcess}
            disabled={processing || loading}
          >
            Process batch
          </Button>
        ) : null}
      </Paper>

      {batch ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2 }}>
            {batch.pay_period_start} – {batch.pay_period_end}
            {batch.batch_name ? ` · ${batch.batch_name}` : ""}
          </Typography>

          {loading ? (
            <Typography color="text.secondary">Loading…</Typography>
          ) : (
            <TableContainer>
              <Table size="small" sx={{ minWidth: 720 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Employee</TableCell>
                    <TableCell align="right">Hours</TableCell>
                    <TableCell align="right">Regular rate</TableCell>
                    <TableCell align="right">Regular amount</TableCell>
                    <TableCell align="right">OT rate</TableCell>
                    <TableCell align="right">OT amount</TableCell>
                    <TableCell align="right">Gross</TableCell>
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
                    </TableRow>
                  ) : null}
                  {!batch.lines?.length ? (
                    <TableRow>
                      <TableCell colSpan={7}>
                        <Typography color="text.secondary">No employee lines in this batch.</Typography>
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
