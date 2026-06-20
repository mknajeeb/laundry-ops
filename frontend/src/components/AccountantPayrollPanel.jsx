import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PayPeriodSelect from "./PayPeriodSelect";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import {
  finalizePayoutDetails,
  getPayoutBatchDetails,
  getPayoutBatches,
  processPayoutBatch,
  putPayoutBatchDetails,
} from "../api";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import { displayStatusLabel } from "../payroll/payrollBatchStatus";

const DEDUCTION_FIELDS = [
  { key: "fit", label: "FIT" },
  { key: "ss", label: "SS" },
  { key: "medicare", label: "Medicare" },
  { key: "state", label: "State" },
  { key: "local", label: "Local" },
];

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function emptyLineState(line) {
  const pd = line?.payout_details || {};
  return {
    line_id: line.id,
    employee_deductions: { ...(pd.employee_deductions || {}) },
    employer_taxes: { ...(pd.employer_taxes || {}) },
    payment: { ...(pd.payment || {}) },
    settlement: { ...(pd.settlement || {}) },
    employee_note: pd.employee_note || "",
  };
}

function lineTaxTotal(draft) {
  return DEDUCTION_FIELDS.reduce((s, f) => s + num(draft.employee_deductions?.[f.key]), 0);
}

function lineGross(ln) {
  return num(ln.gross_amount || ln.total_amount || ln.gross_wages);
}

