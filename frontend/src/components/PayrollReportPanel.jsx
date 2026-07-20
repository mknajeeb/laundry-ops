import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  InputLabel,
  ListItemText,
  MenuItem,
  OutlinedInput,
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
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import {
  getPayrollReport,
  getPayrollReportExcel,
  getPayrollReportMeta,
  getPayrollReportPdfHtml,
} from "../api";
import { PayrollDateField } from "./PayrollDateTimeField";
import { downloadHtmlDocumentPdf } from "../contractorForms/contractorPrint";
import {
  OT_PREMIUM_TOOLTIP,
} from "../payroll/payrollOtDisplay";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const RANGE_MODES = [
  { value: "period", label: "Payroll period(s)" },
  { value: "date_range", label: "Custom date range" },
  { value: "all_history", label: "All payroll history" },
];

function money(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0.00";
  return `$${n.toFixed(2)}`;
}

function hours(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return "";
  return n.toFixed(2);
}

function buildQueryParams(filters) {
  const params = {};
  if (filters.rangeMode === "all_history") {
    params.all_history = "1";
  } else if (filters.rangeMode === "date_range") {
    if (filters.dateFrom) params.date_from = filters.dateFrom;
    if (filters.dateTo) params.date_to = filters.dateTo;
  } else if (filters.selectedPeriods?.length) {
    params.period_start = filters.selectedPeriods.map((p) => p.split("|")[0]).join(",");
    params.period_end = filters.selectedPeriods.map((p) => p.split("|")[1]).join(",");
  }
  if (filters.userId) params.user_id = filters.userId;
  if (filters.workerCategory && filters.workerCategory !== "all") {
    params.worker_category = filters.workerCategory;
  }
  if (filters.payrollStatus && filters.payrollStatus !== "all") {
    params.payroll_status = filters.payrollStatus;
  }
  if (filters.paymentStatus && filters.paymentStatus !== "all") {
    params.payment_status = filters.paymentStatus;
  }
  return params;
}

const EMPTY_FILTERS = {
  rangeMode: "period",
  selectedPeriods: [],
  dateFrom: "",
  dateTo: "",
  userId: "",
  workerCategory: "all",
  payrollStatus: "all",
  paymentStatus: "all",
};

