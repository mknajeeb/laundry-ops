import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  IconButton,
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
import DownloadIcon from "@mui/icons-material/Download";
import PrintIcon from "@mui/icons-material/Print";
import VisibilityIcon from "@mui/icons-material/Visibility";
import {
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  getTaUsers,
  getVendorReceiptHtml,
} from "../api";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
} from "../payroll/payoutSettlementDisplay";
import { downloadPdfFromFetch, paystubDownloadFilename } from "../payroll/paystubDownload";
import {
  DOC_HISTORY_CATEGORY_OPTIONS,
  bulkDownloadPlan,
  documentColumnLabel,
  documentDownloadSuffix,
  downloadAllLabel,
  mergeWorkerOptions,
  netColumnLabel,
  rowDocumentActions,
  rowDocumentKind,
  taxWithheldApplies,
  workerOptionsForCategory,
  workerOptionsFromRows,
} from "../payroll/payrollDocumentHistory";
import { accountantPeriodStatusLabel } from "../payroll/accountantBatchPick";
import AccountantScopeFilters from "./AccountantScopeFilters";
import TaxWithheldBreakdownDialog from "./TaxWithheldBreakdownDialog";

const RANGE_OPTIONS = [
  { value: "this_year", label: "This year" },
  { value: "last_year", label: "Last year" },
  { value: "last_5", label: "Last 5 pay periods" },
  { value: "last_10", label: "Last 10 pay periods" },
  { value: "all", label: "All pay periods" },
];

const ACCOUNTANT_BATCH_STATUSES = new Set([
  "sent_to_accountant",
  "accountant_reviewed",
  "approved_for_payment",
  "paid",
  "closed",
]);

function lineGross(ln) {
  return Number(ln.gross_wages || ln.gross_amount || ln.total_amount || 0);
}

async function previewHtmlDocument(fetchFn) {
  const res = await fetchFn();
  const html = typeof res?.data === "string" ? res.data : String(res?.data ?? "");
  const w = window.open("", "_blank");
  if (!w) throw new Error("Pop-up blocked — allow pop-ups to preview");
  w.document.write(html);
  w.document.close();
}

async function printHtmlDocument(fetchFn) {
  const res = await fetchFn();
  const html = typeof res?.data === "string" ? res.data : String(res?.data ?? "");
  const frame = document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.border = "0";
  document.body.appendChild(frame);
  const doc = frame.contentWindow?.document;
  if (!doc) throw new Error("Print failed");
  doc.open();
  doc.write(html);
  doc.close();
  frame.contentWindow?.focus();
  frame.contentWindow?.print();
  setTimeout(() => frame.remove(), 1000);
}

function documentFetch(kind, batchId, lineId, { preview = false } = {}) {
  return kind === "receipt"
    ? () => getVendorReceiptHtml(batchId, lineId, { preview })
    : () => getPaystubHtml(batchId, lineId, { preview });
}

function filterBatchesByRange(batches, range) {
  const year = new Date().getFullYear();
  let list = [...batches];
  if (range === "this_year") {
    list = list.filter((b) => String(b.pay_period_end || "").slice(0, 4) === String(year));
  } else if (range === "last_year") {
    list = list.filter((b) => String(b.pay_period_end || "").slice(0, 4) === String(year - 1));
  } else if (range === "last_5") {
    list = list.slice(0, 5);
  } else if (range === "last_10") {
    list = list.slice(0, 10);
  }
  return list;
}

