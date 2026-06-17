import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Collapse,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { getEmployeeProductivityDashboard } from "../../api";
import { formatIsoEtWall } from "../../utils/rinseTimeFormat";
import { yesterdayRange, todayRange } from "../../utils/foldingDateRange";
import {
  PRODUCTIVITY_RANK_OPTIONS,
  PERFORMANCE_TIER_STYLES,
  buildExecutiveSummaryCards,
  fmtAvgLbsPerBag,
  fmtProductivityRate,
  fmtSummaryNumber,
  isMissingClockIn,
  rankEmployees,
} from "../../utils/employeeProductivityHelpers";
import EmployeeProductivityDrilldown, {
  EmployeeProductivityDrilldownCollapse,
} from "./EmployeeProductivityDrilldown";
import MetricCardGrid from "./MetricCardGrid";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET Date" },
];

function EmployeeSummaryPanel({ emp }) {
  const missingClockIn = isMissingClockIn(emp);
  const productiveHrs = emp.productive_hours ?? emp.worked_hours;
  const items = [
    { label: "Clock In", value: missingClockIn ? "Missing clock-in" : formatIsoEtWall(emp.clock_in_time_et || emp.clock_in_time) },
    { label: "Last Completion", value: formatIsoEtWall(emp.last_completion_time_et || emp.last_completion_time) },
    { label: "Productive Hours", value: missingClockIn ? "N/A" : fmtSummaryNumber(productiveHrs, 2) },
    { label: "Bags", value: emp.completed_bags ?? 0 },
    { label: "Pounds", value: emp.total_completed_lbs ?? 0 },
    { label: "Bags / Hr", value: fmtProductivityRate(emp.bags_per_hour, missingClockIn) },
    { label: "Lbs / Hr", value: fmtProductivityRate(emp.lbs_per_hour, missingClockIn) },
  ];

  return (
    <Box
      sx={{
        mb: 1.25,
        p: 1.25,
        borderRadius: 1.5,
        border: "1px solid",
        borderColor: "divider",
        bgcolor: "#f8fafc",
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
        Employee Summary
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", sm: "repeat(4, minmax(0, 1fr))" },
          gap: 1,
        }}
      >
        {items.map((item) => (
          <Box key={item.label} sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={700} display="block">
              {item.label}
            </Typography>
            <Typography variant="body2" fontWeight={700} sx={{ wordBreak: "break-word" }}>
              {item.value ?? "—"}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function EmployeeMobileCard({ emp, open, onToggle, selectedDate, loading }) {
  const missingClockIn = isMissingClockIn(emp);
  const tier = PERFORMANCE_TIER_STYLES[emp.performance_tier] || PERFORMANCE_TIER_STYLES.middle;
  const productiveHrs = emp.productive_hours ?? emp.worked_hours;

  return (
    <Paper
      variant="outlined"
      sx={{
        borderRadius: 2,
        overflow: "hidden",
        borderColor: tier.borderColor !== "transparent" ? tier.borderColor : "divider",
        bgcolor: tier.bgcolor,
      }}
    >
      <Box
        onClick={onToggle}
        sx={{ p: 1.25, cursor: "pointer" }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="caption" fontWeight={800} sx={{ color: tier.rankColor }}>
                #{emp.productivity_rank ?? "—"}
              </Typography>
              <Typography variant="subtitle1" fontWeight={800} sx={{ wordBreak: "break-word" }}>
                {emp.employee}
              </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {emp.completed_bags ?? 0} bags · {emp.total_completed_lbs ?? 0} lbs · {fmtAvgLbsPerBag(emp)} avg lbs/bag
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {fmtProductivityRate(emp.bags_per_hour, missingClockIn)} bags/hr · {fmtProductivityRate(emp.lbs_per_hour, missingClockIn)} lbs/hr · {missingClockIn ? "N/A" : fmtSummaryNumber(productiveHrs, 2)} hrs
            </Typography>
          </Box>
          <ExpandMoreIcon
            fontSize="small"
            sx={{
              transform: open ? "rotate(180deg)" : "none",
              transition: "transform 0.2s",
              color: "text.secondary",
              flexShrink: 0,
            }}
          />
        </Stack>
      </Box>
      <EmployeeProductivityDrilldownCollapse open={open}>
        <Box sx={{ px: 1.25, pb: 1.25 }}>
          <EmployeeSummaryPanel emp={emp} />
          <EmployeeProductivityDrilldown
            bags={emp.bags}
            referenceDateEt={selectedDate}
            loading={loading}
          />
        </Box>
      </EmployeeProductivityDrilldownCollapse>
    </Paper>
  );
}

/**
 * Phase 2 — Employee Productivity Dashboard.
 * Reads frozen Phase 1 `employee_completed_bags_today` only.
 * Ranking is client-side; date changes fetch this section only.
 */
export default function EmployeeProductivityDashboard({
  initialSection,
  initialDateEt,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [expandedEmployee, setExpandedEmployee] = useState(null);
  const [reconOpen, setReconOpen] = useState(false);
  const [rankBy, setRankBy] = useState("bags");
  const [datePreset, setDatePreset] = useState(() => resolvePreset(initialDateEt));
  const [customDate, setCustomDate] = useState(initialDateEt || todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(initialDateEt || todayRange().start);
  const [section, setSection] = useState(initialSection || null);
  const [scopeLabel, setScopeLabel] = useState(initialSection?.productivity_scope_label || "WF Only");
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState("");

  const fetchSection = useCallback(async (dateEt) => {
    if (!dateEt) return;
    setLoading(true);
    setFetchError("");
    try {
      const res = await getEmployeeProductivityDashboard({ date_et: dateEt });
      setSection(res.data?.employee_completed_bags_today || null);
      setScopeLabel(
        res.data?.productivity_scope_label
          || res.data?.employee_completed_bags_today?.productivity_scope_label
          || "WF Only",
      );
      setActiveDateEt(dateEt);
    } catch (e) {
      setFetchError(e?.response?.data?.error || "Failed to load employee productivity");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSection(activeDateEt);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- load full bags on mount

  const employees = section?.employees || [];
  const executiveSummary = section?.executive_summary || {};
  const recon = section?.reconciliation || {};
  const banner = section?.reconciliation_banner || recon;
  const reconciled = banner.status === "reconciled" || recon.ok === true;
  const credited = banner.employee_completed_bags_credited ?? recon.employee_attributed_bag_count ?? 0;
  const workload = banner.workload_completed_today ?? recon.workload_completed_today ?? 0;
  const selectedDate = section?.selected_date_et || activeDateEt;
  const productivityScopeLabel = section?.productivity_scope_label || scopeLabel || "WF Only";

  const rankedEmployees = useMemo(
    () => rankEmployees(employees, rankBy),
    [employees, rankBy],
  );

  const kpiCards = useMemo(
    () => buildExecutiveSummaryCards(executiveSummary, productivityScopeLabel),
    [executiveSummary, productivityScopeLabel],
  );

  const applyDate = (isoDate) => {
    if (!isoDate) return;
    setActiveDateEt(isoDate);
    setExpandedEmployee(null);
    fetchSection(isoDate);
  };

  const handleDatePreset = (_, value) => {
    if (!value) return;
    setDatePreset(value);
    if (value === "today") applyDate(todayRange().start);
    else if (value === "yesterday") applyDate(yesterdayRange().start);
    else if (value === "custom") setCustomDate(activeDateEt);
  };

  if (!section && !loading && !fetchError) return null;

  return (
    <Paper
      elevation={0}
      sx={{
        mt: 1.5,
        mb: 1.5,
        borderRadius: 2,
        overflow: "hidden",
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#ffffff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Box
        sx={{
          px: { xs: 1.25, sm: 1.75 },
          py: { xs: 1, sm: 1.25 },
          bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
          color: "#fff",
        }}
      >
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }} spacing={0.75}>
          <Box>
            <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.0625rem" }}>
              Employee Productivity Dashboard
            </Typography>
            <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block" }}>
              ET {selectedDate || activeDateEt}
            </Typography>
          </Box>
          <Chip
            size="small"
            label={`Productivity Scope: ${productivityScopeLabel}`}
            sx={{
              bgcolor: "rgba(255,255,255,0.14)",
              color: "#fff",
              fontWeight: 700,
              border: "1px solid rgba(255,255,255,0.35)",
            }}
          />
        </Stack>
      </Box>

      <Box sx={{ p: { xs: 1, sm: 1.25 } }}>
        <Box sx={{ mb: 1.25, display: "flex", flexWrap: "wrap", gap: 1, alignItems: "center" }}>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={datePreset}
            onChange={handleDatePreset}
            sx={{ flexWrap: "wrap" }}
          >
            {DATE_PRESETS.map((p) => (
              <ToggleButton key={p.id} value={p.id} sx={{ textTransform: "none", fontWeight: 600 }}>
                {p.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          {datePreset === "custom" ? (
            <>
              <TextField
                type="date"
                size="small"
                label="Custom ET Date"
                value={customDate || ""}
                onChange={(e) => setCustomDate(e.target.value)}
                InputLabelProps={{ shrink: true }}
                sx={{ width: 170 }}
              />
              <Typography
                component="button"
                type="button"
                onClick={() => customDate && applyDate(customDate)}
                disabled={loading || !customDate}
                sx={{
                  border: "1px solid",
                  borderColor: "divider",
                  borderRadius: 1,
                  px: 1.25,
                  py: 0.5,
                  fontSize: 13,
                  fontWeight: 600,
                  bgcolor: "background.paper",
                  cursor: loading || !customDate ? "not-allowed" : "pointer",
                }}
              >
                Apply
              </Typography>
            </>
          ) : null}
          {loading ? <CircularProgress size={18} /> : null}
        </Box>

        {fetchError ? (
          <Alert severity="error" sx={{ mb: 1.25 }}>{fetchError}</Alert>
        ) : null}

        <Box sx={{ mb: 1.5 }}>
          <MetricCardGrid
            sections={[
              {
                key: "kpi",
                layout: "kpi",
                cards: kpiCards.map((card) => ({
                  ...card,
                  count: card.value,
                  size: "kpi",
                })),
              },
            ]}
          />
        </Box>

        <Box sx={{ mb: 1.25 }}>
          <Typography
            variant="caption"
            color={reconciled ? "text.secondary" : "error.main"}
            onClick={() => setReconOpen((v) => !v)}
            sx={{
              cursor: "pointer",
              userSelect: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 0.35,
              fontWeight: 600,
            }}
          >
            <ExpandMoreIcon
              fontSize="inherit"
              sx={{
                transform: reconOpen ? "rotate(180deg)" : "rotate(-90deg)",
                transition: "transform 0.2s",
              }}
            />
            Reconciliation diagnostic
            {!reconOpen ? (
              <Typography component="span" variant="caption" color="inherit" sx={{ ml: 0.25 }}>
                · {banner.status_label || (reconciled ? "Reconciled" : "Mismatch")}
              </Typography>
            ) : null}
          </Typography>
          <Collapse in={reconOpen}>
            <Box
              sx={{
                mt: 0.75,
                p: 1,
                border: "1px solid",
                borderColor: reconciled ? "divider" : "error.light",
                borderRadius: 1.5,
                bgcolor: reconciled ? "grey.50" : "error.50",
              }}
            >
              <Typography variant="caption" display="block" color="text.secondary" sx={{ mb: 0.35 }}>
                Scope: {productivityScopeLabel}
              </Typography>
              <Typography variant="caption" display="block">
                Employee completed bags credited: {credited}
              </Typography>
              <Typography variant="caption" display="block">
                Workload completed: {workload}
              </Typography>
              <Typography variant="caption" display="block" fontWeight={700} sx={{ mt: 0.35 }}>
                Status: {banner.status_label || (reconciled ? "Reconciled ✓" : "Mismatch ✗")}
              </Typography>
              {recon.wf_count != null || recon.hd_count != null ? (
                <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.35 }}>
                  WF {recon.wf_count ?? "—"} · HD {recon.hd_count ?? "—"}
                  {recon.difference != null && recon.difference !== 0
                    ? ` · difference ${recon.difference}`
                    : ""}
                </Typography>
              ) : null}
              {(recon.missing_from_employee_dashboard?.length > 0
                || recon.extra_in_employee_dashboard?.length > 0
                || recon.duplicate_bag_ids?.length > 0) ? (
                <Typography variant="caption" color="error.main" display="block" sx={{ mt: 0.35, lineHeight: 1.4 }}>
                  {recon.missing_from_employee_dashboard?.length
                    ? `Missing from dashboard: ${recon.missing_from_employee_dashboard.join(", ")}. `
                    : ""}
                  {recon.extra_in_employee_dashboard?.length
                    ? `Extra in dashboard: ${recon.extra_in_employee_dashboard.join(", ")}. `
                    : ""}
                  {recon.duplicate_bag_ids?.length
                    ? `Duplicates: ${recon.duplicate_bag_ids.join(", ")}`
                    : ""}
                </Typography>
              ) : null}
            </Box>
          </Collapse>
        </Box>

        <Box sx={{ mb: 1.25 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
            Rank by
          </Typography>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={rankBy}
            onChange={(_, v) => v && setRankBy(v)}
            sx={{ flexWrap: "wrap", gap: 0.5 }}
          >
            {PRODUCTIVITY_RANK_OPTIONS.map((opt) => (
              <ToggleButton key={opt.id} value={opt.id} sx={{ textTransform: "none", fontWeight: 600 }}>
                {opt.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {isMobile ? (
          <Stack spacing={1}>
            {rankedEmployees.map((emp) => (
              <EmployeeMobileCard
                key={emp.employee}
                emp={emp}
                open={expandedEmployee === emp.employee}
                onToggle={() => setExpandedEmployee((prev) => (prev === emp.employee ? null : emp.employee))}
                selectedDate={selectedDate}
                loading={loading}
              />
            ))}
          </Stack>
        ) : (
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="medium" aria-label="Employee productivity dashboard">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 700, width: 52, py: 1.25 }}>Rank</TableCell>
                  <TableCell sx={{ fontWeight: 700, py: 1.25 }}>Employee</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25 }}>Bags</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25 }}>Lbs</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25, whiteSpace: "nowrap" }}>Avg Lbs / Bag</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25 }}>Bags / Hr</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25 }}>Lbs / Hr</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, py: 1.25, whiteSpace: "nowrap" }}>Productive Hours</TableCell>
                  <TableCell padding="checkbox" sx={{ py: 1.25 }} />
                </TableRow>
              </TableHead>
              <TableBody>
                {rankedEmployees.map((emp) => {
                  const open = expandedEmployee === emp.employee;
                  const missingClockIn = isMissingClockIn(emp);
                  const productiveHrs = emp.productive_hours ?? emp.worked_hours;
                  const tier = PERFORMANCE_TIER_STYLES[emp.performance_tier] || PERFORMANCE_TIER_STYLES.middle;
                  return (
                    <Fragment key={emp.employee}>
                      <TableRow
                        hover
                        onClick={() => setExpandedEmployee((prev) => (prev === emp.employee ? null : emp.employee))}
                        sx={{
                          cursor: "pointer",
                          bgcolor: tier.bgcolor,
                          "& td": {
                            borderBottom: open ? undefined : "1px solid",
                            borderColor: "divider",
                            py: 1.35,
                          },
                        }}
                      >
                        <TableCell sx={{ fontWeight: 800, color: tier.rankColor }}>
                          {emp.productivity_rank ?? "—"}
                        </TableCell>
                        <TableCell sx={{ fontWeight: 700 }}>{emp.employee}</TableCell>
                        <TableCell align="right">{emp.completed_bags ?? 0}</TableCell>
                        <TableCell align="right">
                          {emp.total_completed_lbs ?? 0}
                          {emp.missing_weight_count > 0 ? (
                            <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5, display: "block" }}>
                              ({emp.missing_weight_count} no wt)
                            </Typography>
                          ) : null}
                        </TableCell>
                        <TableCell align="right">{fmtAvgLbsPerBag(emp)}</TableCell>
                        <TableCell align="right">{fmtProductivityRate(emp.bags_per_hour, missingClockIn)}</TableCell>
                        <TableCell align="right">{fmtProductivityRate(emp.lbs_per_hour, missingClockIn)}</TableCell>
                        <TableCell align="right">
                          {missingClockIn ? "N/A" : fmtSummaryNumber(productiveHrs, 2)}
                        </TableCell>
                        <TableCell padding="checkbox">
                          <ExpandMoreIcon
                            fontSize="small"
                            sx={{
                              transform: open ? "rotate(180deg)" : "none",
                              transition: "transform 0.2s",
                              color: "text.secondary",
                            }}
                          />
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={9} sx={{ py: 0, borderBottom: open ? undefined : "none" }}>
                          <EmployeeProductivityDrilldownCollapse open={open}>
                            <Box sx={{ py: 1.25, px: 0.5 }}>
                              <EmployeeSummaryPanel emp={emp} />
                              <EmployeeProductivityDrilldown
                                bags={emp.bags}
                                referenceDateEt={selectedDate}
                                loading={loading}
                              />
                            </Box>
                          </EmployeeProductivityDrilldownCollapse>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>
    </Paper>
  );
}

function resolvePreset(isoDate) {
  const today = todayRange().start;
  const yesterday = yesterdayRange().start;
  if (!isoDate || isoDate === today) return "today";
  if (isoDate === yesterday) return "yesterday";
  return "custom";
}
