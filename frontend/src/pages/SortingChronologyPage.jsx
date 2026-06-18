import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
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
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { getSortingChronology } from "../api";
import { todayRange, yesterdayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET" },
];

const LONG_GAP_SECONDS = 15 * 60;

function resolvePreset(isoDate) {
  const today = todayRange().start;
  const yesterday = yesterdayRange().start;
  if (!isoDate || isoDate === today) return "today";
  if (isoDate === yesterday) return "yesterday";
  return "custom";
}

function formatDurationSeconds(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s <= 0) return "0m";
  return formatFoldingDuration(s);
}

function SummaryCard({ label, value, sub }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
        minWidth: 0,
        flex: "1 1 140px",
      }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, mt: 0.25 }}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}

export default function SortingChronologyPage() {
  const [datePreset, setDatePreset] = useState("today");
  const [customDate, setCustomDate] = useState(todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(todayRange().start);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [bagFilter, setBagFilter] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("");

  const load = useCallback(async (dateEt, filters = {}) => {
    if (!dateEt) return;
    setLoading(true);
    setError("");
    try {
      const params = { date_et: dateEt };
      if (filters.employee) params.employee = filters.employee;
      if (filters.bag_id) params.bag_id = filters.bag_id;
      if (filters.confidence) params.confidence = filters.confidence;
      const res = await getSortingChronology(params);
      setData(res.data);
      setActiveDateEt(dateEt);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load sorting chronology");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(activeDateEt, {
      employee: employeeFilter,
      bag_id: bagFilter,
      confidence: confidenceFilter,
    });
  }, []); // initial load only

  const applyDate = (preset, dateEt) => {
    setDatePreset(preset);
    if (dateEt) {
      setCustomDate(dateEt);
      load(dateEt, {
        employee: employeeFilter,
        bag_id: bagFilter,
        confidence: confidenceFilter,
      });
    }
  };

  const handlePresetChange = (_, value) => {
    if (!value) return;
    if (value === "today") applyDate("today", todayRange().start);
    else if (value === "yesterday") applyDate("yesterday", yesterdayRange().start);
    else setDatePreset("custom");
  };

  const applyFilters = () => {
    load(activeDateEt, {
      employee: employeeFilter,
      bag_id: bagFilter,
      confidence: confidenceFilter,
    });
  };

  const summary = data?.summary || {};
  const sessions = data?.sessions || [];

  const employeeOptions = useMemo(() => {
    const set = new Set();
    (data?.sessions || []).forEach((r) => {
      if (r.employee) set.add(r.employee);
    });
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [data]);

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 1200, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <VeeWashLogo height={28} />
        <Typography variant="h5" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
          Sorting Chronology
        </Typography>
      </Stack>

      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
        <Button size="small" component={RouterLink} to="/performance" sx={{ textTransform: "none", fontWeight: 600 }}>
          Shift Analysis
        </Button>
        <Button size="small" component={RouterLink} to="/performance/daily-roster" sx={{ textTransform: "none" }}>
          Daily Roster
        </Button>
      </Stack>

      <Paper
        elevation={0}
        sx={{
          p: 1.5,
          mb: 2,
          borderRadius: 2,
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        }}
      >
        <ToggleButtonGroup
          exclusive
          size="small"
          value={datePreset}
          onChange={handlePresetChange}
          sx={{ flexWrap: "wrap", gap: 0.5, mb: datePreset === "custom" ? 1 : 0 }}
        >
          {DATE_PRESETS.map(({ id, label }) => (
            <ToggleButton key={id} value={id} disabled={loading} sx={{ textTransform: "none", fontWeight: 600 }}>
              {label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        {datePreset === "custom" ? (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              type="date"
              size="small"
              label="ET date"
              value={customDate}
              onChange={(e) => setCustomDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <Button
              size="small"
              variant="contained"
              disabled={loading}
              onClick={() => applyDate("custom", customDate)}
              sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}
            >
              Apply
            </Button>
          </Stack>
        ) : null}
      </Paper>

      <Paper elevation={0} sx={{ p: 1.5, mb: 2, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
          <TextField
            size="small"
            label="Employee"
            value={employeeFilter}
            onChange={(e) => setEmployeeFilter(e.target.value)}
            sx={{ minWidth: 140 }}
          />
          <TextField
            size="small"
            label="Bag ID"
            value={bagFilter}
            onChange={(e) => setBagFilter(e.target.value)}
            sx={{ minWidth: 120 }}
          />
          <FormControl size="small" sx={{ minWidth: 130 }}>
            <InputLabel>Confidence</InputLabel>
            <Select
              label="Confidence"
              value={confidenceFilter}
              onChange={(e) => setConfidenceFilter(e.target.value)}
            >
              <MenuItem value="">All</MenuItem>
              <MenuItem value="exact">Exact</MenuItem>
              <MenuItem value="inferred">Inferred</MenuItem>
            </Select>
          </FormControl>
          <Button size="small" variant="outlined" onClick={applyFilters} disabled={loading}>
            Apply filters
          </Button>
        </Stack>
        {employeeOptions.length > 0 ? (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
            Employees on this day: {employeeOptions.join(", ")}
          </Typography>
        ) : null}
      </Paper>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress />
        </Box>
      ) : null}

      {data ? (
        <>
          <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
            <SummaryCard
              label="First Sort Start"
              value={formatDateTime(summary.first_sort_start_et) || "—"}
            />
            <SummaryCard
              label="Last Sort End"
              value={formatDateTime(summary.last_sort_end_et) || "—"}
            />
            <SummaryCard label="Total Sessions" value={summary.total_sessions ?? 0} />
            <SummaryCard
              label="Total Sorting Time"
              value={formatDurationSeconds(summary.total_sorting_seconds)}
            />
            <SummaryCard
              label="Total Gap Time"
              value={formatDurationSeconds(summary.total_gap_seconds)}
            />
            <SummaryCard
              label="Avg Sort Duration"
              value={formatDurationSeconds(summary.average_sort_duration_seconds)}
            />
          </Stack>

          {sessions.length === 0 ? (
            <Alert severity="info">No sorting sessions for {activeDateEt}.</Alert>
          ) : (
            <TableContainer
              component={Paper}
              elevation={0}
              sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
            >
              <Table size="small" sx={{ minWidth: 640 }}>
                <TableHead>
                  <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
                    <TableCell>#</TableCell>
                    <TableCell>Employee</TableCell>
                    <TableCell>Bag</TableCell>
                    <TableCell>Sort start (ET)</TableCell>
                    <TableCell>Sort end (ET)</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell>Next start</TableCell>
                    <TableCell>Gap</TableCell>
                    <TableCell>Source / confidence</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sessions.map((row) => {
                    const longGap =
                      row.gap_until_next_seconds != null && row.gap_until_next_seconds >= LONG_GAP_SECONDS;
                    return (
                      <TableRow
                        key={`${row.index}-${row.bag_id}`}
                        sx={{
                          bgcolor: longGap ? "warning.50" : undefined,
                          "&:hover": { bgcolor: longGap ? "warning.100" : "action.hover" },
                        }}
                      >
                        <TableCell>{row.index}</TableCell>
                        <TableCell>{row.employee || "—"}</TableCell>
                        <TableCell sx={{ fontWeight: 600 }}>{row.bag_id}</TableCell>
                        <TableCell>{formatDateTime(row.sort_start_et)}</TableCell>
                        <TableCell>{formatDateTime(row.sort_end_et)}</TableCell>
                        <TableCell>{formatDurationSeconds(row.duration_seconds)}</TableCell>
                        <TableCell>{formatDateTime(row.next_sort_start_et) || "—"}</TableCell>
                        <TableCell
                          sx={{
                            fontWeight: longGap ? 700 : 400,
                            color: longGap ? "warning.dark" : undefined,
                          }}
                        >
                          {row.gap_until_next_seconds != null
                            ? formatDurationSeconds(row.gap_until_next_seconds)
                            : "—"}
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontSize: "0.75rem" }}>
                            {row.source || "—"}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {row.confidence}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </>
      ) : null}
    </Box>
  );
}
