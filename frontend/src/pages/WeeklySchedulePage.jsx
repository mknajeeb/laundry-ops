import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  Switch,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import AttachMoneyOutlinedIcon from "@mui/icons-material/AttachMoneyOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import FileDownloadOutlinedIcon from "@mui/icons-material/FileDownloadOutlined";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import PrintIcon from "@mui/icons-material/Print";
import {
  createWeeklyScheduleEntry,
  deleteWeeklyScheduleEntry,
  duplicateWeeklyScheduleEntry,
  getWeeklySchedule,
  moveWeeklyScheduleEntry,
  setWeeklyScheduleExclusion,
  updateWeeklyScheduleEntry,
  updateWeeklyScheduleDisplaySettings,
} from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";
import WeeklyScheduleDayHeader from "../components/weeklySchedule/WeeklyScheduleDayHeader";
import WeeklyScheduleEmployeeCell from "../components/weeklySchedule/WeeklyScheduleEmployeeCell";
import WeeklyScheduleShiftCard from "../components/weeklySchedule/WeeklyScheduleShiftCard";
import WeeklyScheduleSummaryBar from "../components/weeklySchedule/WeeklyScheduleSummaryBar";
import {
  EMPLOYER_TAB,
  EMPLOYER_TAB_LABELS,
  filterEmployeesByEmployerTab,
  pickDefaultEmployerTab,
} from "../components/weeklySchedule/weeklyScheduleEmployerTabs";
import {
  DAY_LABELS,
  formatWeekRange,
  normalizeWeekStart,
  shiftWeek,
} from "../components/weeklySchedule/weeklyScheduleDates";
import { exportWeeklyScheduleCsv } from "../components/weeklySchedule/weeklyScheduleExport";
import "../components/weeklySchedule/weeklySchedulePrint.css";
import {
  computeFilteredDaySummaries,
  computeWeekSummary,
  scheduleCellBackground,
} from "../components/weeklySchedule/weeklyScheduleRoles";

function daySummary(day) {
  return {
    people: Number(day?.people ?? day?.employee_count ?? 0),
    hours: Number(day?.hours ?? day?.total_hours ?? 0),
    sort: Number(day?.sort ?? day?.sort_count ?? 0),
    wash: Number(day?.wash ?? day?.wash_count ?? 0),
    fold: Number(day?.fold ?? day?.fold_count ?? 0),
  };
}

