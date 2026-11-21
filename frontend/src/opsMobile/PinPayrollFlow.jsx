import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { getPayoutBatch, getPayoutBatches, patchPayoutBatch } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { businessTodayYmd } from "../utils/businessTime";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  approvedPublicBatches,
  batchesByStoredPaidDate,
  batchesForPeriod,
  formatMoney,
  isPayableCategory,
  loadPayrollView,
  paymentTotals,
  payrollPeriods,
  periodContaining,
  periodsOverlapping,
  publicBatch,
  savePayrollView,
  summarizeBatches,
  workerPaymentRows,
} from "./pinPayrollModel";

function applyPreviewPayment(batch, confirming) {
  if (!batch) return batch;
  const next = {
    ...batch,
    lines: (batch.lines || []).map((line) => ({ ...line })),
    payroll_display: { ...(batch.payroll_display || {}) },
  };
  const payLine = (line) => ({ ...line, payment_status: "paid" });
  if (confirming.lineId) {
    next.lines = next.lines.map((line) => (String(line.id) === String(confirming.lineId) ? payLine(line) : line));
  } else if (!confirming.w2) {
    next.lines = next.lines.map(payLine);
  }
  const everyPaid = next.lines.length > 0 && next.lines.every((line) => String(line.payment_status).toLowerCase() === "paid");
  if (confirming.w2 || everyPaid) {
    next.status = "paid";
    next.payroll_display.display_status = "paid";
    next.payroll_display.display_status_label = "Paid";
  }
  next.payout_details_audit = [
    ...(batch.payout_details_audit || []),
    {
      event: confirming.lineId ? "payment_recorded_set" : confirming.w2 ? "batch_marked_paid" : "pay_all",
      actor_id: null,
      at: new Date().toISOString(),
      detail: confirming.lineId ? `line_id=${confirming.lineId}` : confirming.w2 ? "W-2 batch explicitly marked paid" : "Remaining workers",
    },
  ];
  return next;
}

const PAYMENT_EVENTS = new Set(["payment_recorded_set", "pay_all", "batch_marked_paid"]);

function paymentHistory(batch) {
  const events = Array.isArray(batch?.payout_details_audit) ? batch.payout_details_audit : [];
  return events.filter((event) => PAYMENT_EVENTS.has(event.event)).slice(-8).reverse();
}

function auditWhen(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const utc = /Z$|[+-]\d{2}:\d{2}$/.test(raw) ? raw : `${raw}Z`;
  return formatFriendlyEtWall(utc);
}

function previewSource(preview) {
  if (!preview) return { items: [], canPay: false };
  if (Array.isArray(preview)) return { items: preview, canPay: false };
  return { items: preview.items || [], canPay: Boolean(preview.paymentActionsAllowed) };
}

function Figure({ label, value }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
        {label}
      </Typography>
      <Typography fontWeight={800}>{value}</Typography>
    </Box>
  );
}

