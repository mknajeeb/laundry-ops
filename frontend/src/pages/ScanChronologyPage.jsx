import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Drawer,
  FormControl,
  IconButton,
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
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { getRinseBagScanEvents, getScanChronology } from "../api";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import { todayRange, yesterdayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET" },
];

const STAGE_TABS = [
  { id: "weighing", label: "Weighing" },
  { id: "sorting", label: "Sorting" },
  { id: "washing", label: "Washing" },
  { id: "drying", label: "Drying" },
  { id: "washer_utilization", label: "Washer Utilization" },
  { id: "dryer_utilization", label: "Dryer Utilization" },
  { id: "user_activity", label: "User Activity" },
];

const DURATION_STAGES = new Set(["weighing", "sorting"]);
const EVENT_STAGES = new Set(["washing", "drying"]);
const UTIL_STAGES = new Set(["washer_utilization", "dryer_utilization"]);

const ACTIVITY_TYPE_OPTIONS = [
  { id: "all", label: "All" },
  { id: "weighing", label: "Weighing" },
  { id: "sorting", label: "Sorting" },
  { id: "washing", label: "Washing" },
  { id: "drying", label: "Drying" },
];

const LONG_GAP_SECONDS = 15 * 60;

const STAGE_SUMMARY_LABELS = {
  weighing: {
    firstStart: "First Weigh Start",
    lastEnd: "Last Weigh End",
    totalSessions: "Total Weighing Sessions",
    totalTime: "Total Weighing Time",
    avgDuration: "Average Weigh Duration",
    totalGap: "Total Gap Time",
  },
  sorting: {
    firstStart: "First Sort Start",
    lastEnd: "Last Sort End",
    totalSessions: "Total Sorting Sessions",
    totalTime: "Total Sorting Time",
    avgDuration: "Average Sort Duration",
    totalGap: "Total Gap Time",
  },
  washing: {
    firstStart: "First Washer Load",
    lastEnd: "Last Washer Load",
    totalSessions: "Total Washer Loads",
    uniqueMachines: "Unique Washers Used",
    mostUsed: "Most Used Washer",
  },
  drying: {
    firstStart: "First Drying Scan",
    lastEnd: "Last Drying Scan",
    totalSessions: "Total Drying Scans",
    uniqueMachines: "Unique Dryers Used",
    mostUsed: "Most Used Dryer",
  },
  washer_utilization: {
    firstStart: "First Load",
    lastEnd: "Last Load",
    totalSessions: "Total Loads",
    uniqueMachines: "Unique Washers Used",
    mostUsed: "Most Used Washer",
  },
  dryer_utilization: {
    firstStart: "First Load",
    lastEnd: "Last Load",
    totalSessions: "Total Loads",
    uniqueMachines: "Unique Dryers Used",
    mostUsed: "Most Used Dryer",
  },
};

const ACTIVITY_CHIP_COLORS = {
  weighing: { bg: "#eef2ff", color: "#4338ca" },
  sorting: { bg: "#ecfdf5", color: "#047857" },
  washing: { bg: "#eff6ff", color: "#1d4ed8" },
  drying: { bg: "#fff7ed", color: "#c2410c" },
};

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