function ScheduleDayCell({
  employee,
  dow,
  dayLabel,
  cellEntries,
  entriesByCell,
  dropTarget,
  setDropTarget,
  excluded,
  canEdit,
  openCreate,
  handleDrop,
  draggingId,
  setDraggingId,
  duplicatingId,
  showRoleLabels,
  showBreakMinutes,
  openEdit,
  handleDelete,
  handleDuplicate,
  compact = false,
}) {
  const cellKey = `${employee.user_id}:${dow}`;
  const isDropTarget = dropTarget === cellKey;
  const isEmpty = cellEntries.length === 0;
  const canAddShift = !excluded && canEdit;
  const cellBg = scheduleCellBackground({
    entries: cellEntries,
    excluded,
    isDropTarget,
  });

  return (
    <Box
      onClick={(e) => {
        if (!canAddShift || isEmpty) return;
        if (!e.target.closest("[data-shift-card]")) {
          openCreate(employee.user_id, dow);
        }
      }}
      onDragOver={(e) => {
        if (excluded || !canEdit) return;
        e.preventDefault();
        setDropTarget(cellKey);
      }}
      onDragLeave={() => {
        if (dropTarget === cellKey) setDropTarget(null);
      }}
      onDrop={(e) => {
        if (excluded || !canEdit) return;
        e.preventDefault();
        const entryId = e.dataTransfer.getData("text/plain");
        handleDrop(employee.user_id, dow, entryId);
      }}
      sx={{
        px: compact ? 0 : 0.5,
        py: compact ? 0.65 : 0.4,
        minHeight: compact ? 0 : 44,
        borderBottom: compact ? "none" : "1px solid #e2e8f0",
        borderLeft: compact ? "none" : "1px solid #e2e8f0",
        background: cellBg,
        opacity: excluded ? 0.85 : 1,
        transition: "background-color 0.12s ease",
        cursor: canAddShift && !isEmpty ? "pointer" : "default",
        borderRadius: compact ? 1.5 : 0,
        border: compact ? "1px solid #e8eef2" : undefined,
        "&:hover .schedule-cell-add": canAddShift && isEmpty
          ? { opacity: 1, borderColor: "rgba(0, 151, 178, 0.35)" }
          : {},
      }}
    >
      {compact ? (
        <Typography
          variant="overline"
          sx={{ display: "block", mb: 0.5, fontWeight: 800, letterSpacing: "0.08em", fontSize: "0.65rem" }}
        >
          {dayLabel}
        </Typography>
      ) : null}
      {cellEntries.map((entry) => (
        <WeeklyScheduleShiftCard
          key={entry.id}
          entry={entry}
          dragging={draggingId === entry.id}
          muted={excluded}
          showRoleLabels={showRoleLabels}
          showBreakMinutes={showBreakMinutes}
          onEdit={canEdit ? openEdit : undefined}
          onDelete={canEdit ? handleDelete : undefined}
          onDuplicate={canEdit ? handleDuplicate : undefined}
          duplicating={duplicatingId === entry.id}
          onDragStart={canEdit ? (e) => setDraggingId(e.id) : undefined}
          onDragEnd={canEdit ? () => setDraggingId(null) : undefined}
        />
      ))}
      {canAddShift && isEmpty ? (
        <Box
          className="schedule-cell-add"
          role="button"
          tabIndex={0}
          onClick={() => openCreate(employee.user_id, dow)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              openCreate(employee.user_id, dow);
            }
          }}
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 0.5,
            minHeight: 36,
            borderRadius: 1.25,
            border: "1.5px dashed #d8e2ea",
            bgcolor: "transparent",
            color: "text.secondary",
            opacity: 0.55,
            transition: "opacity 0.12s ease, border-color 0.12s ease, background-color 0.12s ease",
            cursor: "pointer",
            "&:hover": {
              opacity: 1,
              borderColor: "rgba(0, 151, 178, 0.35)",
              bgcolor: "rgba(0, 151, 178, 0.04)",
            },
          }}
        >
          <AddCircleOutlineIcon sx={{ fontSize: 15 }} />
          <Typography variant="caption" sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>
            Add shift
          </Typography>
        </Box>
      ) : null}
    </Box>
  );
}