export default function PinPayrollFlow({ onBack, onLock, preview = null }) {
  const { t } = useI18n();
  const today = businessTodayYmd();
  const saved = useMemo(() => (preview ? null : loadPayrollView()), [preview]);
  const [basis, setBasis] = useState(saved?.basis === "paid" ? "paid" : "period");
  const [periodIndex, setPeriodIndex] = useState(Number.isInteger(saved?.periodIndex) ? saved.periodIndex : 0);
  const [rangeFrom, setRangeFrom] = useState(saved?.rangeFrom || "");
  const [rangeTo, setRangeTo] = useState(saved?.rangeTo || "");
  const [useRange, setUseRange] = useState(Boolean(saved?.useRange));
  const initialPreview = previewSource(preview);
  const [rows, setRows] = useState(() => approvedPublicBatches(initialPreview.items));
  const [rawItems, setRawItems] = useState(initialPreview.items);
  const [canPay, setCanPay] = useState(initialPreview.canPay);
  const [fullBatch, setFullBatch] = useState(null);
  const [loading, setLoading] = useState(!preview);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    if (preview) return;
    savePayrollView({ basis, periodIndex, rangeFrom, rangeTo, useRange });
  }, [preview, basis, periodIndex, rangeFrom, rangeTo, useRange]);

  useEffect(() => {
    if (preview) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setForbidden(false);
    getPayoutBatches(undefined, { signal: controller.signal })
      .then((res) => {
        setRawItems(res?.data?.items || []);
        setRows(approvedPublicBatches(res?.data?.items || []));
        setCanPay(Boolean(res?.data?.payment_actions_allowed));
        setLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err?.response?.status === 403) {
          setForbidden(true);
          setRows([]);
          setLoading(false);
          return;
        }
        setError(err?.response?.data?.error || err?.message || t("pinMgmt.loadFailed"));
        setLoading(false);
      });
    return () => controller.abort();
  }, [preview, t]);

  const periods = useMemo(() => payrollPeriods(rows), [rows]);
  const currentPeriod = useMemo(() => periodContaining(periods, today), [periods, today]);
  const safeIndex = periods.length ? Math.min(periodIndex, periods.length - 1) : 0;
  const selectedPeriod = periods[safeIndex] || null;
  const visible = useMemo(() => {
    if (basis === "paid") {
      return batchesByStoredPaidDate(rows, useRange ? rangeFrom : "", useRange ? rangeTo : "");
    }
    if (useRange && (rangeFrom || rangeTo)) {
      const overlapping = new Set(periodsOverlapping(periods, rangeFrom, rangeTo).map((period) => period.key));
      return rows.filter((row) => overlapping.has(`${row.payPeriodStart}|${row.payPeriodEnd}`));
    }
    return batchesForPeriod(rows, selectedPeriod);
  }, [basis, rows, useRange, rangeFrom, rangeTo, periods, selectedPeriod]);
  const summary = useMemo(() => summarizeBatches(visible), [visible]);
  const selected = visible.find((row) => String(row.id) === String(selectedId)) || null;
  const workers = useMemo(() => (canPay ? workerPaymentRows(fullBatch) : []), [canPay, fullBatch]);
  const workerTotals = useMemo(() => paymentTotals(workers), [workers]);
  const payable = isPayableCategory(selected);

  useEffect(() => {
    if (!selectedId || !canPay) {
      setFullBatch(null);
      return undefined;
    }
    if (preview) {
      setFullBatch(rawItems.find((item) => String(item.id) === String(selectedId)) || null);
      return undefined;
    }
    let cancel = false;
    getPayoutBatch(selectedId)
      .then((res) => {
        if (!cancel) setFullBatch(res?.data || null);
      })
      .catch((err) => {
        if (!cancel) setError(err?.response?.data?.error || err?.message || t("pinMgmt.loadFailed"));
      });
    return () => {
      cancel = true;
    };
  }, [selectedId, canPay, preview, rawItems, t]);

  const leaveDetail = () => {
    setSelectedId(null);
    setConfirming(null);
  };

  const applyPayment = async () => {
    if (!confirming || acting || !selectedId) return;
    setActing(true);
    setError("");
    if (preview) {
      const source = fullBatch || rawItems.find((item) => String(item.id) === String(selectedId));
      const next = applyPreviewPayment(source, confirming);
      setFullBatch(next);
      setRawItems((current) => current.map((item) => (String(item.id) === String(selectedId) ? next : item)));
      const shown = publicBatch(next);
      if (shown) {
        setRows((current) => current.map((row) => (String(row.id) === String(selectedId) ? shown : row)));
      }
      setConfirming(null);
      setActing(false);
      return;
    }
    try {
      const body = { action: confirming.action };
      if (confirming.lineId) body.line_id = confirming.lineId;
      const res = await patchPayoutBatch(selectedId, body);
      const next = res?.data;
      if (next) {
        setFullBatch(next);
        setRows((current) =>
          current.map((row) => (String(row.id) === String(next.id) ? publicBatch(next) : row)).filter(Boolean),
        );
      }
      setConfirming(null);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("pinMgmt.loadFailed"));
    } finally {
      setActing(false);
    }
  };

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={selected ? t("pinMgmt.batchDetail") : t("pinMgmt.payroll")}
        backLabel={selected ? t("pinMgmt.payroll") : "PIN"}
        onBack={selected ? leaveDetail : onBack}
        onLock={onLock}
      />
      <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", pb: 2 }}>
        <Stack spacing={1.25} sx={{ pt: 1 }}>
          {loading ? (
            <Stack alignItems="center" sx={{ py: 4 }}>
              <CircularProgress size={28} />
              <Typography variant="body2" sx={{ mt: 1 }}>
                {t("pinMgmt.loading")}
              </Typography>
            </Stack>
          ) : null}
          {forbidden ? <Alert severity="info">{t("pinMgmt.payrollForbidden")}</Alert> : null}
          {error ? <Alert severity="error">{error}</Alert> : null}
          {!loading && !forbidden && !error ? (
            selected ? (
              <>
                <BatchCard row={selected} t={t} detail={!canPay} />
                {canPay && payable && workers.length ? (
                  <Stack spacing={1}>
                    <Typography fontWeight={800}>{t("pinMgmt.workerPayments")}</Typography>
                    <Typography variant="body2">
                      {t("pinMgmt.paidAmount")}: {formatMoney(workerTotals.paidAmount)} · {t("pinMgmt.remaining")}:{" "}
                      {formatMoney(workerTotals.remainingAmount)}
                    </Typography>
                    {workers.map((worker) => (
                      <Box
                        key={worker.id}
                        sx={{ p: 1.25, borderRadius: 2, border: `1px solid ${OPS_MOBILE.border}`, bgcolor: "#fff" }}
                      >
                        <Typography fontWeight={800}>{worker.name}</Typography>
                        <Typography variant="body2">
                          {worker.statusLabel} · {formatMoney(worker.paid ? worker.paidAmount : worker.remaining)}
                        </Typography>
                        {worker.paid ? null : (
                          <Button
                            size="small"
                            sx={{ mt: 0.5, minHeight: 40 }}
                            onClick={() =>
                              setConfirming({ action: "mark_line_paid", lineId: worker.id, name: worker.name })
                            }
                          >
                            {t("pinMgmt.markPaid")}
                          </Button>
                        )}
                      </Box>
                    ))}
                    {paymentHistory(fullBatch).map((event, index) => (
                      <Typography key={`${event.event}-${event.at}-${index}`} variant="caption" color="text.secondary" display="block">
                        {event.detail || event.event}
                        {event.actor_id ? ` · ${t("pinMgmt.markedBy", { id: event.actor_id })}` : ""}
                        {event.at ? ` · ${auditWhen(event.at)}` : ""}
                      </Typography>
                    ))}
                    {selected.status !== "paid" && workerTotals.unpaidWorkers > 0 ? (
                      <Button variant="contained" sx={{ minHeight: 44 }} onClick={() => setConfirming({ action: "mark_paid" })}>
                        {t("pinMgmt.payAll")}
                      </Button>
                    ) : null}
                  </Stack>
                ) : null}
                {canPay && selected.categoryKey === "w2" && selected.status === "ready_for_payroll" ? (
                  <Button variant="contained" sx={{ minHeight: 44 }} onClick={() => setConfirming({ action: "mark_paid", w2: true })}>
                    {t("pinMgmt.markPaid")}
                  </Button>
                ) : null}
                {confirming ? (
                  <Box sx={{ p: 1.25, borderRadius: 2, bgcolor: "#fff8e1", border: "1px solid #ffe082" }}>
                    <Typography variant="body2">
                      {confirming.w2
                        ? t("pinMgmt.confirmW2Paid")
                        : confirming.lineId
                          ? t("pinMgmt.confirmMarkPaid", { name: confirming.name })
                          : t("pinMgmt.confirmPayAll")}
                    </Typography>
                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                      <Button variant="outlined" disabled={acting} sx={{ minHeight: 44 }} onClick={() => setConfirming(null)}>
                        {t("pinMgmt.cancel")}
                      </Button>
                      <Button variant="contained" disabled={acting} sx={{ minHeight: 44 }} onClick={applyPayment}>
                        {t("pinMgmt.confirm")}
                      </Button>
                    </Stack>
                  </Box>
                ) : null}
              </>
            ) : (
              <>
                <Alert severity="info">{t("pinMgmt.readOnly")}</Alert>
                <Stack direction="row" spacing={1}>
                  <Button
                    variant={basis === "period" ? "contained" : "outlined"}
                    onClick={() => setBasis("period")}
                    sx={{ minHeight: 40 }}
                  >
                    {t("pinMgmt.payPeriod")}
                  </Button>
                  <Button
                    variant={basis === "paid" ? "contained" : "outlined"}
                    onClick={() => setBasis("paid")}
                    sx={{ minHeight: 40 }}
                  >
                    {t("pinMgmt.paidDate")}
                  </Button>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {basis === "period" ? t("pinMgmt.dateBasisPeriod") : t("pinMgmt.dateBasisPaid")}
                </Typography>
                {basis === "period" && !useRange && selectedPeriod ? (
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <IconButton
                      aria-label={t("pinMgmt.previousPeriod")}
                      disabled={safeIndex >= periods.length - 1}
                      onClick={() => setPeriodIndex(safeIndex + 1)}
                    >
                      <ChevronLeftIcon />
                    </IconButton>
                    <Box sx={{ textAlign: "center" }}>
                      <Typography fontWeight={800}>
                        {selectedPeriod.start} – {selectedPeriod.end}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        ET
                      </Typography>
                    </Box>
                    <IconButton
                      aria-label={t("pinMgmt.nextPeriod")}
                      disabled={safeIndex <= 0}
                      onClick={() => setPeriodIndex(safeIndex - 1)}
                    >
                      <ChevronRightIcon />
                    </IconButton>
                  </Stack>
                ) : null}
                <Stack direction="row" spacing={1}>
                  <Button
                    variant="outlined"
                    sx={{ minHeight: 40 }}
                    onClick={() => {
                      const index = periods.findIndex((period) => period.key === currentPeriod?.key);
                      setUseRange(false);
                      setBasis("period");
                      setPeriodIndex(index >= 0 ? index : 0);
                    }}
                  >
                    {t("pinMgmt.currentPeriod")}
                  </Button>
                  <Button
                    variant={useRange ? "contained" : "outlined"}
                    sx={{ minHeight: 40 }}
                    onClick={() => setUseRange((value) => !value)}
                  >
                    {t("pinMgmt.customRange")}
                  </Button>
                </Stack>
                {useRange ? (
                  <Stack direction="row" spacing={1}>
                    <TextField
                      type="date"
                      size="small"
                      label={t("pinMgmt.from")}
                      value={rangeFrom}
                      onChange={(event) => setRangeFrom(event.target.value)}
                      InputLabelProps={{ shrink: true }}
                    />
                    <TextField
                      type="date"
                      size="small"
                      label={t("pinMgmt.to")}
                      value={rangeTo}
                      onChange={(event) => setRangeTo(event.target.value)}
                      InputLabelProps={{ shrink: true }}
                    />
                  </Stack>
                ) : null}
                <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                  <Figure label={t("pinMgmt.approvedBatches")} value={summary.batches} />
                  <Figure label={t("pinMgmt.employees")} value={summary.employees} />
                  <Figure
                    label={t("pinMgmt.approvedHours")}
                    value={summary.approvedHours == null ? "—" : summary.approvedHours}
                  />
                  <Figure label={t("pinMgmt.grossWages")} value={formatMoney(summary.grossWages)} />
                  <Figure label={t("pinMgmt.payoutAmount")} value={formatMoney(summary.payoutAmount)} />
                </Box>
                <Typography variant="caption" color="text.secondary">
                  {t("pinMgmt.noEmployeePay")}
                </Typography>
                {visible.length ? (
                  visible.map((row) => (
                    <Box
                      key={row.id}
                      component="button"
                      onClick={() => setSelectedId(row.id)}
                      sx={{
                        textAlign: "left",
                        width: "100%",
                        p: 1.25,
                        borderRadius: 2,
                        border: `1px solid ${OPS_MOBILE.border}`,
                        bgcolor: OPS_MOBILE.surface,
                        cursor: "pointer",
                      }}
                    >
                      <Typography fontWeight={800}>{row.name}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {row.payPeriodStart} – {row.payPeriodEnd} · {row.statusLabel}
                      </Typography>
                      <Typography variant="body2" sx={{ mt: 0.5 }}>
                        {t("pinMgmt.grossWages")}: {formatMoney(row.grossWages)} · {t("pinMgmt.payoutAmount")}:{" "}
                        {formatMoney(row.payoutAmount)}
                      </Typography>
                    </Box>
                  ))
                ) : (
                  <Alert severity="info">{t("pinMgmt.noPayroll")}</Alert>
                )}
              </>
            )
          ) : null}
        </Stack>
      </Box>
    </OpsMobileShell>
  );
}

