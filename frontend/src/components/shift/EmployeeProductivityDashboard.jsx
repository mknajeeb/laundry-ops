import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Paper,
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
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { getEmployeeProductivityDashboard } from "../../api";
import { yesterdayRange, todayRange } from "../../utils/foldingDateRange";
import {
  PRODUCTIVITY_RANK_OPTIONS,
  fmtAvgLbsPerBag,
  fmtProductivityRate,
  isMissingClockIn,
  rankEmployees,
} from "../../utils/employeeProductivityHelpers";
import EmployeeProductivityDrilldown, {
  EmployeeProductivityDrilldownCollapse,
} from "./EmployeeProductivityDrilldown";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

function fmtNum(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "N/A";
  return Number(value).toFixed(digits);
}

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET Date" },
];

/**
 * Phase 2 — Employee Productivity Dashboard.
 * Reads frozen Phase 1 `employee_completed_bags_today` only.
 * Ranking is client-side; date changes fetch this section only.
 */
export default function EmployeeProductivityDashboard({
  initialSection,
  initialDateEt,
}) {
  const [expandedEmployee, setExpandedEmployee] = useState(null);
  const [rankBy, setRankBy] = useState("bags");
  const [datePreset, setDatePreset] = useState(() => resolvePreset(initialDateEt));
  const [customDate, setCustomDate] = useState(initialDateEt || todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(initialDateEt || todayRange().start);
  const [section, setSection] = useState(initialSection || null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState("");

  const fetchSection = useCallback(async (dateEt) => {
    if (!dateEt) return;
    setLoading(true);
    setFetchError("");
    try {
      const res = await getEmployeeProductivityDashboard({ date_et: dateEt });
      setSection(res.data?.employee_completed_bags_today || null);
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
  const recon = section?.reconciliation || {};
  const banner = section?.reconciliation_banner || recon;
  const reconciled = banner.status === "reconciled" || recon.ok === true;
  const credited = banner.employee_completed_bags_credited ?? recon.employee_attributed_bag_count ?? 0;
  const workload = banner.workload_completed_today ?? recon.workload_completed_today ?? 0;
  const selectedDate = section?.selected_date_et || activeDateEt;

  const rankedEmployees = useMemo(
    () => rankEmployees(employees, rankBy),
    [employees, rankBy],
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
        <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.0625rem" }}>
          Employee Productivity Dashboard
        </Typography>
        <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block" }}>
          Phase 2 · ET {selectedDate || activeDateEt}
        </Typography>
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

        <Alert
          severity={reconciled ? "success" : "error"}
          variant="outlined"
          sx={{ mb: 1.25, py: 0.75 }}
        >
          <Typography variant="body2" fontWeight={700} sx={{ mb: 0.25 }}>
            Reconciliation
          </Typography>
          <Typography variant="body2">Employee Completed Bags Credited: {credited}</Typography>
          <Typography variant="body2">Today&apos;s Workload Completed: {workload}</Typography>
          <Typography variant="body2" fontWeight={800} sx={{ mt: 0.35 }}>
            Status: {banner.status_label || (reconciled ? "Reconciled ✓" : "Mismatch ✗")}
          </Typography>
        </Alert>

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

        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" aria-label="Employee productivity dashboard">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 700, width: 48 }}>#</TableCell>
                <TableCell sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>Employee</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Completed Bags</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Completed Lbs</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>Avg Lbs / Bag</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Bags / Hour</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Lbs / Hour</TableCell>
                <TableCell sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>Clock In Time</TableCell>
                <TableCell sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>Last Completion Time</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Productive Hours</TableCell>
                <TableCell padding="checkbox" />
              </TableRow>
            </TableHead>
            <TableBody>
              {rankedEmployees.map((emp) => {
                const open = expandedEmployee === emp.employee;
                const missingClockIn = isMissingClockIn(emp);
                const productiveHrs = emp.productive_hours ?? emp.worked_hours;
                return (
                  <Fragment key={emp.employee}>
                    <TableRow
                      hover
                      onClick={() => setExpandedEmployee((prev) => (prev === emp.employee ? null : emp.employee))}
                      sx={{ cursor: "pointer" }}
                    >
                      <TableCell sx={{ fontWeight: 800, color: "text.secondary" }}>
                        {emp.productivity_rank}
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600 }}>{emp.employee}</TableCell>
                      <TableCell align="right">{emp.completed_bags ?? 0}</TableCell>
                      <TableCell align="right">
                        {emp.total_completed_lbs ?? 0}
                        {emp.missing_weight_count > 0 ? (
                          <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>
                            ({emp.missing_weight_count} no wt)
                          </Typography>
                        ) : null}
                      </TableCell>
                      <TableCell align="right">{fmtAvgLbsPerBag(emp)}</TableCell>
                      <TableCell align="right">{fmtProductivityRate(emp.bags_per_hour, missingClockIn)}</TableCell>
                      <TableCell align="right">{fmtProductivityRate(emp.lbs_per_hour, missingClockIn)}</TableCell>
                      <TableCell>
                        {missingClockIn ? (
                          <Typography variant="body2" color="warning.main" fontSize="0.8125rem">
                            Missing clock-in
                          </Typography>
                        ) : (
                          emp.clock_in_time_et || "—"
                        )}
                      </TableCell>
                      <TableCell>{emp.last_completion_time_et || "—"}</TableCell>
                      <TableCell align="right">
                        {missingClockIn ? "N/A" : fmtNum(productiveHrs, 2)}
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
                      <TableCell colSpan={11} sx={{ py: 0, borderBottom: open ? undefined : "none" }}>
                        <EmployeeProductivityDrilldownCollapse open={open}>
                          <EmployeeProductivityDrilldown
                            bags={emp.bags}
                            referenceDateEt={selectedDate}
                            loading={loading}
                          />
                        </EmployeeProductivityDrilldownCollapse>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
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