export default function PayrollReportPanel() {
  const [meta, setMeta] = useState({ employees: [], periods: [], date_match_rule: "" });
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getPayrollReportMeta()
      .then((res) => {
        setMeta({
          employees: res.data?.employees || [],
          periods: res.data?.periods || [],
          date_match_rule: res.data?.date_match_rule || "",
        });
        const periods = res.data?.periods || [];
        if (periods.length) {
          const first = `${periods[0].pay_period_start}|${periods[0].pay_period_end}`;
          setFilters((f) => ({ ...f, selectedPeriods: [first] }));
          setApplied((f) => ({ ...f, selectedPeriods: [first] }));
        }
      })
      .catch((e) => setError(e.response?.data?.error || e.message || "Could not load report meta"));
  }, []);

  const loadReport = useCallback(async (nextFilters) => {
    setLoading(true);
    setError("");
    try {
      const res = await getPayrollReport(buildQueryParams(nextFilters));
      setReport(res.data);
      setApplied(nextFilters);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load payroll report");
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (meta.periods.length || filters.rangeMode === "all_history") {
      // Initial load once meta arrives with a default period, or all-history
    }
  }, [meta.periods.length, filters.rangeMode]);

  useEffect(() => {
    if (!meta.periods.length && filters.rangeMode !== "all_history") return;
    if (filters.rangeMode === "period" && !filters.selectedPeriods.length) return;
    loadReport(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load from meta only
  }, [meta.periods.length]);

  const categories = report?.categories || [
    { value: "all", label: "All categories" },
    { value: "w2", label: "W-2 Employee" },
    { value: "contractor_1099", label: "1099 Contractor" },
    { value: "temp", label: "Temp / One-Time" },
  ];
  const payrollStatuses = report?.payroll_statuses || [
    { value: "all", label: "All payroll statuses" },
  ];
  const paymentStatuses = report?.payment_statuses || [
    { value: "all", label: "All payment statuses" },
  ];

  const rows = report?.rows || [];
  const totals = report?.totals || {};
  const dateRule = report?.date_match_rule || meta.date_match_rule;

  const periodOptions = useMemo(
    () =>
      (meta.periods || []).map((p) => ({
        value: `${p.pay_period_start}|${p.pay_period_end}`,
        label: p.label || `${p.pay_period_start} – ${p.pay_period_end}`,
      })),
    [meta.periods],
  );

  const applyFilters = () => {
    if (filters.rangeMode === "date_range") {
      if (!filters.dateFrom || !filters.dateTo) {
        setError("Select both a start date and an end date for the custom range.");
        return;
      }
      if (filters.dateFrom > filters.dateTo) {
        setError("Start date must be on or before end date.");
        return;
      }
    }
    if (filters.rangeMode === "period" && !filters.selectedPeriods.length) {
      setError("Select at least one payroll period, or switch to All payroll history.");
      return;
    }
    loadReport(filters);
  };

  const clearFilters = () => {
    const next = {
      ...EMPTY_FILTERS,
      selectedPeriods: periodOptions[0] ? [periodOptions[0].value] : [],
    };
    setFilters(next);
    loadReport(next);
  };

  const downloadExcel = async () => {
    setExporting("xlsx");
    setError("");
    try {
      const res = await getPayrollReportExcel(buildQueryParams(applied));
      const blob = new Blob([res.data], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "payroll-report.xlsx";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Excel export failed");
    } finally {
      setExporting("");
    }
  };

  const downloadPdf = async () => {
    setExporting("pdf");
    setError("");
    try {
      const res = await getPayrollReportPdfHtml(buildQueryParams(applied));
      const html = typeof res.data === "string" ? res.data : String(res.data ?? "");
      const ok = await downloadHtmlDocumentPdf(html, {
        pageSize: "letter landscape",
        filename: "payroll-report.pdf",
      });
      if (!ok) throw new Error("PDF generation failed");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "PDF export failed");
    } finally {
      setExporting("");
    }
  };

  const patch = (p) => setFilters((f) => ({ ...f, ...p }));

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}

      <Paper
        variant="outlined"
        sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}
      >
        <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark, mb: 0.5 }}>
          Payroll Report
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Payroll records across all periods and employee categories (W-2, 1099, temp).
          Exports use the filters currently applied.
        </Typography>

        <Stack spacing={2}>
          <FormControl size="small" sx={{ minWidth: 220, maxWidth: 320 }}>
            <InputLabel>Report scope</InputLabel>
            <Select
              label="Report scope"
              value={filters.rangeMode}
              onChange={(e) => patch({ rangeMode: e.target.value })}
            >
              {RANGE_MODES.map((m) => (
                <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
              ))}
            </Select>
          </FormControl>

          {filters.rangeMode === "period" ? (
            <FormControl size="small" sx={{ minWidth: 280, maxWidth: 480 }}>
              <InputLabel>Payroll period(s)</InputLabel>
              <Select
                multiple
                label="Payroll period(s)"
                value={filters.selectedPeriods}
                onChange={(e) =>
                  patch({
                    selectedPeriods:
                      typeof e.target.value === "string"
                        ? e.target.value.split(",")
                        : e.target.value,
                  })
                }
                input={<OutlinedInput label="Payroll period(s)" />}
                renderValue={(selected) =>
                  selected
                    .map((v) => periodOptions.find((o) => o.value === v)?.label || v)
                    .join(", ")
                }
              >
                {periodOptions.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    <Checkbox checked={filters.selectedPeriods.includes(o.value)} />
                    <ListItemText primary={o.label} />
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}

          {filters.rangeMode === "date_range" ? (
            <Paper variant="outlined" sx={{ p: 1.5, bgcolor: "grey.50" }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                Custom Date Range
              </Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems="flex-end">
                <PayrollDateField
                  label="Start date"
                  value={filters.dateFrom}
                  onChange={(v) => patch({ dateFrom: v })}
                  size="small"
                />
                <PayrollDateField
                  label="End date"
                  value={filters.dateTo}
                  onChange={(v) => patch({ dateTo: v })}
                  size="small"
                />
                <Button variant="contained" onClick={applyFilters} disabled={loading}>
                  Apply
                </Button>
                <Button variant="outlined" onClick={clearFilters} disabled={loading}>
                  Clear
                </Button>
              </Stack>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                {dateRule ||
                  "Includes rows where the pay period overlaps the selected range, or the pay date falls within the selected range."}
              </Typography>
            </Paper>
          ) : null}

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} flexWrap="wrap" useFlexGap>
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel>Employee</InputLabel>
              <Select
                label="Employee"
                value={filters.userId}
                onChange={(e) => patch({ userId: e.target.value })}
              >
                <MenuItem value="">All employees</MenuItem>
                {(meta.employees || []).map((e) => (
                  <MenuItem key={e.user_id} value={String(e.user_id)}>
                    {e.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Employee category</InputLabel>
              <Select
                label="Employee category"
                value={filters.workerCategory}
                onChange={(e) => patch({ workerCategory: e.target.value })}
              >
                {categories.map((c) => (
                  <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Payroll status</InputLabel>
              <Select
                label="Payroll status"
                value={filters.payrollStatus}
                onChange={(e) => patch({ payrollStatus: e.target.value })}
              >
                {payrollStatuses.map((c) => (
                  <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Payment status</InputLabel>
              <Select
                label="Payment status"
                value={filters.paymentStatus}
                onChange={(e) => patch({ paymentStatus: e.target.value })}
              >
                {paymentStatuses.map((c) => (
                  <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          {filters.rangeMode !== "date_range" ? (
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={applyFilters} disabled={loading}>
                Apply filters
              </Button>
              <Button variant="outlined" onClick={clearFilters} disabled={loading}>
                Clear / reset
              </Button>
            </Stack>
          ) : null}
        </Stack>
      </Paper>

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
        <Button
          variant="outlined"
          startIcon={<DownloadIcon />}
          onClick={downloadExcel}
          disabled={!rows.length || Boolean(exporting)}
        >
          {exporting === "xlsx" ? "Exporting…" : "Download Excel"}
        </Button>
        <Button
          variant="outlined"
          startIcon={<PictureAsPdfIcon />}
          onClick={downloadPdf}
          disabled={!rows.length || Boolean(exporting)}
        >
          {exporting === "pdf" ? "Exporting…" : "Download PDF"}
        </Button>
        <Typography variant="caption" color="text.secondary">
          OT Premium = OT hours x (OT rate - regular rate). Gross pay is unchanged.
        </Typography>
      </Stack>

      <Paper variant="outlined">
        <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider" }}>
          <Typography variant="subtitle2" fontWeight={700}>
            Results{report ? ` · ${report.count ?? rows.length} records` : ""}
          </Typography>
          {dateRule && applied.rangeMode === "date_range" ? (
            <Typography variant="caption" color="text.secondary" display="block">
              Date rule: {dateRule}
            </Typography>
          ) : null}
        </Box>
        {loading ? (
          <Box sx={{ p: 2 }}>
            <Typography color="text.secondary">Loading…</Typography>
          </Box>
        ) : (
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small" sx={{ minWidth: 1600 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Employee</TableCell>
                  <TableCell>Category</TableCell>
                  <TableCell>Payroll period</TableCell>
                  <TableCell>Pay date</TableCell>
                  <TableCell align="right">Reg hrs</TableCell>
                  <TableCell align="right">OT Hours</TableCell>
                  <TableCell align="right">Regular/Base Earnings</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end">
                      <span>OT Premium</span>
                      <Tooltip title={OT_PREMIUM_TOOLTIP}>
                        <InfoOutlinedIcon sx={{ fontSize: 14, color: "text.secondary" }} />
                      </Tooltip>
                    </Stack>
                  </TableCell>
                  <TableCell align="right">Other Earnings</TableCell>
                  <TableCell align="right">Gross Pay</TableCell>
                  <TableCell align="right">Employee tax</TableCell>
                  <TableCell align="right">Other deductions</TableCell>
                  <TableCell align="right">Net pay</TableCell>
                  <TableCell align="right">Employer taxes</TableCell>
                  <TableCell>Payment status</TableCell>
                  <TableCell>Payroll status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={`${row.batch_id}-${row.line_id}`} hover>
                    <TableCell>{row.employee_name}</TableCell>
                    <TableCell>{row.employee_category}</TableCell>
                    <TableCell>{row.payroll_period}</TableCell>
                    <TableCell>{row.pay_date}</TableCell>
                    <TableCell align="right">{hours(row.regular_hours)}</TableCell>
                    <TableCell align="right">{hours(row.ot_hours)}</TableCell>
                    <TableCell align="right">{money(row.base_earnings)}</TableCell>
                    <TableCell align="right">
                      {Number(row.ot_hours) > 0 ? money(row.ot_premium) : ""}
                    </TableCell>
                    <TableCell align="right">
                      {Number(row.other_earnings) ? money(row.other_earnings) : ""}
                    </TableCell>
                    <TableCell align="right">{money(row.gross_pay)}</TableCell>
                    <TableCell align="right">{money(row.employee_tax_deductions)}</TableCell>
                    <TableCell align="right">{money(row.other_deductions)}</TableCell>
                    <TableCell align="right">{money(row.net_pay)}</TableCell>
                    <TableCell align="right">{money(row.employer_taxes)}</TableCell>
                    <TableCell>{row.payment_status}</TableCell>
                    <TableCell>{row.payroll_status}</TableCell>
                  </TableRow>
                ))}
                {rows.length ? (
                  <TableRow>
                    <TableCell sx={{ fontWeight: 700 }}>Totals</TableCell>
                    <TableCell colSpan={3} />
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {hours(totals.regular_hours)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {hours(totals.ot_hours)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.base_earnings)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.ot_premium)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.other_earnings)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.gross_pay)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.employee_tax_deductions)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.other_deductions)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.net_pay)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.employer_taxes)}
                    </TableCell>
                    <TableCell colSpan={2} />
                  </TableRow>
                ) : (
                  <TableRow>
                    <TableCell colSpan={16}>
                      <Typography variant="body2" color="text.secondary">
                        No payroll records match the current filters.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>
    </Stack>
  );
}