function BatchCard({ row, t, detail = false }) {
  return (
    <Stack
      spacing={1}
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: `1px solid ${OPS_MOBILE.border}`,
        bgcolor: OPS_MOBILE.surface,
      }}
    >
      <Typography fontWeight={800}>{row.name}</Typography>
      <Typography variant="body2" color="text.secondary">
        {row.statusLabel}
        {row.category ? ` · ${row.category}` : ""}
      </Typography>
      <Typography variant="body2">
        {t("pinMgmt.payPeriod")}: {row.payPeriodStart} – {row.payPeriodEnd} ET
      </Typography>
      <Figure label={t("pinMgmt.employees")} value={row.employees} />
      <Figure label={t("pinMgmt.approvedHours")} value={row.approvedHours == null ? "—" : row.approvedHours} />
      <Figure label={t("pinMgmt.grossWages")} value={formatMoney(row.grossWages)} />
      <Figure label={t("pinMgmt.payoutAmount")} value={formatMoney(row.payoutAmount)} />
      {row.adjustments != null ? (
        <Figure label={t("pinMgmt.adjustments")} value={formatMoney(row.adjustments)} />
      ) : null}
      {detail ? (
        <Typography variant="caption" color="text.secondary">
          {t("pinMgmt.noEmployeePay")}
        </Typography>
      ) : null}
    </Stack>
  );
}