export default function AccountantPayrollPanel() {
  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [periodExpanded, setPeriodExpanded] = useState(false);
  const [batches, setBatches] = useState([]);
  const [detail, setDetail] = useState(null);
  const [lineDrafts, setLineDrafts] = useState({});
  const [expanded, setExpanded] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const autoPickedRef = useRef(false);

  useEffect(() => {
    const r = defaultPayPeriodRange(0);
    setPeriodStart(r.start);
    setPeriodEnd(r.end);
  }, []);

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
      const batch = res.data;
      setDetail(batch);
      const drafts = {};
      (batch.lines || []).forEach((ln) => {
        drafts[ln.id] = emptyLineState(ln);
      });
      setLineDrafts(drafts);
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
    const pending = batches.find((b) => b.status === "sent_to_accountant");
    const pick = pending || batches.find((b) => b.payroll_display?.display_status === "ready_for_payroll");
    if (pick) {
      setPeriodStart(normPayPeriodYmd(pick.pay_period_start));
      setPeriodEnd(normPayPeriodYmd(pick.pay_period_end));
    }
    autoPickedRef.current = true;
  }, [batches]);

  const updateDraft = (lineId, section, key, value) => {
    setLineDrafts((prev) => ({
      ...prev,
      [lineId]: {
        ...prev[lineId],
        [section]: { ...prev[lineId][section], [key]: value },
      },
    }));
  };

  const totals = useMemo(() => {
    const lines = detail?.lines || [];
    let gross = 0;
    let tax = 0;
    let net = 0;
    for (const ln of lines) {
      const draft = lineDrafts[ln.id] || emptyLineState(ln);
      const g = lineGross(ln);
      const t = lineTaxTotal(draft);
      gross += g;
      tax += t;
      net += g - t;
    }
    return { gross, tax, net, count: lines.length };
  }, [detail, lineDrafts]);

  const canSubmit =
    detail &&
    (detail.can_process_as_accountant ||
      detail.payroll_display?.display_status === "ready_for_payroll");

  const submitPayroll = async () => {
    if (!detail?.id) return;
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const lines = Object.values(lineDrafts).map((d) => ({
        line_id: d.line_id,
        payout_details: {
          employee_deductions: d.employee_deductions,
          employer_taxes: d.employer_taxes,
          payment: d.payment,
          settlement: d.settlement,
          employee_note: d.employee_note || "",
        },
      }));
      await putPayoutBatchDetails(detail.id, { lines });
      let batch = detail;
      if (batch.can_process_as_accountant) {
        const proc = await processPayoutBatch(batch.id);
        batch = proc.data;
      }
      if (!batch.payout_workflow?.payout_details_finalized) {
        const fin = await finalizePayoutDetails(batch.id);
        batch = fin.data;
      }
      setDetail(batch);
      setInfo("Payroll submitted — ready to pay.");
      await loadBatches();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={1.5}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>{info}</Alert>
      ) : null}

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
          Accountant Payroll
        </Typography>
        {batches.length ? (
          <PayPeriodSelect
            weekStartsOn={weekStartsOn}
            batches={batches}
            start={periodStart}
            end={periodEnd}
            expanded={periodExpanded}
            onExpandedChange={setPeriodExpanded}
            batchStatusLabel={(b) => displayStatusLabel(b)}
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
          {loading ? (
            <Typography color="text.secondary">Loading…</Typography>
          ) : (
            <Paper variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell width={32} />
                    <TableCell>Employee</TableCell>
                    <TableCell align="right">Gross</TableCell>
                    <TableCell align="right">FIT</TableCell>
                    <TableCell align="right">SS</TableCell>
                    <TableCell align="right">Medicare</TableCell>
                    <TableCell align="right">State</TableCell>
                    <TableCell align="right">Total tax</TableCell>
                    <TableCell align="right">Net</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(detail.lines || []).map((ln) => {
                    const draft = lineDrafts[ln.id] || emptyLineState(ln);
                    const gross = lineGross(ln);
                    const tax = lineTaxTotal(draft);
                    const isOpen = expanded[ln.id];
                    const editable = canSubmit && !detail.payout_workflow?.payout_details_finalized;
                    return (
                      <Fragment key={ln.id}>
                        <TableRow sx={{ "& td": { py: 0.5 } }}>
                          <TableCell>
                            <IconButton size="small" onClick={() => setExpanded((p) => ({ ...p, [ln.id]: !p[ln.id] }))}>
                              <ExpandMoreIcon
                                fontSize="small"
                                sx={{ transform: isOpen ? "rotate(180deg)" : "none" }}
                              />
                            </IconButton>
                          </TableCell>
                          <TableCell>{ln.worker_name_snapshot}</TableCell>
                          <TableCell align="right">${gross.toFixed(2)}</TableCell>
                          {DEDUCTION_FIELDS.map((f) => (
                            <TableCell key={f.key} align="right">
                              {editable ? (
                                <TextField
                                  size="small"
                                  type="number"
                                  value={draft.employee_deductions?.[f.key] ?? ""}
                                  onChange={(e) =>
                                    updateDraft(ln.id, "employee_deductions", f.key, e.target.value)
                                  }
                                  inputProps={{ style: { width: 56, textAlign: "right" } }}
                                />
                              ) : (
                                `$${num(draft.employee_deductions?.[f.key]).toFixed(2)}`
                              )}
                            </TableCell>
                          ))}
                          <TableCell align="right">${tax.toFixed(2)}</TableCell>
                          <TableCell align="right">${(gross - tax).toFixed(2)}</TableCell>
                        </TableRow>
                        <TableRow key={`${ln.id}-n`}>
                          <TableCell colSpan={9} sx={{ py: 0 }}>
                            <Collapse in={isOpen}>
                              <Box sx={{ py: 1, pl: 2 }}>
                                <TextField
                                  size="small"
                                  label="Employee note"
                                  value={draft.employee_note || ""}
                                  disabled={!editable}
                                  onChange={(e) =>
                                    setLineDrafts((prev) => ({
                                      ...prev,
                                      [ln.id]: { ...prev[ln.id], employee_note: e.target.value },
                                    }))
                                  }
                                />
                              </Box>
                            </Collapse>
                          </TableCell>
                        </TableRow>
                      </Fragment>
                    );
                  })}
                  {(detail.lines || []).length > 0 ? (
                    <TableRow>
                      <TableCell sx={{ fontWeight: 700 }}>Totals</TableCell>
                      <TableCell />
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.gross.toFixed(2)}
                      </TableCell>
                      <TableCell colSpan={4} />
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.tax.toFixed(2)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        ${totals.net.toFixed(2)}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </Paper>
          )}
          {canSubmit && !detail.payout_workflow?.payout_details_finalized ? (
            <Button variant="contained" disabled={submitting} onClick={submitPayroll}>
              Submit payroll
            </Button>
          ) : null}
        </>
      ) : null}
    </Stack>
  );
}