export default function AccountantEmployeePaystubsPanel({ w2Only = false }) {
  const [viewMode, setViewMode] = useState("employee");
  const [category, setCategory] = useState(w2Only ? "w2" : "all");
  const [range, setRange] = useState("this_year");
  const [batches, setBatches] = useState([]);
  const [profileWorkers, setProfileWorkers] = useState([]);
  const [selectedWorker, setSelectedWorker] = useState(null);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [rows, setRows] = useState([]);
  const [batchWorkers, setBatchWorkers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const [busyKey, setBusyKey] = useState("");

  useEffect(() => {
    if (w2Only && category !== "w2") setCategory("w2");
  }, [w2Only, category]);

  useEffect(() => {
    const effectiveCategory = w2Only ? "w2" : category;
    const params =
      effectiveCategory === "all" ? {} : { worker_category: effectiveCategory };
    getPayoutBatches(params)
      .then((res) => {
        const list = (res.data?.items || []).filter((b) => ACCOUNTANT_BATCH_STATUSES.has(b.status));
        list.sort((a, b) =>
          String(b.pay_period_end || "").localeCompare(String(a.pay_period_end || "")),
        );
        setBatches(list);
      })
      .catch(() => setBatches([]));
    getTaUsers()
      .then((res) => {
        setProfileWorkers(
          workerOptionsForCategory(res.data?.users || res.data || [], effectiveCategory),
        );
      })
      .catch(() => setProfileWorkers([]));
  }, [category, w2Only]);

  const loadRows = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const shapeLine = (ln, batch) => ({
        ...ln,
        batch_id: batch.id,
        batch_name: batch.batch_name,
        worker_category: batch.worker_category,
        pay_period_start: batch.pay_period_start,
        pay_period_end: batch.pay_period_end,
      });

      if (viewMode === "batch") {
        if (!selectedBatchId) {
          setRows([]);
          return;
        }
        const res = await getPayoutBatchDetails(Number(selectedBatchId));
        const batch = res.data;
        let lines = (batch?.lines || []).map((ln) => shapeLine(ln, batch));
        if (selectedWorker?.id) {
          lines = lines.filter((ln) => Number(ln.user_id) === Number(selectedWorker.id));
        }
        setRows(lines);
        return;
      }

      let scopedBatches = filterBatchesByRange(batches, range);
      if (selectedBatchId) {
        scopedBatches = scopedBatches.filter((b) => String(b.id) === String(selectedBatchId));
      }

      const details = await Promise.all(
        scopedBatches.map(async (b) => {
          try {
            const r = await getPayoutBatchDetails(b.id);
            return r.data;
          } catch {
            return null;
          }
        }),
      );

      // Keep every worker's line so the worker dropdown (built from these rows)
      // stays complete; the selected worker is applied in `visibleRows`.
      const out = [];
      for (const batch of details.filter(Boolean)) {
        for (const ln of batch.lines || []) {
          out.push(shapeLine(ln, batch));
        }
      }
      out.sort((a, b) => {
        const pe = String(b.pay_period_end || "").localeCompare(String(a.pay_period_end || ""));
        if (pe !== 0) return pe;
        return String(a.worker_name_snapshot || "").localeCompare(
          String(b.worker_name_snapshot || ""),
        );
      });
      setRows(out);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load payroll documents");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [viewMode, range, batches, selectedBatchId, selectedWorker]);

  useEffect(() => {
    if (viewMode !== "batch" || !selectedBatchId) {
      setBatchWorkers([]);
      return;
    }
    let cancelled = false;
    getPayoutBatchDetails(Number(selectedBatchId))
      .then((res) => {
        if (cancelled) return;
        const seen = new Set();
        const list = [];
        for (const ln of res.data?.lines || []) {
          const uid = ln.user_id;
          if (!uid || seen.has(uid)) continue;
          seen.add(uid);
          list.push({
            id: uid,
            label: ln.worker_name_snapshot || `User #${uid}`,
          });
        }
        list.sort((a, b) => String(a.label).localeCompare(String(b.label)));
        setBatchWorkers(list);
      })
      .catch(() => {
        if (!cancelled) setBatchWorkers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [viewMode, selectedBatchId]);

  useEffect(() => {
    loadRows();
  }, [loadRows]);

  const visibleRows = useMemo(() => {
    if (viewMode === "batch") return rows;
    if (!selectedWorker) return [];
    return rows.filter((ln) => Number(ln.user_id) === Number(selectedWorker.id));
  }, [viewMode, selectedWorker, rows]);

  // Worker dropdown = payroll profiles for the category ∪ workers present in the
  // loaded document rows (so historical / inactive workers never disappear).
  const employeeWorkerOptions = useMemo(
    () => mergeWorkerOptions(profileWorkers, workerOptionsFromRows(rows)),
    [profileWorkers, rows],
  );

  // Labels: driven by the concrete rows (batch view) or the category filter (employee view).
  const labelCategory = viewMode === "batch" ? "all" : w2Only ? "w2" : category;
  const finalColumnLabel = documentColumnLabel(labelCategory, visibleRows);
  const netLabel = netColumnLabel(visibleRows);
  const bulkLabel = downloadAllLabel(labelCategory, visibleRows);

  const bulkPlan = useMemo(() => bulkDownloadPlan(visibleRows), [visibleRows]);

  const runAction = async (key, fn) => {
    setBusyKey(key);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Document action failed");
    } finally {
      setBusyKey("");
    }
  };

  const previewDocument = (ln) => {
    const kind = rowDocumentKind(ln);
    const preview = !rowDocumentActions(ln).final;
    return runAction(`pv-${ln.batch_id}-${ln.id}`, () =>
      previewHtmlDocument(documentFetch(kind, ln.batch_id, ln.id, { preview })),
    );
  };

  const printDocument = (ln) => {
    const kind = rowDocumentKind(ln);
    return runAction(`pr-${ln.batch_id}-${ln.id}`, () =>
      printHtmlDocument(documentFetch(kind, ln.batch_id, ln.id)),
    );
  };

  const downloadDocument = (ln) => {
    const kind = rowDocumentKind(ln);
    return runAction(`dl-${ln.batch_id}-${ln.id}`, () =>
      downloadPdfFromFetch(
        documentFetch(kind, ln.batch_id, ln.id),
        paystubDownloadFilename(ln.worker_name_snapshot, ln.pay_period_start, ln.pay_period_end, {
          suffix: documentDownloadSuffix(kind),
        }),
      ),
    );
  };

  const downloadAllVisible = async () => {
    if (!bulkPlan.length) return;
    setBusyKey("all");
    setError("");
    try {
      for (const item of bulkPlan) {
        await downloadPdfFromFetch(
          documentFetch(item.kind, item.batchId, item.lineId),
          paystubDownloadFilename(item.workerName, item.payPeriodStart, item.payPeriodEnd, {
            suffix: documentDownloadSuffix(item.kind),
          }),
        );
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Bulk download failed");
    } finally {
      setBusyKey("");
    }
  };

  const handleViewModeChange = (mode) => {
    setViewMode(mode);
    setSelectedWorker(null);
    if (mode === "employee") {
      setSelectedBatchId("");
    }
  };

  const handleCategoryChange = (value) => {
    if (w2Only) return;
    setCategory(value);
    setSelectedWorker(null);
    setSelectedBatchId("");
  };

  const scopeCategory = w2Only ? "w2" : category;
  const categoryOptions = w2Only ? [] : DOC_HISTORY_CATEGORY_OPTIONS;

  return (
    <Stack spacing={1.5}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Box>
            <Typography variant="subtitle1" fontWeight={700}>
              By Employee
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Payroll document history — filter by worker or batch, then view, print, or download.
            </Typography>
          </Box>
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            disabled={!bulkPlan.length || busyKey === "all"}
            onClick={downloadAllVisible}
          >
            {bulkLabel}
          </Button>
        </Stack>
      </Paper>

      <AccountantScopeFilters
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
        batches={batches}
        selectedBatchId={selectedBatchId}
        onBatchChange={setSelectedBatchId}
        workers={viewMode === "batch" ? batchWorkers : employeeWorkerOptions}
        selectedWorker={selectedWorker}
        onWorkerChange={setSelectedWorker}
        workerLabel={scopeCategory === "w2" ? "Employee" : "Worker"}
        category={scopeCategory}
        onCategoryChange={handleCategoryChange}
        categoryOptions={categoryOptions}
        range={range}
        onRangeChange={setRange}
        rangeOptions={RANGE_OPTIONS}
        weekStartsOn={0}
        periodStart={periodStart}
        periodEnd={periodEnd}
        onPeriodChange={({ start, end, batchId }) => {
          setPeriodStart(start || "");
          setPeriodEnd(end || "");
          if (batchId) setSelectedBatchId(String(batchId));
        }}
        batchStatusLabel={accountantPeriodStatusLabel}
      />

      <Paper variant="outlined" sx={{ overflow: "hidden" }}>
        {loading ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            Loading…
          </Typography>
        ) : viewMode === "employee" && !selectedWorker ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            Select a worker to see their payroll document history.
          </Typography>
        ) : viewMode === "batch" && !selectedBatchId ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            Select a batch to see payroll documents for that pay period.
          </Typography>
        ) : (
          <TableContainer sx={{ px: 1, pb: 1 }}>
            <Table size="small" sx={{ minWidth: 680 }}>
              <TableHead>
                <TableRow>
                  {viewMode === "batch" ? <TableCell>Worker</TableCell> : null}
                  <TableCell>Pay period</TableCell>
                  <TableCell>Category</TableCell>
                  <TableCell align="right">Gross</TableCell>
                  <TableCell align="right">Tax withheld</TableCell>
                  <TableCell align="right">{netLabel}</TableCell>
                  <TableCell align="right" sx={{ pr: 2, minWidth: 120 }}>
                    {finalColumnLabel}
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleRows.map((ln) => {
                  const key = `${ln.batch_id}-${ln.id}`;
                  const actions = rowDocumentActions(ln);
                  const kind = rowDocumentKind(ln);
                  const categoryLabel = kind === "receipt" ? "Contractor" : "W-2";
                  return (
                    <TableRow key={key} hover>
                      {viewMode === "batch" ? (
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                      ) : null}
                      <TableCell>
                        {ln.pay_period_start} – {ln.pay_period_end}
                      </TableCell>
                      <TableCell>{categoryLabel}</TableCell>
                      <TableCell align="right">${lineGross(ln).toFixed(2)}</TableCell>
                      <TableCell align="right">
                        {taxWithheldApplies(ln) ? (
                          <Button
                            size="small"
                            variant="text"
                            sx={{ minWidth: 0, p: 0 }}
                            onClick={() =>
                              setTaxDialog({
                                open: true,
                                line: ln,
                                workerName: ln.worker_name_snapshot,
                              })
                            }
                          >
                            {formatTaxWithheldDisplay(ln)}
                          </Button>
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            —
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell align="right">{formatNetPaidDisplay(ln)}</TableCell>
                      <TableCell align="right" sx={{ pr: 1 }}>
                        {actions.final ? (
                          <Stack direction="row" spacing={0.25} justifyContent="flex-end">
                            <Tooltip title="View">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => previewDocument(ln)}
                              >
                                <VisibilityIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Print">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => printDocument(ln)}
                              >
                                <PrintIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Download">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => downloadDocument(ln)}
                              >
                                <DownloadIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </Stack>
                        ) : actions.preview ? (
                          <Stack direction="row" spacing={0.25} justifyContent="flex-end">
                            <Tooltip title="Preview (not finalized)">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => previewDocument(ln)}
                              >
                                <VisibilityIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ alignSelf: "center" }}
                            >
                              Pending
                            </Typography>
                          </Stack>
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            Pending
                          </Typography>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!visibleRows.length ? (
                  <TableRow>
                    <TableCell colSpan={viewMode === "batch" ? 7 : 6}>
                      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                        No payroll documents match these filters.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      <TaxWithheldBreakdownDialog
        open={taxDialog.open}
        onClose={() => setTaxDialog({ open: false, line: null, workerName: "" })}
        line={taxDialog.line}
        workerName={taxDialog.workerName}
      />
    </Stack>
  );
}