function formatTimeOnly(iso) {
  if (!iso) return "—";
  const formatted = formatDateTime(iso);
  if (!formatted) return "—";
  const parts = formatted.split(" ");
  return parts.length >= 2 ? parts.slice(1).join(" ") : formatted;
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

function ActivityTypeChip({ type, label }) {
  const colors = ACTIVITY_CHIP_COLORS[type] || { bg: "#f3f4f6", color: "#374151" };
  return (
    <Chip
      label={label || type}
      size="small"
      sx={{
        bgcolor: colors.bg,
        color: colors.color,
        fontWeight: 700,
        fontSize: "0.75rem",
      }}
    />
  );
}

function EmployeeActivityCard({ group, onBagClick }) {
  const summary = group.summary || {};
  const activities = group.activities || [];

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
      }}
    >
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h6" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
          {group.employee}
        </Typography>
        <Stack direction="row" flexWrap="wrap" gap={0.75} useFlexGap>
          <Chip label={`${summary.total_activities ?? 0} activities`} size="small" variant="outlined" />
          {(summary.weighing_count ?? 0) > 0 ? (
            <Chip label={`${summary.weighing_count} weigh`} size="small" variant="outlined" />
          ) : null}
          {(summary.sorting_sessions ?? 0) > 0 ? (
            <Chip label={`${summary.sorting_sessions} sort`} size="small" variant="outlined" />
          ) : null}
          {(summary.washer_loads ?? 0) > 0 ? (
            <Chip label={`${summary.washer_loads} wash`} size="small" variant="outlined" />
          ) : null}
          {(summary.dryer_loads ?? 0) > 0 ? (
            <Chip label={`${summary.dryer_loads} dry`} size="small" variant="outlined" />
          ) : null}
        </Stack>
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        {formatDateTime(summary.first_activity_et) || "—"} → {formatDateTime(summary.last_activity_et) || "—"}
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ bgcolor: "grey.50" }}>
              <TableCell sx={{ fontWeight: 700 }}>Time</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Activity</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Bag ID</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Machine/Rack</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Duration</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Source</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Confidence</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {activities.map((row, idx) => (
              <TableRow key={`${row.activity_type}-${row.bag_id}-${row.time_et}-${idx}`} hover>
                <TableCell>{formatTimeOnly(row.time_et)}</TableCell>
                <TableCell>
                  <ActivityTypeChip type={row.activity_type} label={row.activity_label} />
                </TableCell>
                <TableCell>
                  {row.bag_id ? (
                    <Button
                      size="small"
                      onClick={() => onBagClick(row)}
                      sx={{ textTransform: "none", fontWeight: 700, p: 0, minWidth: 0 }}
                    >
                      {row.bag_id}
                    </Button>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell>{row.machine_or_rack || "—"}</TableCell>
                <TableCell>
                  {row.duration_seconds != null ? formatDurationSeconds(row.duration_seconds) : "—"}
                </TableCell>
                <TableCell>
                  <Typography variant="body2" sx={{ fontSize: "0.75rem" }}>
                    {row.source || "—"}
                  </Typography>
                </TableCell>
                <TableCell>{row.confidence || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default function ScanChronologyPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const stageParam = (searchParams.get("stage") || "weighing").toLowerCase();
  const activeStage = STAGE_TABS.some((t) => t.id === stageParam) ? stageParam : "weighing";
  const isUserActivity = activeStage === "user_activity";
  const isDurationStage = DURATION_STAGES.has(activeStage);
  const isEventStage = EVENT_STAGES.has(activeStage);
  const isUtilStage = UTIL_STAGES.has(activeStage);

  const [datePreset, setDatePreset] = useState("today");
  const [customDate, setCustomDate] = useState(todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(todayRange().start);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [bagFilter, setBagFilter] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("");
  const [activityTypeFilter, setActivityTypeFilter] = useState("all");
  const [drawerSession, setDrawerSession] = useState(null);
  const [drawerScans, setDrawerScans] = useState([]);
  const [drawerLoading, setDrawerLoading] = useState(false);

  const load = useCallback(async (dateEt, stage, filters = {}) => {
    if (!dateEt) return;
    setLoading(true);
    setError("");
    try {
      const params = { date_et: dateEt, stage };
      if (filters.employee) params.employee = filters.employee;
      if (filters.bag_id) params.bag_id = filters.bag_id;
      if (filters.confidence) params.confidence = filters.confidence;
      if (filters.activity_type) params.activity_type = filters.activity_type;
      const res = await getScanChronology(params);
      setData(res.data);
      setActiveDateEt(dateEt);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load scan chronology");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const currentFilters = useMemo(
    () => ({
      employee: employeeFilter,
      bag_id: bagFilter,
      confidence: isUserActivity ? "" : confidenceFilter,
      activity_type: isUserActivity ? activityTypeFilter : undefined,
    }),
    [employeeFilter, bagFilter, confidenceFilter, activityTypeFilter, isUserActivity],
  );

  useEffect(() => {
    load(activeDateEt, activeStage, currentFilters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeStage]);

  const applyDate = (preset, dateEt) => {
    setDatePreset(preset);
    if (dateEt) {
      setCustomDate(dateEt);
      load(dateEt, activeStage, currentFilters);
    }
  };

  const handlePresetChange = (_, value) => {
    if (!value) return;
    if (value === "today") applyDate("today", todayRange().start);
    else if (value === "yesterday") applyDate("yesterday", yesterdayRange().start);
    else setDatePreset("custom");
  };

  const applyFilters = () => {
    load(activeDateEt, activeStage, currentFilters);
  };

  const handleStageChange = (_, value) => {
    if (!value || value === activeStage) return;
    const next = new URLSearchParams(searchParams);
    next.set("stage", value);
    setSearchParams(next, { replace: true });
  };

  const openDrawer = async (row) => {
    setDrawerSession(row);
    setDrawerScans([]);
    setDrawerLoading(true);
    try {
      const res = await getRinseBagScanEvents(row.bag_id);
      setDrawerScans(res.data?.events || res.data?.scan_events || []);
    } catch {
      setDrawerScans([]);
    } finally {
      setDrawerLoading(false);
    }
  };

  const closeDrawer = () => {
    setDrawerSession(null);
    setDrawerScans([]);
  };

  const summary = data?.summary || {};
  const sessions = data?.sessions || [];
  const employeeGroups = data?.employee_groups || [];
  const labels = STAGE_SUMMARY_LABELS[activeStage] || STAGE_SUMMARY_LABELS.weighing;

  const employeeOptions = useMemo(() => {
    if (Array.isArray(data?.employees) && data.employees.length > 0) {
      return [...data.employees].sort((a, b) => a.localeCompare(b));
    }
    if (isUserActivity) {
      const set = new Set();
      employeeGroups.forEach((g) => {
        if (g.employee) set.add(g.employee);
      });
      return [...set].sort((a, b) => a.localeCompare(b));
    }
    const set = new Set();
    (data?.sessions || []).forEach((r) => {
      if (r.employee) set.add(r.employee);
    });
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [data, employeeGroups, isUserActivity]);

  const handleEmployeeFilterChange = (value) => {
    setEmployeeFilter(value);
    load(activeDateEt, activeStage, {
      ...currentFilters,
      employee: value,
    });
  };

  const handleActivityTypeFilterChange = (value) => {
    setActivityTypeFilter(value);
    load(activeDateEt, activeStage, {
      ...currentFilters,
      activity_type: value,
    });
  };

  const stageLabel = STAGE_TABS.find((t) => t.id === activeStage)?.label || "Weighing";

  const renderSummaryCards = () => {
    if (isUserActivity) {
      return (
        <>
          <SummaryCard label="Active Employees" value={summary.active_employees ?? 0} />
          <SummaryCard label="Total Activities" value={summary.total_activities ?? 0} />
          <SummaryCard label="Weighing Count" value={summary.weighing_count ?? 0} />
          <SummaryCard label="Sorting Sessions" value={summary.sorting_sessions ?? 0} />
          <SummaryCard label="Washer Loads" value={summary.washer_loads ?? 0} />
          <SummaryCard label="Dryer Loads" value={summary.dryer_loads ?? 0} />
          <SummaryCard label="First Activity" value={formatDateTime(summary.first_activity_et) || "—"} />
          <SummaryCard label="Last Activity" value={formatDateTime(summary.last_activity_et) || "—"} />
        </>
      );
    }

    if (isUtilStage) {
      return (
        <>
          <SummaryCard label={labels.firstStart} value={formatDateTime(summary.first_load_et) || "—"} />
          <SummaryCard label={labels.lastEnd} value={formatDateTime(summary.last_load_et) || "—"} />
          <SummaryCard label={labels.totalSessions} value={summary.total_loads ?? 0} />
          <SummaryCard label={labels.uniqueMachines} value={summary.unique_machines_used ?? 0} />
          <SummaryCard label={labels.mostUsed} value={summary.most_used_machine || "—"} />
        </>
      );
    }

    if (isEventStage) {
      const totalKey = activeStage === "washing" ? "total_washer_loads" : "total_drying_scans";
      const uniqueKey = activeStage === "washing" ? "unique_washers_used" : "unique_dryers_used";
      const mostUsedKey = activeStage === "washing" ? "most_used_washer" : "most_used_dryer";
      const firstKey = activeStage === "washing" ? "first_washer_load_et" : "first_drying_scan_et";
      const lastKey = activeStage === "washing" ? "last_washer_load_et" : "last_drying_scan_et";
      return (
        <>
          <SummaryCard label={labels.firstStart} value={formatDateTime(summary[firstKey]) || "—"} />
          <SummaryCard label={labels.lastEnd} value={formatDateTime(summary[lastKey]) || "—"} />
          <SummaryCard label={labels.totalSessions} value={summary[totalKey] ?? 0} />
          <SummaryCard label={labels.uniqueMachines} value={summary[uniqueKey] ?? 0} />
          <SummaryCard label={labels.mostUsed} value={summary[mostUsedKey] || "—"} />
        </>
      );
    }

    return (
      <>
        <SummaryCard label={labels.firstStart} value={formatDateTime(summary.first_start_et) || "—"} />
        <SummaryCard label={labels.lastEnd} value={formatDateTime(summary.last_end_et) || "—"} />
        <SummaryCard label={labels.totalSessions} value={summary.total_sessions ?? 0} />
        <SummaryCard label={labels.totalTime} value={formatDurationSeconds(summary.total_stage_seconds)} />
        <SummaryCard label={labels.avgDuration} value={formatDurationSeconds(summary.average_duration_seconds)} />
        <SummaryCard label={labels.totalGap} value={formatDurationSeconds(summary.total_gap_seconds)} />
      </>
    );
  };

  const renderSessionsTable = () => {
    if (isUtilStage) {
      return (
        <TableContainer
          component={Paper}
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
        >
          <Table size="small" sx={{ minWidth: 640 }}>
            <TableHead>
              <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
                <TableCell>#</TableCell>
                <TableCell>Time (ET)</TableCell>
                <TableCell>Machine</TableCell>
                <TableCell>Employee</TableCell>
                <TableCell>Bag ID</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.map((row) => (
                <TableRow key={`${row.index}-${row.machine}-${row.timestamp_et}`} hover>
                  <TableCell>{row.index}</TableCell>
                  <TableCell>{formatDateTime(row.timestamp_et)}</TableCell>
                  <TableCell>{row.machine || "—"}</TableCell>
                  <TableCell>{row.employee || "—"}</TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      onClick={() => openDrawer(row)}
                      sx={{ textTransform: "none", fontWeight: 700, p: 0, minWidth: 0 }}
                    >
                      {row.bag_id}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      );
    }

    if (isEventStage) {
      const rackKey = activeStage === "washing" ? "washer_rack" : "dryer_rack";
      return (
        <TableContainer
          component={Paper}
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
        >
          <Table size="small" sx={{ minWidth: 640 }}>
            <TableHead>
              <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
                <TableCell>#</TableCell>
                <TableCell>Bag ID</TableCell>
                <TableCell>Employee</TableCell>
                <TableCell>Time (ET)</TableCell>
                <TableCell>Machine/Rack</TableCell>
                <TableCell>Event</TableCell>
                <TableCell>Confidence</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.map((row) => (
                <TableRow key={`${row.index}-${row.bag_id}-${row.timestamp_et}`} hover>
                  <TableCell>{row.index}</TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      onClick={() => openDrawer(row)}
                      sx={{ textTransform: "none", fontWeight: 700, p: 0, minWidth: 0 }}
                    >
                      {row.bag_id}
                    </Button>
                  </TableCell>
                  <TableCell>{row.employee || "—"}</TableCell>
                  <TableCell>{formatDateTime(row.timestamp_et)}</TableCell>
                  <TableCell>{row[rackKey] || "—"}</TableCell>
                  <TableCell>{row.event_purpose || "—"}</TableCell>
                  <TableCell>{row.confidence || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      );
    }

    return (
      <TableContainer
        component={Paper}
        elevation={0}
        sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
      >
        <Table size="small" sx={{ minWidth: 640 }}>
          <TableHead>
            <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
              <TableCell>#</TableCell>
              <TableCell>Bag ID</TableCell>
              <TableCell>Employee</TableCell>
              <TableCell>Start (ET)</TableCell>
              <TableCell>End (ET)</TableCell>
              <TableCell>Duration</TableCell>
              <TableCell>Next start</TableCell>
              <TableCell>Gap</TableCell>
              <TableCell>Confidence</TableCell>
              <TableCell>Source</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sessions.map((row) => {
              const longGap =
                row.gap_until_next_seconds != null && row.gap_until_next_seconds >= LONG_GAP_SECONDS;
              return (
                <TableRow
                  key={`${row.index}-${row.bag_id}-${row.start_et}`}
                  sx={{
                    bgcolor: longGap ? "warning.50" : undefined,
                    "&:hover": { bgcolor: longGap ? "warning.100" : "action.hover" },
                  }}
                >
                  <TableCell>{row.index}</TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      onClick={() => openDrawer(row)}
                      sx={{ textTransform: "none", fontWeight: 700, p: 0, minWidth: 0 }}
                    >
                      {row.bag_id}
                    </Button>
                  </TableCell>
                  <TableCell>{row.employee || "—"}</TableCell>
                  <TableCell>{formatDateTime(row.start_et)}</TableCell>
                  <TableCell>{formatDateTime(row.end_et)}</TableCell>
                  <TableCell>{formatDurationSeconds(row.duration_seconds)}</TableCell>
                  <TableCell>{formatDateTime(row.next_start_et) || "—"}</TableCell>
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
                  <TableCell>{row.confidence || "—"}</TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontSize: "0.75rem" }}>
                      {row.source || "—"}
                    </Typography>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };

  const drawerStageLabel = drawerSession?.activity_label || stageLabel;

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 1200, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <VeeWashLogo height={28} />
        <Typography variant="h5" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
          Scan Chronology
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

      <Tabs
        value={activeStage}
        onChange={handleStageChange}
        sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
      >
        {STAGE_TABS.map(({ id, label }) => (
          <Tab key={id} value={id} label={label} sx={{ textTransform: "none", fontWeight: 600 }} />
        ))}
      </Tabs>

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
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Employee</InputLabel>
            <Select
              label="Employee"
              value={employeeFilter}
              onChange={(e) => handleEmployeeFilterChange(e.target.value)}
            >
              <MenuItem value="">All Employees</MenuItem>
              {employeeOptions.map((name) => (
                <MenuItem key={name} value={name}>
                  {name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {isUserActivity ? (
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Activity type</InputLabel>
              <Select
                label="Activity type"
                value={activityTypeFilter}
                onChange={(e) => handleActivityTypeFilterChange(e.target.value)}
              >
                {ACTIVITY_TYPE_OPTIONS.map(({ id, label }) => (
                  <MenuItem key={id} value={id}>
                    {label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : (
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
          )}
          <TextField
            size="small"
            label="Bag ID"
            value={bagFilter}
            onChange={(e) => setBagFilter(e.target.value)}
            sx={{ minWidth: 120 }}
          />
          <Button size="small" variant="outlined" onClick={applyFilters} disabled={loading}>
            Apply filters
          </Button>
        </Stack>
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
          {isUserActivity ? (
            <>
              <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
                {renderSummaryCards()}
              </Stack>

              {employeeGroups.length === 0 ? (
                <Alert severity="info">No user activity for {activeDateEt}.</Alert>
              ) : (
                <Stack spacing={2}>
                  {employeeGroups.map((group) => (
                    <EmployeeActivityCard key={group.employee} group={group} onBagClick={openDrawer} />
                  ))}
                </Stack>
              )}
            </>
          ) : (
            <>
              <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
                {renderSummaryCards()}
              </Stack>

              {sessions.length === 0 ? (
                <Alert severity="info">
                  No {stageLabel.toLowerCase()} {isDurationStage ? "sessions" : "records"} for {activeDateEt}.
                </Alert>
              ) : (
                renderSessionsTable()
              )}
            </>
          )}
        </>
      ) : null}

      <Drawer
        anchor="right"
        open={Boolean(drawerSession)}
        onClose={closeDrawer}
        PaperProps={{ sx: { width: { xs: "100%", sm: 480 }, p: 2 } }}
      >
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
          <Typography variant="h6" fontWeight={700}>
            Bag {drawerSession?.bag_id}
          </Typography>
          <IconButton onClick={closeDrawer} aria-label="Close">
            <CloseIcon />
          </IconButton>
        </Stack>
        {drawerSession ? (
          <Stack spacing={1} sx={{ mb: 2 }}>
            <Typography variant="body2">
              <strong>Stage:</strong> {drawerStageLabel}
            </Typography>
            <Typography variant="body2">
              <strong>Start event:</strong>{" "}
              {drawerSession.start_event_purpose || drawerSession.source?.split(" → ")[0] || "—"}
            </Typography>
            <Typography variant="body2">
              <strong>End event:</strong>{" "}
              {drawerSession.end_event_purpose || drawerSession.source?.split(" → ").slice(-1)[0] || "—"}
            </Typography>
            <Typography variant="body2">
              <strong>Confidence:</strong> {drawerSession.confidence || "—"}
            </Typography>
            <Typography variant="body2">
              <strong>Source:</strong> {drawerSession.source || "—"}
            </Typography>
            {drawerSession.machine_or_rack ||
            drawerSession.washer_rack ||
            drawerSession.dryer_rack ||
            drawerSession.machine ? (
              <Typography variant="body2">
                <strong>Machine/Rack:</strong>{" "}
                {drawerSession.machine_or_rack ||
                  drawerSession.washer_rack ||
                  drawerSession.dryer_rack ||
                  drawerSession.machine}
              </Typography>
            ) : null}
            {drawerSession.timestamp_et ? (
              <Typography variant="body2">
                <strong>Time (ET):</strong> {formatDateTime(drawerSession.timestamp_et)}
              </Typography>
            ) : null}
            {drawerSession.time_et ? (
              <Typography variant="body2">
                <strong>Time (ET):</strong> {formatDateTime(drawerSession.time_et)}
              </Typography>
            ) : null}
            {drawerSession.event_purpose ? (
              <Typography variant="body2">
                <strong>Event:</strong> {drawerSession.event_purpose}
              </Typography>
            ) : null}
          </Stack>
        ) : null}
        <Typography variant="subtitle2" fontWeight={700} gutterBottom>
          Full scan list
        </Typography>
        {drawerLoading ? (
          <CircularProgress size={24} />
        ) : (
          <FoldingScanEventsTable events={drawerScans} />
        )}
      </Drawer>
    </Box>
  );
}