export default function WeeklySchedulePage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const isTablet = useMediaQuery(theme.breakpoints.between("md", "lg"));

  const [weekStart, setWeekStart] = useState(() => normalizeWeekStart(new Date().toISOString().slice(0, 10)));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [dialogDefaults, setDialogDefaults] = useState({ userId: null, day: 0 });
  const [draggingId, setDraggingId] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [showExcluded, setShowExcluded] = useState(false);
  const [showCost, setShowCost] = useState(false);
  const [costSaving, setCostSaving] = useState(false);
  const [excludeSavingUserId, setExcludeSavingUserId] = useState(null);
  const [duplicatingId, setDuplicatingId] = useState(null);
  const [employerTab, setEmployerTab] = useState(EMPLOYER_TAB.VEEWASH);
  const printRef = useRef(null);

  const display = data?.display || {};
  const canEdit = display.can_edit_schedule !== false;
  const canManageExclusions = display.can_manage_exclusions !== false;
  const showRoleLabels = display.show_role_labels !== false;
  const showBreakMinutes = display.show_break_minutes !== false;
  const showEmployeeRates = display.show_employee_rates !== false;
  const costAllowed = display.show_estimated_cost !== false;
  const canConfigureSharing = display.can_configure_sharing !== false;
  const lockEmployerTab = display.lock_employer_tab === true;
  const hideEmployerTabs = display.hide_employer_tabs === true;
  const minWeekStart = display.min_week_start || null;
  const canViewPastWeeks = display.can_view_past_weeks !== false;
  const lockedEmployerTab = display.employer_tab || EMPLOYER_TAB.RINSE_EXCLUSIVE;

  useEffect(() => {
    if (data?.display) {
      setShowCost(data.display.show_estimated_cost !== false);
    }
  }, [data?.display?.show_estimated_cost]);

  const handleCostToggle = async () => {
    const next = !showCost;
    setShowCost(next);
    if (!canConfigureSharing) return;
    setCostSaving(true);
    try {
      await updateWeeklyScheduleDisplaySettings({ show_estimated_cost_default: next });
    } catch {
      setShowCost(!next);
    } finally {
      setCostSaving(false);
    }
  };

  const load = useCallback(async (week) => {
    setLoading(true);
    setError("");
    try {
      const res = await getWeeklySchedule({ week_start: week });
      setData(res.data);
      setWeekStart(res.data?.week_start || week);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load weekly schedule");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(weekStart);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const entriesByCell = useMemo(() => {
    const map = {};
    for (const entry of data?.entries || []) {
      const key = `${entry.user_id}:${entry.day_of_week}`;
      if (!map[key]) map[key] = [];
      map[key].push(entry);
    }
    return map;
  }, [data?.entries]);

  const dayTotals = data?.totals?.day_totals || [];

  useEffect(() => {
    if (lockEmployerTab) {
      setEmployerTab(lockedEmployerTab);
      return;
    }
    if (data?.employees?.length) {
      setEmployerTab(pickDefaultEmployerTab(data.employees));
    }
  }, [data?.week_start, lockEmployerTab, lockedEmployerTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabEmployees = useMemo(
    () => filterEmployeesByEmployerTab(data?.employees || [], employerTab),
    [data?.employees, employerTab],
  );

  const tabUserIds = useMemo(
    () => tabEmployees.map((employee) => employee.user_id),
    [tabEmployees],
  );

  const weekSummary = useMemo(
    () =>
      data
        ? computeWeekSummary(data, {
            includeExcluded: showExcluded,
            userIds: tabUserIds,
          })
        : null,
    [data, showExcluded, tabUserIds],
  );

  const filteredDaySummaries = useMemo(
    () =>
      data
        ? computeFilteredDaySummaries(data, {
            userIds: tabUserIds,
            includeExcluded: showExcluded,
          })
        : [],
    [data, tabUserIds, showExcluded],
  );

  const visibleEmployees = useMemo(() => {
    if (showExcluded) return tabEmployees;
    return tabEmployees.filter((e) => !e.excluded);
  }, [tabEmployees, showExcluded]);

  const excludedCount = useMemo(
    () => tabEmployees.filter((e) => e.excluded).length,
    [tabEmployees],
  );

  const employeeColWidth = isTablet ? "minmax(180px, 195px)" : "minmax(185px, 200px)";
  const dayColWidth = isTablet ? "minmax(128px, 1fr)" : "minmax(138px, 1fr)";
  const gridMinWidth = isTablet ? 1088 : 1200;

  const handleExcludeToggle = async (employee, excluded) => {
    setExcludeSavingUserId(employee.user_id);
    setError("");
    try {
      const res = await setWeeklyScheduleExclusion({
        week_start: weekStart,
        user_id: employee.user_id,
        excluded,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update exclusion");
    } finally {
      setExcludeSavingUserId(null);
    }
  };

  const openCreate = (userId, day) => {
    setEditingEntry(null);
    setDialogDefaults({ userId, day });
    setDialogOpen(true);
  };

  const openEdit = (entry) => {
    setEditingEntry(entry);
    setDialogDefaults({ userId: entry.user_id, day: entry.day_of_week });
    setDialogOpen(true);
  };

  const handleSave = async (form) => {
    setSaving(true);
    setError("");
    try {
      if (editingEntry?.id) {
        const res = await updateWeeklyScheduleEntry(editingEntry.id, form);
        setData(res.data);
      } else {
        const res = await createWeeklyScheduleEntry({ week_start: weekStart, ...form });
        setData(res.data);
      }
      setDialogOpen(false);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save shift");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (entry) => {
    if (!window.confirm("Delete this shift?")) return;
    setError("");
    try {
      const res = await deleteWeeklyScheduleEntry(entry.id);
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to delete shift");
    }
  };

  const handleDuplicate = async (entry) => {
    setDuplicatingId(entry.id);
    setError("");
    try {
      const res = await duplicateWeeklyScheduleEntry(entry.id, {
        day_of_week: entry.day_of_week,
        user_id: entry.user_id,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to duplicate shift");
    } finally {
      setDuplicatingId(null);
    }
  };

  const handleDrop = async (userId, dayOfWeek, entryId) => {
    if (!entryId) return;
    setError("");
    try {
      const res = await moveWeeklyScheduleEntry(entryId, { user_id: userId, day_of_week: dayOfWeek });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to move shift");
    } finally {
      setDraggingId(null);
      setDropTarget(null);
    }
  };

  const changeWeek = (delta) => {
    const next = shiftWeek(weekStart, delta);
    if (delta < 0 && minWeekStart && next < minWeekStart) return;
    setWeekStart(next);
    load(next);
  };

  const canGoToPreviousWeek = canViewPastWeeks && (!minWeekStart || weekStart > minWeekStart);

  const openEmployeeView = (employee) => {
    const url = `/performance/weekly-schedule/employee/${employee.user_id}?week_start=${weekStart}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handlePrint = () => {
    window.print();
  };

  const handleExport = () => {
    exportWeeklyScheduleCsv({
      employees: visibleEmployees,
      entries: data?.entries,
      weekStart,
      tabLabel: EMPLOYER_TAB_LABELS[employerTab],
      showRoleLabels,
    });
  };

  const cellProps = {
    entriesByCell,
    dropTarget,
    setDropTarget,
    canEdit,
    openCreate,
    handleDrop,
    draggingId,
    setDraggingId,
    duplicatingId,
    showRoleLabels,
    showBreakMinutes,
    openEdit,
    handleDelete,
    handleDuplicate,
  };

  return (
    <Box className="weekly-schedule-print-root" sx={{ p: { xs: 1.5, md: 2.5 }, bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100%" }}>
      <Paper
        ref={printRef}
        className="weekly-schedule-print-area"
        elevation={0}
        sx={{
          borderRadius: 3,
          overflow: "hidden",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
          boxShadow: "0 8px 30px rgba(15, 23, 42, 0.06)",
        }}
      >
        <Box
          className="no-print"
          sx={{
            px: { xs: 2, md: 2.5 },
            py: 2,
            background: `linear-gradient(135deg, ${VEEWASH_DASHBOARD.primaryBlue} 0%, ${VEEWASH_DASHBOARD.tealDark} 100%)`,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1.5,
            flexWrap: "wrap",
          }}
        >
          <Box>
            <Typography variant="h5" fontWeight={800} sx={{ letterSpacing: "-0.02em" }}>
              Weekly Schedule
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.92, mt: 0.25 }} className="no-print">
              Plan labor by day — drag shifts, assign Wash · Sort · Fold roles
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap className="no-print">
            <Stack
              direction="row"
              spacing={0.5}
              alignItems="center"
              sx={{
                bgcolor: "rgba(255,255,255,0.14)",
                borderRadius: 999,
                px: 0.5,
                py: 0.25,
              }}
            >
              <IconButton
                size="small"
                onClick={() => changeWeek(-1)}
                disabled={!canGoToPreviousWeek}
                sx={{ color: "#fff", opacity: canGoToPreviousWeek ? 1 : 0.45 }}
              >
                <ChevronLeftIcon />
              </IconButton>
              <Typography
                variant="subtitle2"
                sx={{ minWidth: { xs: 180, md: 220 }, textAlign: "center", fontWeight: 700 }}
              >
                {formatWeekRange(weekStart)}
              </Typography>
              <IconButton size="small" onClick={() => changeWeek(1)} sx={{ color: "#fff" }}>
                <ChevronRightIcon />
              </IconButton>
            </Stack>
            {canEdit ? (
              <Button
                size="small"
                variant="outlined"
                component={RouterLink}
                to="/performance/user-mapping"
                sx={{
                  fontWeight: 700,
                  color: "#fff",
                  borderColor: "rgba(255,255,255,0.45)",
                  "&:hover": { borderColor: "#fff", bgcolor: "rgba(255,255,255,0.12)" },
                }}
              >
                User mapping
              </Button>
            ) : null}
            <Button
              size="small"
              variant="outlined"
              startIcon={<FileDownloadOutlinedIcon />}
              onClick={handleExport}
              disabled={!visibleEmployees.length}
              sx={{
                fontWeight: 700,
                color: "#fff",
                borderColor: "rgba(255,255,255,0.45)",
                "&:hover": { borderColor: "#fff", bgcolor: "rgba(255,255,255,0.12)" },
              }}
            >
              Export Excel
            </Button>
            <Button
              size="small"
              variant="outlined"
              startIcon={<PrintIcon />}
              onClick={handlePrint}
              disabled={!visibleEmployees.length}
              sx={{
                fontWeight: 700,
                color: "#fff",
                borderColor: "rgba(255,255,255,0.45)",
                "&:hover": { borderColor: "#fff", bgcolor: "rgba(255,255,255,0.12)" },
              }}
            >
              Print
            </Button>
          </Stack>
        </Box>

        <Box className="weekly-schedule-print-header" sx={{ px: 2, pt: 1.5, pb: 0.5, bgcolor: "#fff" }}>
          <Typography variant="h6" fontWeight={800}>
            Weekly Schedule — {EMPLOYER_TAB_LABELS[employerTab]}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
            {formatWeekRange(weekStart)}
          </Typography>
        </Box>

        {!hideEmployerTabs ? (
          <Box sx={{ px: 2, pt: 1.5, pb: 0, bgcolor: "#fff", borderBottom: "1px solid #e8eef2" }} className="no-print">
            <Tabs
              value={employerTab}
              onChange={(_, value) => setEmployerTab(value)}
              sx={{
                minHeight: 40,
                "& .MuiTab-root": {
                  minHeight: 40,
                  py: 0.75,
                  fontWeight: 700,
                  fontSize: "0.8125rem",
                  textTransform: "none",
                },
              }}
            >
              <Tab
                value={EMPLOYER_TAB.VEEWASH}
                label={`${EMPLOYER_TAB_LABELS[EMPLOYER_TAB.VEEWASH]} (${filterEmployeesByEmployerTab(data?.employees || [], EMPLOYER_TAB.VEEWASH).length})`}
              />
              <Tab
                value={EMPLOYER_TAB.RINSE_EXCLUSIVE}
                label={`${EMPLOYER_TAB_LABELS[EMPLOYER_TAB.RINSE_EXCLUSIVE]} (${filterEmployeesByEmployerTab(data?.employees || [], EMPLOYER_TAB.RINSE_EXCLUSIVE).length})`}
              />
              <Tab
                value={EMPLOYER_TAB.COMBINED}
                label={`${EMPLOYER_TAB_LABELS[EMPLOYER_TAB.COMBINED]} (${(data?.employees || []).length})`}
              />
            </Tabs>
          </Box>
        ) : null}

        <Box
          className="no-print"
          sx={{
            px: 2,
            py: 1.25,
            bgcolor: "#fff",
            borderBottom: "1px solid #e8eef2",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1,
            flexWrap: "wrap",
          }}
        >
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            {excludedCount > 0 && canManageExclusions ? (
              <Chip
                icon={<PersonOffOutlinedIcon />}
                label={showExcluded ? `Showing excluded (${excludedCount})` : `Show excluded (${excludedCount})`}
                onClick={() => setShowExcluded((v) => !v)}
                color={showExcluded ? "warning" : "default"}
                variant={showExcluded ? "filled" : "outlined"}
                sx={{ fontWeight: 700 }}
              />
            ) : null}
            {costAllowed ? (
              <Chip
                icon={<AttachMoneyOutlinedIcon />}
                label={showCost ? "Hide cost" : "Show cost"}
                onClick={handleCostToggle}
                disabled={costSaving}
                variant={showCost ? "filled" : "outlined"}
                color={showCost ? "primary" : "default"}
                sx={{ fontWeight: 700 }}
              />
            ) : null}
          </Stack>
          {!display.is_privileged && display.org_settings ? (
            <Typography variant="caption" color="text.secondary">
              Shared view — some details hidden per org settings
            </Typography>
          ) : null}
        </Box>

        <Box sx={{ p: 2 }}>
          {excludedCount > 0 && !showExcluded && canManageExclusions ? (
            <Alert
              severity="info"
              className="no-print"
              sx={{ mb: 2, borderRadius: 2 }}
              action={
                <Button color="inherit" size="small" onClick={() => setShowExcluded(true)} sx={{ fontWeight: 700 }}>
                  Show excluded ({excludedCount})
                </Button>
              }
            >
              {excludedCount} employee{excludedCount === 1 ? "" : "s"} excluded from this week&apos;s schedule. Toggle
              &quot;Show excluded&quot; to review and include them.
            </Alert>
          ) : null}
          {data?.carried_forward_from ? (
            <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }} className="no-print">
              Schedule copied from the week of{" "}
              {formatWeekRange(normalizeWeekStart(data.carried_forward_from))}. Edit shifts here as needed — future
              empty weeks will carry forward from the latest saved week.
            </Alert>
          ) : null}
          {error ? (
            <Alert severity="error" sx={{ mb: 2 }} className="no-print">
              {error}
            </Alert>
          ) : null}

          {loading ? (
            <Stack alignItems="center" py={6} className="no-print">
              <CircularProgress size={32} />
            </Stack>
          ) : (
            <>
              <WeeklyScheduleSummaryBar
                summary={weekSummary}
                showCost={showCost && costAllowed}
              />

              {isMobile ? (
                <Stack spacing={1.5}>
                  {(visibleEmployees || []).map((employee) => {
                    const excluded = Boolean(employee.excluded);
                    return (
                      <Paper
                        key={employee.user_id}
                        elevation={0}
                        sx={{
                          borderRadius: 2.5,
                          border: "1px solid #e2e8f0",
                          overflow: "hidden",
                          bgcolor: "#fff",
                        }}
                      >
                        <WeeklyScheduleEmployeeCell
                          employee={employee}
                          entries={data?.entries}
                          excluded={excluded}
                          canManageExclusions={canManageExclusions}
                          excludeSaving={excludeSavingUserId === employee.user_id}
                          onExcludeToggle={handleExcludeToggle}
                          showCost={showCost}
                          showRates={showEmployeeRates}
                          costAllowed={costAllowed}
                          onViewSchedule={openEmployeeView}
                        />
                        <Box sx={{ px: 1.25, pb: 1.25, display: "grid", gap: 0.75 }}>
                          {DAY_LABELS.map((dayLabel, dow) => {
                            const cellKey = `${employee.user_id}:${dow}`;
                            const cellEntries = entriesByCell[cellKey] || [];
                            if (!cellEntries.length && excluded) return null;
                            return (
                              <ScheduleDayCell
                                key={cellKey}
                                employee={employee}
                                dow={dow}
                                dayLabel={dayLabel}
                                cellEntries={cellEntries}
                                excluded={excluded}
                                compact
                                {...cellProps}
                              />
                            );
                          })}
                        </Box>
                      </Paper>
                    );
                  })}
                </Stack>
              ) : (
                <Box sx={{ overflowX: "auto" }}>
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: `${employeeColWidth} repeat(7, ${dayColWidth})`,
                      minWidth: gridMinWidth,
                      gap: 0,
                      border: "1px solid #e2e8f0",
                      borderRadius: 2.5,
                      overflow: "hidden",
                      bgcolor: "#fff",
                    }}
                  >
                    <Box
                      sx={{
                        px: 1.15,
                        py: 0.85,
                        bgcolor: "#f8fafc",
                        borderBottom: "1px solid #e2e8f0",
                        position: "sticky",
                        left: 0,
                        zIndex: 2,
                        display: "flex",
                        alignItems: "flex-end",
                      }}
                    >
                      <Typography
                        variant="overline"
                        fontWeight={800}
                        color="text.secondary"
                        sx={{ letterSpacing: "0.1em", fontSize: "0.68rem" }}
                      >
                        Employee
                      </Typography>
                    </Box>
                    {DAY_LABELS.map((label, dow) => (
                      <Box
                        key={label}
                        sx={{
                          bgcolor: "#f8fafc",
                          borderBottom: "1px solid #e2e8f0",
                          borderLeft: "1px solid #e2e8f0",
                        }}
                      >
                        <WeeklyScheduleDayHeader
                          dayLabel={label}
                          summary={daySummary(filteredDaySummaries[dow] || dayTotals[dow])}
                        />
                      </Box>
                    ))}

                    {(visibleEmployees || []).map((employee) => {
                      const excluded = Boolean(employee.excluded);
                      return (
                        <Box key={employee.user_id} sx={{ display: "contents" }}>
                          <WeeklyScheduleEmployeeCell
                            employee={employee}
                            entries={data?.entries}
                            excluded={excluded}
                            canManageExclusions={canManageExclusions}
                            excludeSaving={excludeSavingUserId === employee.user_id}
                            onExcludeToggle={handleExcludeToggle}
                            showCost={showCost}
                            showRates={showEmployeeRates}
                            costAllowed={costAllowed}
                            onViewSchedule={openEmployeeView}
                          />
                          {DAY_LABELS.map((dayLabel, dow) => {
                            const cellKey = `${employee.user_id}:${dow}`;
                            const cellEntries = entriesByCell[cellKey] || [];
                            return (
                              <ScheduleDayCell
                                key={cellKey}
                                employee={employee}
                                dow={dow}
                                dayLabel={dayLabel}
                                cellEntries={cellEntries}
                                excluded={excluded}
                                {...cellProps}
                              />
                            );
                          })}
                        </Box>
                      );
                    })}
                  </Box>
                </Box>
              )}
            </>
          )}
        </Box>
      </Paper>

      <WeeklyScheduleEntryDialog
        open={dialogOpen && canEdit}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        saving={saving}
        entry={editingEntry}
        defaultUserId={dialogDefaults.userId}
        defaultDay={dialogDefaults.day}
      />
    </Box>
  );
}
