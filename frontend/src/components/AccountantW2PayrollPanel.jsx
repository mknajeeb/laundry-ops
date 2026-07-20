import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  Link,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from "@mui/material";
import PayPeriodSelect from "./PayPeriodSelect";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";
import {
  getPayrollPeriodSettings,
  getPayoutBatch,
  getPayoutBatches,
  processPayoutBatch,
} from "../api";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  hasTaxWithheldBreakdown,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import { DEFAULT_OT_MULTIPLIER, computeEarningsBreakdown } from "../payroll/payrollOtDisplay";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const ACCOUNTANT_BATCH_STATUSES = new Set([
  "sent_to_accountant",
  "accountant_reviewed",
  "approved_for_payment",
  "paid",
  "closed",
]);

function periodStatusLabel(batch) {
  if (!batch || typeof batch !== "object") return null;
  const st = batch.accountant_processing_status;
  if (st === "PENDING" || st === "PROCESSED") return st;
  if (batch.status === "sent_to_accountant") return "PENDING";
  if (
    batch.status === "accountant_reviewed" ||
    batch.status === "approved_for_payment" ||
    batch.status === "paid" ||
    batch.status === "closed"
  ) {
    return "PROCESSED";
  }
  return null;
}

function computeLinePay(ln, otMultiplier = DEFAULT_OT_MULTIPLIER) {
  const earn = computeEarningsBreakdown(ln, { multiplier: otMultiplier });
  return {
    totalHours: earn.regular_hours + earn.ot_hours,
    regularRate: earn.regular_rate,
    regularAmount: earn.base_earnings,
    otRate: earn.ot_rate,
    otAmount: earn.ot_premium,
    otherEarnings: earn.other_earnings,
    gross: earn.gross_pay,
  };
}

