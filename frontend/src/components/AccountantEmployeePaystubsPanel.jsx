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
  getBatchPaystubsHtml,
  getPayoutBatchDetails,
  getPayoutBatches,
  getPaystubHtml,
  getTaUsers,
} from "../api";
import {
  formatNetPaidDisplay,
  formatTaxWithheldDisplay,
  isPayoutDetailsFinalized,
} from "../payroll/payoutSettlementDisplay";
import {
  downloadPdfFromFetch,
  paystubBatchDownloadFilename,
  paystubDownloadFilename,
} from "../payroll/paystubDownload";
import {
  filterAccountantDocumentUsers,
  mapAccountantDocumentUserOption,
} from "../payroll/accountantDocumentUsers";
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

function paystubReady(ln) {
  return isPayoutDetailsFinalized(ln) && ln.paystub_available !== false;
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

export default function AccountantEmployeePaystubsPanel() {
  const [viewMode, setViewMode] = useState("employee");
  const [range, setRange] = useState("this_year");
  const [batches, setBatches] = useState([]);
  const [workers, setWorkers] = useState([]);
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
    getPayoutBatches({ worker_category: "w2" })
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
        const list = filterAccountantDocumentUsers(res.data?.users || res.data || [], "w2").map(
          mapAccountantDocumentUserOption,
        );
        setWorkers(list);
      })
      .catch(() => setWorkers([]));
  }, []);

  const loadRows = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (viewMode === "batch") {
        if (!selectedBatchId) {
          setRows([]);
          return;
        }
        const res = await getPayoutBatchDetails(Number(selectedBatchId));
        const batch = res.data;
        let lines = (batch?.lines || []).map((ln) => ({
          ...ln,
          batch_id: batch.id,
          batch_name: batch.batch_name,
          pay_period_start: batch.pay_period_start,
          pay_period_end: batch.pay_period_end,
          paystub_available: Boolean(batch.payout_workflow?.paystub_available),
        }));
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

      const out = [];
      for (const batch of details.filter(Boolean)) {
        for (const ln of batch.lines || []) {
          if (selectedWorker?.id && Number(ln.user_id) !== Number(selectedWorker.id)) continue;
          out.push({
            ...ln,
            batch_id: batch.id,
            batch_name: batch.batch_name,
            pay_period_start: batch.pay_period_start,
            pay_period_end: batch.pay_period_end,
            paystub_available: Boolean(batch.payout_workflow?.paystub_available),
          });
        }
      }
      out.sort((a, b) => {
        const pe = String(b.pay_period_end || "").localeCompare(String(a.pay_period_end || ""));
        if (pe !== 0) return pe;
        return String(a.worker_name_snapshot || "").localeCompare(String(b.worker_name_snapshot || ""));
      });
      setRows(out);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load employee paystubs");
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
    if (viewMode === "employee" && !selectedWorker) return [];
    return rows;
  }, [viewMode, selectedWorker, rows]);

  const paystubRows = useMemo(() => visibleRows.filter((ln) => paystubReady(ln)), [visibleRows]);

  const runPaystubAction = async (key, fn) => {
    setBusyKey(key);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Paystub action failed");
    } finally {
      setBusyKey("");
    }
  };

  const previewPaystub = (ln) =>
    runPaystubAction(`pv-${ln.batch_id}-${ln.id}`, () =>
      previewHtmlDocument(() => getPaystubHtml(ln.batch_id, ln.id)),
    );

  const printPaystub = (ln) =>
    runPaystubAction(`pr-${ln.batch_id}-${ln.id}`, () =>
      printHtmlDocument(() => getPaystubHtml(ln.batch_id, ln.id)),
    );

  const downloadPaystub = (ln) =>
    runPaystubAction(`dl-${ln.batch_id}-${ln.id}`, () =>
      downloadPdfFromFetch(
        () => getPaystubHtml(ln.batch_id, ln.id),
        paystubDownloadFilename(ln.worker_name_snapshot, ln.pay_period_start, ln.pay_period_end),
      ),
    );

  const downloadAllVisible = async () => {
    const batchIds =
      viewMode === "batch" && selectedBatchId
        ? [Number(selectedBatchId)]
        : [...new Set(paystubRows.map((ln) => ln.batch_id).filter(Boolean))];
    if (!batchIds.length) return;
    setBusyKey("all");
    setError("");
    try {
      for (const batchId of batchIds) {
        const sample = paystubRows.find((ln) => ln.batch_id === batchId) || rows.find((ln) => ln.batch_id === batchId);
        if (!sample) continue;
        await downloadPdfFromFetch(
          () => getBatchPaystubsHtml(batchId),
          paystubBatchDownloadFilename(
            sample.batch_name,
            sample.pay_period_start,
            sample.pay_period_end,
          ),
        );
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Download all paystubs failed");
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
              Paystub history — filter by employee or batch, then view, print, or download.
            </Typography>
          </Box>
          <Button
            size="small"
            variant="outlined"
            startIcon={<DownloadIcon />}
            disabled={!paystubRows.length || busyKey === "all"}
            onClick={downloadAllVisible}
          >
            Download all paystubs
          </Button>
        </Stack>
      </Paper>

      <AccountantScopeFilters
        viewMode={viewMode}
        onViewModeChange={handleViewModeChange}
        batches={batches}
        selectedBatchId={selectedBatchId}
        onBatchChange={setSelectedBatchId}
        workers={viewMode === "batch" ? batchWorkers : workers}
        selectedWorker={selectedWorker}
        onWorkerChange={setSelectedWorker}
        workerLabel="Employee"
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
            Select an employee to see paystub history.
          </Typography>
        ) : viewMode === "batch" && !selectedBatchId ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            Select a batch to see employee paystubs for that pay period.
          </Typography>
        ) : (
          <TableContainer sx={{ px: 1, pb: 1 }}>
            <Table size="small" sx={{ minWidth: 640 }}>
              <TableHead>
                <TableRow>
                  {viewMode === "batch" ? <TableCell>Employee</TableCell> : null}
                  <TableCell>Pay period</TableCell>
                  <TableCell align="right">Gross</TableCell>
                  <TableCell align="right">Tax withheld</TableCell>
                  <TableCell align="right">Net paid</TableCell>
                  <TableCell align="right" sx={{ pr: 2, minWidth: 120 }}>
                    Paystub
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleRows.map((ln) => {
                  const key = `${ln.batch_id}-${ln.id}`;
                  const ready = paystubReady(ln);
                  return (
                    <TableRow key={key} hover>
                      {viewMode === "batch" ? (
                        <TableCell>{ln.worker_name_snapshot}</TableCell>
                      ) : null}
                      <TableCell>
                        {ln.pay_period_start} – {ln.pay_period_end}
                      </TableCell>
                      <TableCell align="right">${lineGross(ln).toFixed(2)}</TableCell>
                      <TableCell align="right">
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
                      </TableCell>
                      <TableCell align="right">{formatNetPaidDisplay(ln)}</TableCell>
                      <TableCell align="right" sx={{ pr: 1 }}>
                        {ready ? (
                          <Stack direction="row" spacing={0.25} justifyContent="flex-end">
                            <Tooltip title="View">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => previewPaystub(ln)}
                              >
                                <VisibilityIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Print">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => printPaystub(ln)}
                              >
                                <PrintIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Download">
                              <IconButton
                                size="small"
                                disabled={!!busyKey}
                                onClick={() => downloadPaystub(ln)}
                              >
                                <DownloadIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
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
                    <TableCell colSpan={viewMode === "batch" ? 6 : 5}>
                      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                        No paystub records match these filters.
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
