import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  FormControl,
  IconButton,
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

export default function AccountantEmployeePaystubsPanel() {
  const [range, setRange] = useState("this_year");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [taxDialog, setTaxDialog] = useState({ open: false, line: null, workerName: "" });
  const [busyKey, setBusyKey] = useState("");

  const loadRows = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getPayoutBatches({ worker_category: "w2" });
      let batches = (res.data?.items || []).filter((b) => ACCOUNTANT_BATCH_STATUSES.has(b.status));
      batches.sort((a, b) =>
        String(b.pay_period_end || "").localeCompare(String(a.pay_period_end || "")),
      );

      const year = new Date().getFullYear();
      if (range === "this_year") {
        batches = batches.filter((b) => String(b.pay_period_end || "").slice(0, 4) === String(year));
      } else if (range === "last_year") {
        batches = batches.filter(
          (b) => String(b.pay_period_end || "").slice(0, 4) === String(year - 1),
        );
      } else if (range === "last_5") {
        batches = batches.slice(0, 5);
      } else if (range === "last_10") {
        batches = batches.slice(0, 10);
      }

      const details = await Promise.all(
        batches.map(async (b) => {
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
  }, [range]);

  useEffect(() => {
    loadRows();
  }, [loadRows]);

  const paystubRows = useMemo(() => rows.filter((ln) => paystubReady(ln)), [rows]);

  const batchIdsWithPaystubs = useMemo(() => {
    const ids = new Set();
    for (const ln of paystubRows) {
      if (ln.batch_id) ids.add(ln.batch_id);
    }
    return [...ids];
  }, [paystubRows]);

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
    if (!batchIdsWithPaystubs.length) return;
    setBusyKey("all");
    setError("");
    try {
      for (const batchId of batchIdsWithPaystubs) {
        const sample = paystubRows.find((ln) => ln.batch_id === batchId);
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
              Paystub history across pay periods — view, print, or download.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Pay periods</InputLabel>
              <Select
                label="Pay periods"
                value={range}
                onChange={(e) => setRange(e.target.value)}
              >
                {RANGE_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
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
        </Stack>
      </Paper>

      <Paper variant="outlined">
        {loading ? (
          <Typography sx={{ p: 2 }} color="text.secondary">
            Loading…
          </Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Employee</TableCell>
                  <TableCell>Pay period</TableCell>
                  <TableCell align="right">Gross</TableCell>
                  <TableCell align="right">Tax withheld</TableCell>
                  <TableCell align="right">Net paid</TableCell>
                  <TableCell align="right">Paystub</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((ln) => {
                  const key = `${ln.batch_id}-${ln.id}`;
                  const ready = paystubReady(ln);
                  return (
                    <TableRow key={key} hover>
                      <TableCell>{ln.worker_name_snapshot}</TableCell>
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
                      <TableCell align="right">
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
                {!rows.length ? (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                        No employee payout records in this range.
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