function TaxWithheldCell({ line, workerName, onOpen }) {
  const label = formatTaxWithheldDisplay(line);
  const finalized = isPayoutDetailsFinalized(line);
  const clickable = finalized && (hasTaxWithheldBreakdown(line) || label !== "Pending");
  if (!clickable) {
    return <Typography variant="body2">{label}</Typography>;
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

export default function AccountantW2PayrollPanel() {
  const [viewMode, setViewMode] = useState(0);
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [periodExpanded, setPeriodExpanded] = useState(false);
  const [batches, setBatches] = useState([]);
  const [batch, setBatch] = useState(null);
  const [employeeRows, setEmployeeRows] = useState([]);
  const [employeeLoading, setEmployeeLoading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const autoPickedRef = useRef(false);

  const openTaxDialog = (line, workerName) => {
    setTaxDialog({ open: true, line, workerName: workerName || line?.worker_name_snapshot || "" });
  };

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

  const loadEmployeeRows = useCallback(async () => {
    setEmployeeLoading(true);
    setError("");
    try {
      const res = await getPayoutBatches({ worker_category: "w2" });
      const list = (res.data?.items || []).filter((b) => ACCOUNTANT_BATCH_STATUSES.has(b.status));
      const details = await Promise.all(
        list.map(async (b) => {
          try {
            const r = await getPayoutBatch(b.id);
            return r.data;
          } catch {
            return null;
          }
        }),
      );
      const rows = [];
      for (const b of details.filter(Boolean)) {
        for (const ln of b.lines || []) {
          rows.push({
            ...ln,
            batch_id: b.id,
            batch_name: b.batch_name,
            batch_number: b.id,
            pay_period_start: b.pay_period_start,
            pay_period_end: b.pay_period_end,
            payout_details_finalized: Boolean(b.payout_details_finalized_at),
          });
        }
      }
      rows.sort((a, b) => {
        const pe = String(b.pay_period_end || "").localeCompare(String(a.pay_period_end || ""));
        if (pe !== 0) return pe;
        return String(a.worker_name_snapshot || "").localeCompare(String(b.worker_name_snapshot || ""));
      });
      setEmployeeRows(rows);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load employee payouts");
      setEmployeeRows([]);
    } finally {
      setEmployeeLoading(false);
    }
  }, []);

  useEffect(() => {
    if (viewMode === 1) loadEmployeeRows();
  }, [viewMode, loadEmployeeRows]);

  const processingStatus = periodStatusLabel(batch || periodBatch);
  const canProcess = Boolean(batch?.can_process_as_accountant);

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
      await loadBatchDetail(batch.id);
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

      <Tabs value={viewMode} onChange={(_, v) => setViewMode(v)} sx={{ mb: 1 }}>
        <Tab label="Batch-wise" />
        <Tab label="Employee-wise" />
      </Tabs>

      {viewMode === 0 ? (
        <>
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
                  <Table size="small" sx={{ minWidth: 960 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Employee</TableCell>
                        <TableCell align="right">Hours</TableCell>
                        <TableCell align="right">Regular rate</TableCell>
                        <TableCell align="right">Regular/Base Earnings</TableCell>
                        <TableCell align="right">OT Hours</TableCell>
                        <TableCell align="right">OT Premium</TableCell>
                        <TableCell align="right">Gross Pay</TableCell>
                        <TableCell align="right">Net paid</TableCell>
                        <TableCell align="right">Tax withheld</TableCell>
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
                              {Number(ln.ot_hours || 0) > 0
                                ? Number(ln.ot_hours).toFixed(2)
                                : "—"}
                            </TableCell>
                            <TableCell align="right">
                              {pay.otAmount > 0 ? `$${pay.otAmount.toFixed(2)}` : "—"}
                            </TableCell>
                            <TableCell align="right">${pay.gross.toFixed(2)}</TableCell>
                            <TableCell align="right">{formatNetPaidDisplay(ln)}</TableCell>
                            <TableCell align="right">
                              <TaxWithheldCell
                                line={ln}
                                workerName={ln.worker_name_snapshot}
                                onOpen={openTaxDialog}
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
                          <TableCell colSpan={2} />
                        </TableRow>
                      ) : null}
                      {!batch.lines?.length ? (
                        <TableRow>
                          <TableCell colSpan={9}>
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
        </>
      ) : (
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6" sx={{ color: VEEWASH_BRAND.primaryDark, mb: 2 }}>
            Employee payout history
          </Typography>
          {employeeLoading ? (
            <Typography color="text.secondary">Loading…</Typography>
          ) : (
            <TableContainer>
              <Table size="small" sx={{ minWidth: 1100 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Employee</TableCell>
                    <TableCell>Employee ID</TableCell>
                    <TableCell>Pay period</TableCell>
                    <TableCell>Batch #</TableCell>
                    <TableCell align="right">Approved hrs</TableCell>
                    <TableCell align="right">Gross pay</TableCell>
                    <TableCell>Payment status</TableCell>
                    <TableCell>Payment date</TableCell>
                    <TableCell>Payment method</TableCell>
                    <TableCell align="right">Net paid</TableCell>
                    <TableCell align="right">Tax withheld</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {employeeRows.map((ln) => {
                    const pay = computeLinePay(ln);
                    return (
                      <TableRow key={`${ln.batch_id}-${ln.id}`} hover>
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                        <TableCell>{ln.employee_id || "—"}</TableCell>
                        <TableCell>
                          {ln.pay_period_start} – {ln.pay_period_end}
                        </TableCell>
                        <TableCell>{ln.batch_number || ln.batch_id}</TableCell>
                        <TableCell align="right">{pay.totalHours.toFixed(2)}</TableCell>
                        <TableCell align="right">${pay.gross.toFixed(2)}</TableCell>
                        <TableCell>{ln.payment_status_label || ln.payment_status || "—"}</TableCell>
                        <TableCell>
                          {isPayoutDetailsFinalized(ln) && ln.payment_date ? ln.payment_date : "—"}
                        </TableCell>
                        <TableCell>
                          {isPayoutDetailsFinalized(ln) && ln.payment_method_label
                            ? ln.payment_method_label
                            : "—"}
                        </TableCell>
                        <TableCell align="right">{formatNetPaidDisplay(ln)}</TableCell>
                        <TableCell align="right">
                          <TaxWithheldCell
                            line={ln}
                            workerName={ln.worker_name_snapshot}
                            onOpen={openTaxDialog}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {!employeeRows.length ? (
                    <TableRow>
                      <TableCell colSpan={11}>
                        <Typography color="text.secondary">No employee payout records found.</Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      )}

      <TaxWithheldBreakdownDialog
        open={taxDialog.open}
        onClose={() => setTaxDialog({ open: false, line: null, workerName: "" })}
        line={taxDialog.line}
        workerName={taxDialog.workerName}
      />
    </Stack>
  );
}
