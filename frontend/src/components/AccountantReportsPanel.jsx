import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getAccountantYtd, getPayoutBatch, getPayoutBatches } from "../api";
import {
  ESTIMATE_DISCLAIMER,
  PAYROLL_ESTIMATE_PURPOSE,
  isLineTaxIncomplete,
} from "../payroll/payrollTaxMessages";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

export default function AccountantReportsPanel() {
  const [subTab, setSubTab] = useState(0);
  const [year, setYear] = useState(new Date().getFullYear());
  const [category, setCategory] = useState("all");
  const [batchFilter, setBatchFilter] = useState("accountant");
  const [ytdRows, setYtdRows] = useState([]);
  const [batches, setBatches] = useState([]);
  const [error, setError] = useState("");
  const [viewBatch, setViewBatch] = useState(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [ytdRes, batchRes] = await Promise.all([
        getAccountantYtd({ year, worker_category: category !== "all" ? category : undefined }),
        getPayoutBatches(category !== "all" ? { worker_category: category } : {}),
      ]);
      setYtdRows(ytdRes.data?.items || []);
      setBatches(batchRes.data?.items || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [year, category]);

  useEffect(() => {
    load();
  }, [load]);

  const filteredBatches = useMemo(() => {
    let rows = batches;
    if (batchFilter === "accountant") {
      rows = rows.filter((b) =>
        ["sent_to_accountant", "accountant_reviewed", "approved_for_payment", "paid", "closed"].includes(
          b.status,
        ),
      );
    } else if (batchFilter === "unpaid") {
      rows = rows.filter((b) => b.status !== "paid" && b.status !== "closed");
    }
    return rows;
  }, [batches, batchFilter]);

  const openBatch = async (id) => {
    try {
      const res = await getPayoutBatch(id);
      setViewBatch(res.data);
    } catch (e) {
      setError(e.response?.data?.error || "Could not load batch");
    }
  };

  const downloadBatchCsv = (batch) => {
    if (!batch?.lines?.length) return;
    const isW2 = batch.worker_category === "w2";
    const csvCell = (val) => String(val ?? "").replace(/,/g, ";");
    const header = isW2
      ? [
          "Worker",
          "Hours",
          "Rate",
          "Gross",
          "Federal est",
          "NY est",
          "NYC est",
          "SS employee",
          "Medicare employee",
          "Addl Medicare",
          "Total employee taxes",
          "Net pay",
          "Er SS",
          "Er Medicare",
          "FUTA est",
          "NY SUTA est",
          "Er other",
          "Workers comp",
          "Total employer taxes",
          "Total employer cost",
          "tax_calculation_status",
          "tax_notes",
          "profile_incomplete_fields",
          "estimated_withholding_notice",
          "Payment status",
          "Sick hours used",
          "Sick pay",
          "Health credit",
        ]
      : [
          "Worker",
          "Worker type",
          "Hours",
          "Rate",
          "Base pay",
          "Bonus/tip",
          "Health credit",
          "Reimbursements",
          "Gross payout",
          "Net/Total",
          "Payment status",
          "Paid date",
          "Notes",
        ];
    const lines = batch.lines.map((ln) => {
      const incomplete = isLineTaxIncomplete(ln);
      const profileFields = Array.isArray(ln.profile_incomplete_fields)
        ? ln.profile_incomplete_fields.join("; ")
        : ln.profile_incomplete_fields || "";
      return isW2
        ? [
            ln.worker_name_snapshot,
            ln.approved_hours,
            ln.rate,
            ln.gross_amount,
            incomplete ? "" : ln.federal_withholding ?? "",
            incomplete ? "" : ln.state_withholding ?? "",
            incomplete ? "" : ln.city_withholding ?? "",
            incomplete ? "" : ln.social_security_withholding ?? "",
            incomplete ? "" : ln.medicare_withholding ?? "",
            incomplete ? "" : ln.additional_medicare_withholding ?? "",
            incomplete ? "" : ln.total_employee_taxes ?? "",
            incomplete ? "" : ln.net_pay ?? "",
            incomplete ? "" : ln.employer_social_security ?? "",
            incomplete ? "" : ln.employer_medicare ?? "",
            incomplete ? "" : ln.futa_estimate ?? "",
            incomplete ? "" : ln.ny_suta_estimate ?? "",
            incomplete ? "" : ln.employer_other_tax_estimate ?? "",
            incomplete ? "" : ln.workers_comp_estimate ?? "",
            incomplete ? "" : ln.total_employer_taxes ?? "",
            incomplete ? "" : ln.total_employer_cost ?? "",
            ln.tax_calculation_status || ln.tax_calc_status || "",
            csvCell(ln.tax_notes || ln.tax_calc_notes),
            csvCell(profileFields),
            ln.estimated_withholding_notice || (incomplete ? "" : ESTIMATE_DISCLAIMER),
            ln.payment_status_label || ln.payment_status,
            ln.sick_hours_used ?? "",
            ln.sick_pay_amount ?? "",
            ln.health_credit_amount ?? "",
          ].join(",")
        : [
            ln.worker_name_snapshot,
            batch.worker_category_label,
            ln.approved_hours,
            ln.rate,
            ln.gross_amount,
            ln.bonus_tip_amount ?? "",
            ln.health_credit_amount ?? "",
            ln.reimbursement_amount ?? "",
            ln.gross_amount ?? ln.total_amount,
            ln.total_amount,
            ln.payment_status_label || ln.payment_status,
            ln.payment_date || "",
            csvCell(ln.notes || ln.admin_note || ""),
          ].join(",");
    });
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `accountant-batch-${batch.id}.csv`;
    a.click();
  };

  const categoryTotals = useMemo(() => {
    const out = { w2: 0, contractor_1099: 0, temp: 0 };
    for (const r of ytdRows) {
      const cat = r.worker_category;
      if (cat in out) out[cat] += Number(r.total_paid_ytd || 0);
    }
    return out;
  }, [ytdRows]);

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">Accountant Reports</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          View approved batches sent for accountant review. W-2, 1099, and temp categories are
          always separate. W-2 exports include estimated withholding only — {ESTIMATE_DISCLAIMER}
        </Typography>
        <Alert severity="info" sx={{ mb: 2 }}>
          {PAYROLL_ESTIMATE_PURPOSE}
        </Alert>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
          <FormControl size="small" sx={{ minWidth: 100 }}>
            <InputLabel>Year</InputLabel>
            <Select label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[year, year - 1].map((y) => (
                <MenuItem key={y} value={y}>
                  {y}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Category</InputLabel>
            <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {WORKER_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Batch filter</InputLabel>
            <Select label="Batch filter" value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
              <MenuItem value="accountant">Sent to accountant+</MenuItem>
              <MenuItem value="all">All batches</MenuItem>
              <MenuItem value="unpaid">Not fully paid</MenuItem>
            </Select>
          </FormControl>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mt: 2 }}>
          <Chip label={`W-2 YTD: $${categoryTotals.w2.toFixed(2)}`} color="primary" variant="outlined" />
          <Chip
            label={`1099 YTD: $${categoryTotals.contractor_1099.toFixed(2)}`}
            color="secondary"
            variant="outlined"
          />
          <Chip label={`Temp YTD: $${categoryTotals.temp.toFixed(2)}`} color="warning" variant="outlined" />
        </Stack>
      </Paper>

      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)}>
        <Tab label="Approved batches" />
        <Tab label="YTD by worker" />
        <Tab label="1099 / Temp" />
        <Tab label="W-2 support" />
      </Tabs>

      {subTab === 0 ? (
        <TableContainer component={Paper} sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 720 }}>
            <TableHead>
              <TableRow>
                <TableCell>Batch</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>Period</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Payout</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredBatches.map((b) => (
                <TableRow key={b.id} hover>
                  <TableCell>{b.batch_name}</TableCell>
                  <TableCell>{b.worker_category_label || b.worker_category}</TableCell>
                  <TableCell>
                    {b.pay_period_start} – {b.pay_period_end}
                  </TableCell>
                  <TableCell>{b.status}</TableCell>
                  <TableCell align="right">${Number(b.total_payout_amount || 0).toFixed(2)}</TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => openBatch(b.id)}>
                      View / download
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!filteredBatches.length ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography color="text.secondary">No batches match this filter.</Typography>
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {subTab === 1 ? (
        <TableContainer component={Paper} sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 720 }}>
            <TableHead>
              <TableRow>
                <TableCell>Worker</TableCell>
                <TableCell>Category</TableCell>
                <TableCell align="right">Paid YTD</TableCell>
                <TableCell align="right">Payments</TableCell>
                <TableCell>Last paid</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ytdRows.map((r) => (
                <TableRow key={`${r.user_id}-${r.worker_category}`}>
                  <TableCell>{r.worker_name}</TableCell>
                  <TableCell>{r.worker_category_label}</TableCell>
                  <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                  <TableCell align="right">{r.payment_count}</TableCell>
                  <TableCell>{r.last_payment_date || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {subTab === 2 ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            1099 / Temp — {year}
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Worker</TableCell>
                <TableCell>Type</TableCell>
                <TableCell align="right">YTD paid</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ytdRows
                .filter((r) => r.worker_category !== "w2")
                .map((r) => (
                  <TableRow key={r.user_id}>
                    <TableCell>{r.worker_name}</TableCell>
                    <TableCell>{r.worker_category_label}</TableCell>
                    <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      {subTab === 3 ? (
        <Paper sx={{ p: 2 }}>
          <Alert severity="info" sx={{ mb: 2 }}>
            W-2 reports show estimated withholding from employee W-4 profiles. {ESTIMATE_DISCLAIMER}{" "}
            {PAYROLL_ESTIMATE_PURPOSE}
          </Alert>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Worker</TableCell>
                <TableCell align="right">YTD gross (batches)</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {ytdRows
                .filter((r) => r.worker_category === "w2")
                .map((r) => (
                  <TableRow key={r.user_id}>
                    <TableCell>{r.worker_name}</TableCell>
                    <TableCell align="right">${Number(r.total_paid_ytd || 0).toFixed(2)}</TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </Paper>
      ) : null}

      <Dialog open={!!viewBatch} onClose={() => setViewBatch(null)} maxWidth="md" fullWidth>
        <DialogTitle>{viewBatch?.batch_name || "Batch report"}</DialogTitle>
        <DialogContent>
          {viewBatch ? (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Typography variant="body2">
                {viewBatch.worker_category_label} · {viewBatch.pay_period_start} –{" "}
                {viewBatch.pay_period_end} · {viewBatch.status}
              </Typography>
              {(viewBatch.warnings || []).map((w) => (
                <Alert key={w} severity="warning">
                  {w}
                </Alert>
              ))}
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Worker</TableCell>
                    <TableCell align="right">Hours</TableCell>
                    <TableCell align="right">Rate</TableCell>
                    <TableCell align="right">Gross</TableCell>
                    <TableCell>Payment</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(viewBatch.lines || []).map((ln) => (
                    <TableRow key={ln.id}>
                      <TableCell>{ln.worker_name_snapshot}</TableCell>
                      <TableCell align="right">{Number(ln.approved_hours || 0).toFixed(2)}</TableCell>
                      <TableCell align="right">${Number(ln.rate || 0).toFixed(2)}</TableCell>
                      <TableCell align="right">${Number(ln.gross_amount || 0).toFixed(2)}</TableCell>
                      <TableCell>{ln.payment_status_label || ln.payment_status}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setViewBatch(null)}>Close</Button>
          <Button onClick={() => downloadBatchCsv(viewBatch)} disabled={!viewBatch?.lines?.length}>
            Download CSV
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
