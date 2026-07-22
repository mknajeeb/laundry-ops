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
  getPayrollReportCsv,
  getPayrollReportExcel,
  getPayrollReportMeta,
  getPayrollReportPdfHtml,
} from "../api";
import { downloadHtmlDocumentPdf } from "../contractorForms/contractorPrint";
import {
  OT_PREMIUM_TOOLTIP,
} from "../payroll/payrollOtDisplay";
import {
  distinctPayDates,
  distinctPayrollPeriods,
  groupMonthlyPaidRows,
} from "../payroll/payrollReportGroups";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import PayrollReportAnalyticsDashboard from "./PayrollReportAnalyticsDashboard";

const RANGE_MODES = [
  { value: "period", label: "Payroll Period Report", reportType: "payroll_period" },
  {
    value: "monthly_paid",
    label: "Monthly Payroll Paid",
    reportType: "monthly_paid",
  },
  {
    value: "date_range",
    label: "Custom Date Range (coming soon)",
    reportType: "custom_range",
    disabled: true,
  },
  {
    value: "labor_cost",
    label: "Labor Cost Analysis (coming soon)",
    reportType: "labor_cost",
    disabled: true,
  },
  { value: "all_history", label: "All payroll history", reportType: "all_history" },
];

const MONTH_OPTIONS = [
  { value: 1, label: "January" },
  { value: 2, label: "February" },
  { value: 3, label: "March" },
  { value: 4, label: "April" },
  { value: 5, label: "May" },
  { value: 6, label: "June" },
  { value: 7, label: "July" },
  { value: 8, label: "August" },
  { value: 9, label: "September" },
  { value: 10, label: "October" },
  { value: 11, label: "November" },
  { value: 12, label: "December" },
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
  const mode = RANGE_MODES.find((m) => m.value === filters.rangeMode);
  const params = {
    report_type: mode?.reportType || "payroll_period",
  };
  if (filters.rangeMode === "all_history") {
    params.all_history = "1";
  } else if (filters.rangeMode === "monthly_paid") {
    if (filters.month) params.month = filters.month;
    if (filters.year) params.year = filters.year;
  } else if (filters.rangeMode === "date_range") {
    if (filters.dateFrom) params.date_from = filters.dateFrom;
    if (filters.dateTo) params.date_to = filters.dateTo;
    params.date_basis = filters.dateBasis || "pay_date";
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
  if (filters.comparisonRange) {
    params.comparison_range = filters.comparisonRange;
  }
  return params;
}

const now = new Date();
const EMPTY_FILTERS = {
  rangeMode: "period",
  selectedPeriods: [],
  dateFrom: "",
  dateTo: "",
  dateBasis: "pay_date",
  month: now.getMonth() + 1,
  year: now.getFullYear(),
  userId: "",
  workerCategory: "all",
  payrollStatus: "all",
  paymentStatus: "all",
  comparisonRange: 4,
};

export default function PayrollReportPanel({ viewMode = "dashboard" }) {
  const dashboardPrimary = viewMode !== "report";
  const [meta, setMeta] = useState({
    employees: [],
    periods: [],
    date_match_rule: "",
    can_view_employee_detail: true,
  });
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");
  const [showDashboard, setShowDashboard] = useState(dashboardPrimary);

  useEffect(() => {
    getPayrollReportMeta()
      .then((res) => {
        setMeta({
          employees: res.data?.employees || [],
          periods: res.data?.periods || [],
          date_match_rule: res.data?.date_match_rule || "",
          can_view_employee_detail: res.data?.can_view_employee_detail !== false,
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

  const rows = useMemo(() => report?.rows || [], [report]);
  const totals = report?.totals || {};
  const dateRule = report?.date_match_rule || meta.date_match_rule;
  const canViewEmployeeDetail = meta.can_view_employee_detail !== false;
  const isMonthlyPaid = applied.rangeMode === "monthly_paid";
  const monthlyGroups = useMemo(
    () => (isMonthlyPaid ? groupMonthlyPaidRows(rows) : []),
    [isMonthlyPaid, rows],
  );
  const payDatesInMonth = useMemo(() => distinctPayDates(rows), [rows]);
  const periodsInMonth = useMemo(() => distinctPayrollPeriods(rows), [rows]);

  const sumRows = (groupRows) =>
    (groupRows || []).reduce(
      (acc, row) => {
        for (const k of Object.keys(acc)) {
          acc[k] += Number(row[k]) || 0;
        }
        return acc;
      },
      {
        regular_hours: 0,
        ot_hours: 0,
        base_earnings: 0,
        ot_premium: 0,
        other_earnings: 0,
        gross_pay: 0,
        employee_tax_deductions: 0,
        other_deductions: 0,
        net_pay: 0,
        amount_paid: 0,
        outstanding_balance: 0,
        employer_taxes: 0,
        total_payroll_cost: 0,
      },
    );

  const renderEmployeeTable = (tableRows, subTotals) => (
    <TableContainer sx={{ overflowX: "auto" }}>
      <Table size="small" sx={{ minWidth: 1600 }}>
        <TableHead>
          <TableRow>
            <TableCell>Employee</TableCell>
            <TableCell>Category</TableCell>
            <TableCell>Pay Date</TableCell>
            <TableCell align="right">Reg hrs</TableCell>
            <TableCell align="right">OT hrs</TableCell>
            <TableCell align="right">Base</TableCell>
            <TableCell align="right">OT prem</TableCell>
            <TableCell align="right">Gross</TableCell>
            <TableCell align="right">EE taxes</TableCell>
            <TableCell align="right">Net</TableCell>
            <TableCell align="right">ER taxes</TableCell>
            <TableCell align="right">Total cost</TableCell>
            <TableCell>Payment</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {tableRows.map((row) => (
            <TableRow key={`${row.batch_id}-${row.line_id}`} hover>
              <TableCell>{row.employee_name}</TableCell>
              <TableCell>{row.employee_category}</TableCell>
              <TableCell>{row.pay_date_display || row.pay_date || ""}</TableCell>
              <TableCell align="right">{hours(row.regular_hours)}</TableCell>
              <TableCell align="right">{hours(row.ot_hours)}</TableCell>
              <TableCell align="right">{money(row.base_earnings)}</TableCell>
              <TableCell align="right">
                {Number(row.ot_hours) > 0 ? money(row.ot_premium) : money(0)}
              </TableCell>
              <TableCell align="right">{money(row.gross_pay)}</TableCell>
              <TableCell align="right">{money(row.employee_tax_deductions)}</TableCell>
              <TableCell align="right">{money(row.net_pay)}</TableCell>
              <TableCell align="right">{money(row.employer_taxes)}</TableCell>
              <TableCell align="right">{money(row.total_payroll_cost)}</TableCell>
              <TableCell>{row.payment_status}</TableCell>
            </TableRow>
          ))}
          <TableRow>
            <TableCell sx={{ fontWeight: 700 }}>Subtotal</TableCell>
            <TableCell colSpan={2} />
            <TableCell align="right" sx={{ fontWeight: 700 }}>{hours(subTotals.regular_hours)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{hours(subTotals.ot_hours)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.base_earnings)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.ot_premium)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.gross_pay)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.employee_tax_deductions)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.net_pay)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.employer_taxes)}</TableCell>
            <TableCell align="right" sx={{ fontWeight: 700 }}>{money(subTotals.total_payroll_cost)}</TableCell>
            <TableCell />
          </TableRow>
        </TableBody>
      </Table>
    </TableContainer>
  );

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
    if (filters.rangeMode === "monthly_paid") {
      if (!filters.month || !filters.year) {
        setError("Select a month and year for Monthly Payroll Paid.");
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

  const downloadCsv = async () => {
    setExporting("csv");
    setError("");
    try {
      const res = await getPayrollReportCsv(buildQueryParams(applied));
      const blob = new Blob([res.data], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "payroll-report.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "CSV export failed");
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

  const dynamicHeading = useMemo(() => {
    if (report?.report_heading) return report.report_heading;
    if (applied.rangeMode === "all_history") return "Payroll Reports — All History";
    if (applied.rangeMode === "monthly_paid") {
      const monthLabel = MONTH_OPTIONS.find((m) => m.value === applied.month)?.label || applied.month;
      return `Monthly Payroll Paid: ${monthLabel} ${applied.year}`;
    }
    if (applied.rangeMode === "date_range" && applied.dateFrom && applied.dateTo) {
      const basis =
        applied.dateBasis === "period_overlap" ? "Payroll Period Overlap" : "Pay Date";
      return `Payroll Report: ${applied.dateFrom} – ${applied.dateTo} (${basis} Basis)`;
    }
    if (applied.rangeMode === "period" && applied.selectedPeriods?.length === 1) {
      const [ps, pe] = applied.selectedPeriods[0].split("|");
      return `Payroll Period: ${ps} – ${pe}`;
    }
    if (applied.rangeMode === "period" && applied.selectedPeriods?.length > 1) {
      return `Payroll Period Report (${applied.selectedPeriods.length} periods)`;
    }
    return "Payroll Reports";
  }, [report, applied]);

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>{error}</Alert>
      ) : null}

      <Paper
        variant="outlined"
        sx={{ p: 1.5, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "baseline" }}
          spacing={0.5}
          sx={{ mb: 1 }}
        >
          <Box>
            <Typography variant="subtitle1" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
              {dashboardPrimary ? "Payroll Dashboard" : "Payroll Reports"}
            </Typography>
            <Typography variant="body2" fontWeight={600} sx={{ color: VEEWASH_BRAND.inkSoft }}>
              {dynamicHeading}
            </Typography>
          </Box>
        </Stack>

        <Stack spacing={1}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
            <FormControl size="small" sx={{ minWidth: 200, flex: { md: "1 1 200px" } }}>
              <InputLabel>Report type</InputLabel>
              <Select
                label="Report type"
                value={filters.rangeMode}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "labor_cost" || v === "date_range") return;
                  const next = { ...filters, rangeMode: v };
                  setFilters(next);
                  if (v === "monthly_paid" || v === "all_history") {
                    loadReport(next);
                  }
                }}
              >
                {RANGE_MODES.map((m) => (
                  <MenuItem key={m.value} value={m.value} disabled={Boolean(m.disabled)}>
                    {m.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {filters.rangeMode === "period" ? (
              <FormControl size="small" sx={{ minWidth: 220, flex: { md: "1 1 240px" } }}>
                <InputLabel>Payroll period</InputLabel>
                <Select
                  multiple
                  label="Payroll period"
                  value={filters.selectedPeriods}
                  onChange={(e) =>
                    patch({
                      selectedPeriods:
                        typeof e.target.value === "string"
                          ? e.target.value.split(",")
                          : e.target.value,
                    })
                  }
                  input={<OutlinedInput label="Payroll period" />}
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

            {filters.rangeMode === "monthly_paid" ? (
              <>
                <FormControl size="small" sx={{ minWidth: 140 }}>
                  <InputLabel>Month</InputLabel>
                  <Select
                    label="Month"
                    value={filters.month}
                    onChange={(e) => {
                      const month = Number(e.target.value);
                      const next = { ...filters, month };
                      setFilters(next);
                      if (filters.rangeMode === "monthly_paid") loadReport(next);
                    }}
                  >
                    {MONTH_OPTIONS.map((m) => (
                      <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ minWidth: 100 }}>
                  <InputLabel>Year</InputLabel>
                  <Select
                    label="Year"
                    value={filters.year}
                    onChange={(e) => {
                      const year = Number(e.target.value);
                      const next = { ...filters, year };
                      setFilters(next);
                      if (filters.rangeMode === "monthly_paid") loadReport(next);
                    }}
                  >
                    {[filters.year - 1, filters.year, filters.year + 1]
                      .filter((y, i, arr) => arr.indexOf(y) === i)
                      .map((y) => (
                        <MenuItem key={y} value={y}>{y}</MenuItem>
                      ))}
                  </Select>
                </FormControl>
              </>
            ) : null}

            {canViewEmployeeDetail ? (
              <FormControl size="small" sx={{ minWidth: 160, flex: { md: "1 1 160px" } }}>
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
            ) : null}

            <FormControl size="small" sx={{ minWidth: 150, flex: { md: "1 1 150px" } }}>
              <InputLabel>Category</InputLabel>
              <Select
                label="Category"
                value={filters.workerCategory}
                onChange={(e) => patch({ workerCategory: e.target.value })}
              >
                {categories.map((c) => (
                  <MenuItem key={c.value} value={c.value}>{c.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150, flex: { md: "1 1 150px" } }}>
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
            <FormControl size="small" sx={{ minWidth: 150, flex: { md: "1 1 150px" } }}>
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

          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button size="small" variant="contained" onClick={applyFilters} disabled={loading}>
              Apply
            </Button>
            <Button size="small" variant="outlined" onClick={clearFilters} disabled={loading}>
              Reset
            </Button>
            {filters.rangeMode === "monthly_paid" ? (
              <Typography variant="caption" color="text.secondary">
                Batches without Official Pay Date are excluded. Incomplete (open/draft) periods are hidden.
              </Typography>
            ) : (
              <Typography variant="caption" color="text.secondary">
                Periods appear only when all batches for that week are paid or finalized.
              </Typography>
            )}
          </Stack>
        </Stack>
      </Paper>

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
        <Button
          variant="outlined"
          startIcon={<DownloadIcon />}
          onClick={downloadExcel}
          disabled={
            Boolean(exporting) ||
            (!rows.length && !report?.employee_detail_restricted && !report?.analytics)
          }
        >
          {exporting === "xlsx" ? "Exporting…" : "Download Excel"}
        </Button>
        <Button
          variant="outlined"
          startIcon={<DownloadIcon />}
          onClick={downloadCsv}
          disabled={
            Boolean(exporting) ||
            (!rows.length && !report?.employee_detail_restricted)
          }
        >
          {exporting === "csv" ? "Exporting…" : "Download CSV"}
        </Button>
        <Button
          variant="outlined"
          startIcon={<PictureAsPdfIcon />}
          onClick={downloadPdf}
          disabled={
            Boolean(exporting) ||
            (!rows.length && !report?.employee_detail_restricted && !report?.analytics)
          }
        >
          {exporting === "pdf" ? "Exporting…" : "Download PDF"}
        </Button>
        <Button
          variant="text"
          onClick={() => setShowDashboard((v) => !v)}
          disabled={!report?.analytics}
        >
          {showDashboard ? "Hide Dashboard" : "Show Dashboard"}
        </Button>
        <Typography variant="caption" color="text.secondary">
          OT Premium = OT hours × (OT rate − regular rate). Gross includes OT premium. PDF always
          includes the analytics dashboard.
        </Typography>
      </Stack>

      {showDashboard && report?.analytics ? (
        <Paper
          variant="outlined"
          sx={{ p: 2, borderTop: `3px solid ${VEEWASH_BRAND.primary}` }}
        >
          <PayrollReportAnalyticsDashboard
            analytics={report.analytics}
            summary={report.summary}
            comparisonRange={applied.comparisonRange || 4}
            onComparisonRangeChange={(n) => {
              const next = { ...filters, comparisonRange: n };
              setFilters(next);
              loadReport(next);
            }}
          />
        </Paper>
      ) : null}

      {report?.employee_detail_restricted ? (
        <Alert severity="info">{report.employee_detail_message || "You do not have permission to view employee payroll details."}</Alert>
      ) : null}

      {!dashboardPrimary || !showDashboard ? (
      <Paper variant="outlined">
        <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: "divider" }}>
          <Typography variant="subtitle2" fontWeight={700}>
            {dynamicHeading}
            {report ? ` · ${report.count ?? rows.length} records` : ""}
          </Typography>
          {report?.summary ? (
            <Typography variant="caption" color="text.secondary" display="block">
              Periods: {report.summary.payroll_period_count ?? periodsInMonth.length ?? "—"} ·
              Pay dates: {report.summary.official_pay_date_count ?? payDatesInMonth.length ?? "—"} ·
              Workers: {report.summary.unique_employees ?? "—"} · Gross: {money(totals.gross_pay)} ·
              EE taxes: {money(totals.employee_tax_deductions)} · Net: {money(totals.net_pay)} ·
              Employer taxes: {money(totals.employer_taxes)} · Total payroll cost:{" "}
              {money(totals.total_payroll_cost)}
            </Typography>
          ) : null}
          {dateRule ? (
            <Typography variant="caption" color="text.secondary" display="block">
              {dateRule}
            </Typography>
          ) : null}
          {report?.excluded_missing_pay_date_count ? (
            <Typography variant="caption" color="warning.main" display="block">
              {report.excluded_missing_pay_date_count} line(s) excluded — Pay Date Missing.
            </Typography>
          ) : null}
          {isMonthlyPaid && (periodsInMonth.length || payDatesInMonth.length) ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              Grouped by Payroll Period → Pay Date · {periodsInMonth.length} period
              {periodsInMonth.length === 1 ? "" : "s"} · {payDatesInMonth.length} Official Pay Date
              {payDatesInMonth.length === 1 ? "" : "s"}
              {payDatesInMonth.length ? `: ${payDatesInMonth.join(", ")}` : ""}
            </Typography>
          ) : null}
        </Box>
        {loading ? (
          <Box sx={{ p: 2 }}>
            <Typography color="text.secondary">Loading…</Typography>
          </Box>
        ) : isMonthlyPaid && monthlyGroups.length ? (
          <Stack spacing={2.5} sx={{ p: 2 }}>
            {monthlyGroups.map((group) => {
              const periodTotals = sumRows(group.rows);
              return (
                <Box key={group.heading}>
                  <Typography
                    variant="subtitle1"
                    fontWeight={800}
                    sx={{ color: VEEWASH_BRAND.primaryDark, mb: 0.5 }}
                  >
                    {group.heading}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                    Pay dates: {(group.payDates || []).length} · Workers: {group.rows.length} ·
                    Gross: {money(periodTotals.gross_pay)} · EE taxes:{" "}
                    {money(periodTotals.employee_tax_deductions)} · Net: {money(periodTotals.net_pay)} ·
                    ER taxes: {money(periodTotals.employer_taxes)} · Total cost:{" "}
                    {money(periodTotals.total_payroll_cost)}
                  </Typography>
                  <Stack spacing={2}>
                    {(group.payDates || []).map((pd) => {
                      const gTotals = sumRows(pd.rows);
                      return (
                        <Box key={`${group.period}-${pd.payDate}`} sx={{ pl: { xs: 0, sm: 1 } }}>
                          <Typography
                            variant="subtitle2"
                            fontWeight={700}
                            sx={{ color: VEEWASH_BRAND.ink, mb: 0.5 }}
                          >
                            {pd.heading}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                            Employees: {pd.rows.length} · Gross: {money(gTotals.gross_pay)}
                          </Typography>
                          {renderEmployeeTable(pd.rows, gTotals)}
                        </Box>
                      );
                    })}
                  </Stack>
                </Box>
              );
            })}
            <Typography variant="subtitle2" fontWeight={700} sx={{ pt: 1 }}>
              Month totals · Gross: {money(totals.gross_pay)} · EE taxes:{" "}
              {money(totals.employee_tax_deductions)} · Net: {money(totals.net_pay)} · Total
              payroll cost: {money(totals.total_payroll_cost)}
            </Typography>
          </Stack>
        ) : (
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small" sx={{ minWidth: 1700 }}>
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
                  <TableCell align="right">Total payroll cost</TableCell>
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
                    <TableCell>
                      {row.pay_date_display || row.pay_date || (row.pay_date_missing ? "Pay Date Missing" : "")}
                    </TableCell>
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
                    <TableCell align="right">{money(row.total_payroll_cost)}</TableCell>
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
                    <TableCell align="right" sx={{ fontWeight: 700 }}>
                      {money(totals.total_payroll_cost)}
                    </TableCell>
                    <TableCell colSpan={2} />
                  </TableRow>
                ) : (
                  <TableRow>
                    <TableCell colSpan={19}>
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
      ) : null}
    </Stack>
  );
}
