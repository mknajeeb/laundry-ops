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
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import PersonAddAlt1OutlinedIcon from "@mui/icons-material/PersonAddAlt1Outlined";
import AttachMoneyOutlinedIcon from "@mui/icons-material/AttachMoneyOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import FileDownloadOutlinedIcon from "@mui/icons-material/FileDownloadOutlined";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import PrintIcon from "@mui/icons-material/Print";
import {
  bulkSetWeeklyScheduleEmployer,
  cascadeWeeklySchedule,
  createWeeklyScheduleEntry,
  createWeeklyScheduleResponsibility,
  deleteWeeklyScheduleEntry,
  deleteWeeklyScheduleResponsibility,
  disableWeeklyScheduleTemplate,
  duplicateWeeklyScheduleEntry,
  enableWeeklyScheduleTemplate,
  getWeeklySchedule,
  moveWeeklyScheduleEntry,
  setWeeklyScheduleExclusion,
  updateWeeklyScheduleEntry,
  updateWeeklyScheduleDisplaySettings,
  updateWeeklyScheduleResponsibility,
} from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import WeeklyScheduleCascadeDialog from "../components/weeklySchedule/WeeklyScheduleCascadeDialog";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";
import WeeklyScheduleManageRolesDialog from "../components/weeklySchedule/WeeklyScheduleManageRolesDialog";
import WeeklyScheduleTimeRoleView, {
  HourlyCoverageControls,
} from "../components/weeklySchedule/WeeklyScheduleTimeRoleView";
import WeeklyScheduleHoursSummary from "../components/weeklySchedule/WeeklyScheduleHoursSummary";
import WeeklyScheduleResponsibilityChip from "../components/weeklySchedule/WeeklyScheduleResponsibilityChip";
import {
  ASSIGNMENT_KIND,
  buildHourlyCoverage,
  coverageColumns,
  filterCoverageHours,
} from "../components/weeklySchedule/weeklyScheduleTimeBlocks";
import WeeklyScheduleDayHeader from "../components/weeklySchedule/WeeklyScheduleDayHeader";
import WeeklyScheduleEmployeeCell from "../components/weeklySchedule/WeeklyScheduleEmployeeCell";
import WeeklyScheduleShiftCard from "../components/weeklySchedule/WeeklyScheduleShiftCard";
import WeeklyScheduleSummaryBar from "../components/weeklySchedule/WeeklyScheduleSummaryBar";
import {
  ENTITY_TAB,
  ENTITY_TAB_LABELS,
  addableEmployeesForEmployerTab,
  countEmployeesForEmployerTab,
  defaultNewShiftEntity,
  filterEmployeesByEmployerTab,
  filterEntriesByEmployerTab,
  pickDefaultEmployerTab,
  shiftEntityChoicesForEmployee,
  visibleEntityTabs,
  SHIFT_EMPLOYER_AFFILIATION,
} from "../components/weeklySchedule/weeklyScheduleEmployerTabs";
import { entityLabel } from "../payroll/businessEntity";
import {
  DAY_LABELS,
  formatWeekRange,
  currentWeekStart,
  normalizeWeekStart,
  shiftWeek,
} from "../components/weeklySchedule/weeklyScheduleDates";
import {
  exportWeeklyScheduleCsv,
  exportWeeklyScheduleHourlyCsv,
} from "../components/weeklySchedule/weeklyScheduleExport";
import WeeklySchedulePrintTable from "../components/weeklySchedule/WeeklySchedulePrintTable";
import WeeklyScheduleTimeRolePrint from "../components/weeklySchedule/WeeklyScheduleTimeRolePrint";
import WeeklyScheduleViewTabs from "../components/weeklySchedule/WeeklyScheduleViewTabs";
import {
  filterEntriesByScheduleView,
  hasRoleViewFilter,
  resolveRoleViewRoles,
  SCHEDULE_VIEW_ALL,
  scheduleViewSummaryLabel,
  visibleDayIndices,
} from "../components/weeklySchedule/weeklyScheduleViewFilters";
import { openWeeklySchedulePrintWindow } from "../components/weeklySchedule/weeklySchedulePrint";
import "../components/weeklySchedule/weeklySchedulePrint.css";
import {
  computeFilteredDaySummaries,
  computeWeekSummary,
  scheduleCellBackground,
  isScheduleTask,
  scheduleRoleCatalog,
  setScheduleRoleCatalog,
  setScheduleRoleGroups,
  entryRoleAssignments,
  sortRoles,
  summarizeSelectedRoleHours,
  withDisplayedTotals,
} from "../components/weeklySchedule/weeklyScheduleRoles";

const VIEW_MODE = { EMPLOYEE: "employee", TIME_ROLE: "time_role" };


function daySummary(day) {
  return {
    people: Number(day?.people ?? day?.employee_count ?? 0),
    hours: Number(day?.hours ?? day?.total_hours ?? 0),
    sort: Number(day?.sort ?? day?.sort_count ?? 0),
    wash: Number(day?.wash ?? day?.wash_count ?? 0),
    weigher: Number(day?.weigher ?? day?.weigher_count ?? 0),
    fold: Number(day?.fold ?? day?.fold_count ?? 0),
    pt_washer: Number(day?.pt_washer ?? day?.pt_washer_count ?? 0),
    pt_sorter: Number(day?.pt_sorter ?? day?.pt_sorter_count ?? 0),
    pt_folder: Number(day?.pt_folder ?? day?.pt_folder_count ?? 0),
    hd_operator: Number(day?.hd_operator ?? day?.hd_operator_count ?? 0),
    hd_folder: Number(day?.hd_folder ?? day?.hd_folder_count ?? 0),
    attendant: Number(day?.attendant ?? day?.attendant_count ?? 0),
    non_rinse_folder: Number(day?.non_rinse_folder ?? day?.non_rinse_folder_count ?? 0),
    wash_hours: Number(day?.wash_hours ?? 0),
    sort_hours: Number(day?.sort_hours ?? 0),
    fold_hours: Number(day?.fold_hours ?? 0),
    pt_washer_hours: Number(day?.pt_washer_hours ?? 0),
    pt_sorter_hours: Number(day?.pt_sorter_hours ?? 0),
    pt_folder_hours: Number(day?.pt_folder_hours ?? 0),
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
  scheduleEndTimeEnabled,
  openEdit,
  handleDelete,
  handleDuplicate,
  handleSetEmployer,
  organizationSlug = null,
  compact = false,
  cellResponsibilities = [],
  openEditResponsibility,
}) {
  const cellKey = `${employee.user_id}:${dow}`;
  const isDropTarget = dropTarget === cellKey;
  const isEmpty = cellEntries.length === 0 && cellResponsibilities.length === 0;
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
        px: 0.55,
        py: 0.55,
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
          employee={employee}
          dragging={draggingId === entry.id}
          muted={excluded}
          showRoleLabels={showRoleLabels}
          showBreakMinutes={showBreakMinutes}
          scheduleEndTimeEnabled={scheduleEndTimeEnabled}
          onEdit={canEdit ? openEdit : undefined}
          onDelete={canEdit ? handleDelete : undefined}
          onDuplicate={canEdit ? handleDuplicate : undefined}
          onSetEmployer={canEdit ? handleSetEmployer : undefined}
          organizationSlug={organizationSlug}
          duplicating={duplicatingId === entry.id}
          onDragStart={canEdit ? (e) => setDraggingId(e.id) : undefined}
          onDragEnd={canEdit ? () => setDraggingId(null) : undefined}
        />
      ))}
      {cellResponsibilities.map((item) => (
        <WeeklyScheduleResponsibilityChip
          key={`r${item.id}`}
          item={item}
          onClick={canEdit && !excluded ? openEditResponsibility : undefined}
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

  const [weekStart, setWeekStart] = useState(() => currentWeekStart());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [dialogDefaults, setDialogDefaults] = useState({ userId: null, day: 0 });
  const [editingResponsibility, setEditingResponsibility] = useState(null);
  const [dialogError, setDialogError] = useState("");
  const [viewMode, setViewMode] = useState(VIEW_MODE.EMPLOYEE);
  const [rolesOpen, setRolesOpen] = useState(false);
  const [draggingId, setDraggingId] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);
  const [showExcluded, setShowExcluded] = useState(false);
  const [showCost, setShowCost] = useState(false);
  const [costSaving, setCostSaving] = useState(false);
  const [excludeSavingUserId, setExcludeSavingUserId] = useState(null);
  const [duplicatingId, setDuplicatingId] = useState(null);
  const [bulkEmployerSaving, setBulkEmployerSaving] = useState(false);
  const [cascadeOpen, setCascadeOpen] = useState(false);
  const [templateSaving, setTemplateSaving] = useState(false);
  const [employerTab, setEmployerTab] = useState(ENTITY_TAB.RINSE_EXCLUSIVE);
  const [selectedRoleView, setSelectedRoleView] = useState([]);
  const [dayViewTab, setDayViewTab] = useState(SCHEDULE_VIEW_ALL);
  const [matrixRoles, setMatrixRoles] = useState(null);
  const [showCoverageNames, setShowCoverageNames] = useState(true);
  const [coverageRange, setCoverageRange] = useState({ fromHour: null, toHour: null });
  const printContentRef = useRef(null);
  const stickyHeaderRef = useRef(null);

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
  const lockedEmployerTab = display.employer_tab || ENTITY_TAB.RINSE_EXCLUSIVE;
  const entityScope = data?.entity_scope || {};
  const organizationSlug = entityScope.organization_slug || null;
  const entityTabs = visibleEntityTabs(entityScope);
  const scheduleEndTimeEnabled = display.schedule_end_time_enabled !== false;
  const hiddenScheduleRoles = display.hidden_schedule_roles || [];
  const daysOnly = !scheduleEndTimeEnabled;

  // Registered during render so every child (chips, filters, dialogs) sees the org's role settings.
  const roleCatalog = useMemo(() => {
    setScheduleRoleCatalog(data?.role_catalog);
    return scheduleRoleCatalog();
  }, [data?.role_catalog]);
  const roleGroups = useMemo(() => {
    setScheduleRoleGroups(data?.role_groups);
    return data?.role_groups || [];
  }, [data?.role_groups]);

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

  const dayTotals = data?.totals?.day_totals || [];

  useEffect(() => {
    if (lockEmployerTab) {
      setEmployerTab(lockedEmployerTab);
      return;
    }
    if (data?.employees?.length || data?.entries?.length) {
      setEmployerTab(pickDefaultEmployerTab(entityScope, data.employees, data.entries));
    }
  }, [data?.week_start, lockEmployerTab, lockedEmployerTab, entityScope?.organization_slug]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (lockEmployerTab) return;
    if (entityTabs.length && !entityTabs.includes(employerTab)) {
      setEmployerTab(pickDefaultEmployerTab(entityScope, data?.employees, data?.entries));
    }
  }, [entityTabs, employerTab, lockEmployerTab, entityScope, data?.employees, data?.entries]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setSelectedRoleView([]);
    setDayViewTab(SCHEDULE_VIEW_ALL);
  }, [data?.week_start, employerTab]);

  const tabEntries = useMemo(
    () => filterEntriesByEmployerTab(data?.entries || [], employerTab, data?.employees || [], organizationSlug),
    [data?.entries, data?.employees, employerTab, organizationSlug],
  );

  const shiftTabEmployees = useMemo(
    () => filterEmployeesByEmployerTab(data?.employees || [], employerTab, data?.entries || [], organizationSlug),
    [data?.employees, data?.entries, employerTab, organizationSlug],
  );

  const addableForTab = useMemo(
    () =>
      addableEmployeesForEmployerTab(
        data?.employees || [],
        employerTab,
        data?.entries || [],
        organizationSlug,
      ),
    [data?.employees, data?.entries, employerTab, organizationSlug],
  );

  /** Daily responsibilities follow the employee's tab (they carry no shift employer of their own). */
  const tabResponsibilities = useMemo(() => {
    const ids = new Set([...shiftTabEmployees, ...addableForTab].map((e) => Number(e.user_id)));
    return (data?.daily_responsibilities || []).filter((item) => ids.has(Number(item.user_id)));
  }, [data?.daily_responsibilities, shiftTabEmployees, addableForTab]);

  const tabEmployees = useMemo(() => {
    const ids = new Set(shiftTabEmployees.map((e) => Number(e.user_id)));
    const extra = addableForTab.filter(
      (e) => !ids.has(Number(e.user_id)) && tabResponsibilities.some((r) => Number(r.user_id) === Number(e.user_id)),
    );
    if (!extra.length) return shiftTabEmployees;
    return [...shiftTabEmployees, ...extra].sort((a, b) =>
      String(a.display_name || "").localeCompare(String(b.display_name || "")),
    );
  }, [shiftTabEmployees, addableForTab, tabResponsibilities]);

  const viewEntries = useMemo(
    () => filterEntriesByScheduleView(tabEntries, selectedRoleView, dayViewTab),
    [tabEntries, selectedRoleView, dayViewTab],
  );

  const viewResponsibilities = useMemo(() => {
    const roles = resolveRoleViewRoles(selectedRoleView);
    return tabResponsibilities.filter((item) => {
      if (roles && !roles.includes(item.role)) return false;
      if (dayViewTab !== SCHEDULE_VIEW_ALL && Number(item.day_of_week) !== Number(dayViewTab)) return false;
      return true;
    });
  }, [tabResponsibilities, selectedRoleView, dayViewTab]);

  const viewEmployees = useMemo(() => {
    if (!hasRoleViewFilter(selectedRoleView) && dayViewTab === SCHEDULE_VIEW_ALL) {
      return tabEmployees;
    }
    const userIds = new Set(
      [...viewEntries, ...viewResponsibilities].map((item) => Number(item.user_id)),
    );
    return tabEmployees.filter((employee) => userIds.has(Number(employee.user_id)));
  }, [tabEmployees, viewEntries, viewResponsibilities, selectedRoleView, dayViewTab]);

  const responsibilitiesByCell = useMemo(() => {
    const map = {};
    for (const item of viewResponsibilities) {
      const key = `${item.user_id}:${item.day_of_week}`;
      if (!map[key]) map[key] = [];
      map[key].push(item);
    }
    return map;
  }, [viewResponsibilities]);

  const visibleDayColumns = useMemo(() => visibleDayIndices(dayViewTab), [dayViewTab]);
  const visibleDayLabels = useMemo(
    () => visibleDayColumns.map((dow) => DAY_LABELS[dow]),
    [visibleDayColumns],
  );
  const scheduleViewLabel = useMemo(
    () => scheduleViewSummaryLabel(selectedRoleView, dayViewTab),
    [selectedRoleView, dayViewTab],
  );

  const entriesByCell = useMemo(() => {
    const map = {};
    for (const entry of viewEntries) {
      const key = `${entry.user_id}:${entry.day_of_week}`;
      if (!map[key]) map[key] = [];
      map[key].push(entry);
    }
    return map;
  }, [viewEntries]);

  const tabUserIds = useMemo(
    () => viewEmployees.map((employee) => employee.user_id),
    [viewEmployees],
  );

  const weekSummary = useMemo(
    () =>
      data
        ? computeWeekSummary(data, {
            includeExcluded: showExcluded,
            userIds: tabUserIds,
            entries: viewEntries,
            daysOnly,
          })
        : null,
    [data, showExcluded, tabUserIds, viewEntries, daysOnly],
  );

  const filteredDaySummaries = useMemo(
    () =>
      data
        ? computeFilteredDaySummaries(data, {
            userIds: tabUserIds,
            includeExcluded: showExcluded,
            entries: viewEntries,
          })
        : [],
    [data, tabUserIds, showExcluded, viewEntries],
  );

  const visibleEmployees = useMemo(() => {
    const shown = showExcluded ? viewEmployees : viewEmployees.filter((e) => !e.excluded);
    return withDisplayedTotals(shown, viewEntries);
  }, [viewEmployees, showExcluded, viewEntries]);

  const visibleUserIds = useMemo(
    () => new Set(visibleEmployees.map((e) => Number(e.user_id))),
    [visibleEmployees],
  );
  const timeViewEntries = useMemo(
    () => viewEntries.filter((entry) => visibleUserIds.has(Number(entry.user_id))),
    [viewEntries, visibleUserIds],
  );
  const timeViewResponsibilities = useMemo(
    () => viewResponsibilities.filter((item) => visibleUserIds.has(Number(item.user_id))),
    [viewResponsibilities, visibleUserIds],
  );
  const employeesById = useMemo(
    () => Object.fromEntries((data?.employees || []).map((e) => [e.user_id, e])),
    [data?.employees],
  );
  const hoursSummary = useMemo(
    () =>
      summarizeSelectedRoleHours(
        timeViewEntries,
        new Map((data?.employees || []).map((e) => [Number(e.user_id), e])),
        matrixRoles,
      ),
    // roleCatalog: role order, labels, and task/role type come from the registered catalog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [timeViewEntries, data?.employees, matrixRoles, roleCatalog],
  );
  const shiftCategoryChoices = useCallback(
    (userId) => shiftEntityChoicesForEmployee(employeesById[userId], organizationSlug),
    [employeesById, organizationSlug],
  );
  const scheduleTemplate = data?.schedule_template || null;
  const hiddenRolesSetting = display.hidden_schedule_roles;
  const coverageRoleOptions = useMemo(() => {
    const hidden = new Set(hiddenRolesSetting || []);
    const codes = new Set(
      roleCatalog
        .filter((role) => role.active !== false && role.uses_time_slots !== false && !hidden.has(role.code))
        .map((role) => role.code),
    );
    for (const entry of timeViewEntries) {
      for (const assignment of entryRoleAssignments(entry)) {
        if (assignment.role && !isScheduleTask(assignment.role)) codes.add(assignment.role);
      }
    }
    return sortRoles([...codes]);
  }, [roleCatalog, hiddenRolesSetting, timeViewEntries]);
  const coverageAllHours = useMemo(
    () =>
      buildHourlyCoverage(timeViewEntries, {
        dayIndices: visibleDayColumns,
        employeesById,
        responsibilities: timeViewResponsibilities,
        roles: matrixRoles,
      }),
    // roleCatalog + roleGroups: column order and labels come from the registered catalog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [timeViewEntries, visibleDayColumns, employeesById, timeViewResponsibilities, matrixRoles, roleCatalog, roleGroups],
  );
  const coverageMatrixColumns = useMemo(
    () => (Array.isArray(matrixRoles) ? sortRoles(matrixRoles) : coverageColumns(coverageAllHours)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [matrixRoles, coverageAllHours, roleCatalog],
  );
  const coverageHourBounds = useMemo(() => {
    const hours = coverageAllHours.flatMap((day) => day.hours.map((row) => row.hour));
    return hours.length ? { min: Math.min(...hours), max: Math.max(...hours) } : null;
  }, [coverageAllHours]);
  const coverageDays = useMemo(
    () => filterCoverageHours(coverageAllHours, coverageRange),
    [coverageAllHours, coverageRange],
  );

  const addableEmployees = useMemo(() => {
    const ids = new Set(tabEmployees.map((e) => Number(e.user_id)));
    return addableForTab.filter((e) => !ids.has(Number(e.user_id)));
  }, [addableForTab, tabEmployees]);

  const excludedCount = useMemo(
    () => viewEmployees.filter((e) => e.excluded).length,
    [viewEmployees],
  );

  const employeeColWidth = isTablet ? "minmax(180px, 195px)" : "minmax(185px, 200px)";
  const dayColWidth = isTablet ? "minmax(148px, 1fr)" : "minmax(158px, 1fr)";
  const gridMinWidth = isTablet
    ? 195 + visibleDayColumns.length * 148
    : 200 + visibleDayColumns.length * 158;

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

  const openCreate = (userId, day, extras = {}) => {
    setEditingEntry(null);
    setEditingResponsibility(null);
    setDialogError("");
    setDialogDefaults({ userId, day, ...extras });
    setDialogOpen(true);
  };

  const openEdit = (entry) => {
    setEditingEntry(entry);
    setEditingResponsibility(null);
    setDialogError("");
    setDialogDefaults({ userId: entry.user_id, day: entry.day_of_week });
    setDialogOpen(true);
  };

  const openEditResponsibility = (item) => {
    setEditingEntry(null);
    setEditingResponsibility(item);
    setDialogError("");
    setDialogDefaults({ userId: item.user_id, day: item.day_of_week, kind: ASSIGNMENT_KIND.RESPONSIBILITY });
    setDialogOpen(true);
  };

  const openCreateFromTimeView = ({ day, role, startTime, endTime, kind }) => {
    openCreate(null, day, { role, startTime, endTime, kind, pickEmployee: true });
  };

  const pickerEmployees = useMemo(
    () =>
      [...tabEmployees.filter((e) => !e.excluded), ...addableEmployees].sort((a, b) =>
        String(a.display_name || "").localeCompare(String(b.display_name || "")),
      ),
    [tabEmployees, addableEmployees],
  );

  const handleSave = async (form) => {
    setSaving(true);
    setDialogError("");
    const { kind, ...body } = form;
    try {
      let res;
      if (kind === ASSIGNMENT_KIND.RESPONSIBILITY) {
        res = editingResponsibility?.id
          ? await updateWeeklyScheduleResponsibility(editingResponsibility.id, body)
          : await createWeeklyScheduleResponsibility({ week_start: weekStart, ...body });
      } else if (editingEntry?.id) {
        res = await updateWeeklyScheduleEntry(editingEntry.id, body);
      } else {
        res = await createWeeklyScheduleEntry({
          week_start: weekStart,
          ...body,
          employer_affiliation:
            body.employer_affiliation || defaultNewShiftEntity(employeesById[body.user_id], organizationSlug),
        });
      }
      setData(res.data);
      setDialogOpen(false);
    } catch (e) {
      setDialogError(e?.response?.data?.error || "Failed to save assignment");
    } finally {
      setSaving(false);
    }
  };

  const handleDialogDelete = async () => {
    if (editingResponsibility?.id) {
      if (!window.confirm("Remove this task?")) return;
      setSaving(true);
      setDialogError("");
      try {
        const res = await deleteWeeklyScheduleResponsibility(editingResponsibility.id);
        setData(res.data);
        setDialogOpen(false);
      } catch (e) {
        setDialogError(e?.response?.data?.error || "Failed to remove task");
      } finally {
        setSaving(false);
      }
      return;
    }
    if (editingEntry?.id) {
      if (!window.confirm("Delete this shift?")) return;
      setSaving(true);
      setDialogError("");
      try {
        const res = await deleteWeeklyScheduleEntry(editingEntry.id);
        setData(res.data);
        setDialogOpen(false);
      } catch (e) {
        setDialogError(e?.response?.data?.error || "Failed to delete shift");
      } finally {
        setSaving(false);
      }
    }
  };

  const handleCatalogChange = (roles) => {
    setData((prev) => (prev ? { ...prev, role_catalog: roles } : prev));
  };

  const handleGroupsChange = (groups) => {
    setData((prev) => (prev ? { ...prev, role_groups: groups } : prev));
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

  const handleSetEmployer = async (entry, employerAffiliation) => {
    setError("");
    try {
      const res = await updateWeeklyScheduleEntry(entry.id, { employer_affiliation: employerAffiliation });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update shift employer");
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
    if (printContentRef.current) {
      openWeeklySchedulePrintWindow(printContentRef.current);
    }
  };

  const handleExport = () => {
    const viewSuffix = scheduleViewLabel ? ` - ${scheduleViewLabel}` : "";
    if (viewMode === VIEW_MODE.TIME_ROLE) {
      exportWeeklyScheduleHourlyCsv({
        days: coverageDays,
        weekStart,
        columns: coverageMatrixColumns,
        tabLabel: `${ENTITY_TAB_LABELS[employerTab]}${viewSuffix}`,
        hoursSummary,
      });
      return;
    }
    exportWeeklyScheduleCsv({
      employees: visibleEmployees,
      entries: viewEntries,
      weekStart,
      tabLabel: `${ENTITY_TAB_LABELS[employerTab]}${viewSuffix}`,
      showRoleLabels,
      scheduleEndTimeEnabled,
      dayLabels: visibleDayLabels.length === 7 ? undefined : visibleDayLabels,
      dayIndices: visibleDayColumns.length === 7 ? undefined : visibleDayColumns,
      daySummaries: filteredDaySummaries,
      responsibilities: timeViewResponsibilities,
    });
  };

  const handleBulkMoveToRinseExclusive = async () => {
    if (
      !window.confirm(
        "Move every shift this week to Rinse Exclusive? Worker profiles are updated too so they stay on the Rinse Exclusive tab.",
      )
    ) {
      return;
    }
    setBulkEmployerSaving(true);
    setError("");
    try {
      const res = await bulkSetWeeklyScheduleEmployer({
        week_start: weekStart,
        employer_affiliation: SHIFT_EMPLOYER_AFFILIATION.RINSE_EXCLUSIVE,
      });
      setData(res.data);
      setEmployerTab(ENTITY_TAB.RINSE_EXCLUSIVE);
      const skipped = res.data?.entries_skipped || [];
      if (skipped.length) {
        setError(`Moved ${res.data?.entries_updated || 0} shifts. Skipped ${skipped.length} (None-affiliated) shift(s).`);
      }
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to move shifts to Rinse Exclusive");
    } finally {
      setBulkEmployerSaving(false);
    }
  };

  const handleEnableTemplate = async () => {
    const res = await enableWeeklyScheduleTemplate(weekStart);
    setData(res.data);
    return res.data?.cascade;
  };

  const handleCopySelected = async (targetWeeks) => {
    const res = await cascadeWeeklySchedule({ source_week_start: weekStart, target_weeks: targetWeeks });
    setData(res.data);
    return res.data?.cascade;
  };

  const handleStopTemplate = async () => {
    const res = await disableWeeklyScheduleTemplate(weekStart);
    setData(res.data);
    return res.data?.cascade;
  };

  const stopTemplateFromBanner = async () => {
    if (!window.confirm("Stop the ongoing template? Later weeks keep their current planned assignments.")) return;
    setTemplateSaving(true);
    setError("");
    try {
      await handleStopTemplate();
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to stop the template");
    } finally {
      setTemplateSaving(false);
    }
  };

  const showToolbarChips =
    (excludedCount > 0 && canManageExclusions) || costAllowed;

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
    scheduleEndTimeEnabled,
    openEdit,
    handleDelete,
    handleDuplicate,
    handleSetEmployer,
    organizationSlug,
    openEditResponsibility,
  };

  return (
    <Box
      className="weekly-schedule-print-root"
      sx={{
        p: { xs: 0, md: 0.5 },
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        width: "100%",
        maxWidth: "100%",
        minWidth: 0,
        boxSizing: "border-box",
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <Paper
        className="weekly-schedule-print-area"
        elevation={0}
        sx={{
          borderRadius: { xs: 0, md: 3 },
          overflow: "hidden",
          width: "100%",
          maxWidth: "100%",
          minWidth: 0,
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          border: { xs: "none", md: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}` },
          boxShadow: { xs: "none", md: "0 8px 30px rgba(15, 23, 42, 0.06)" },
        }}
      >
        <Box
          ref={stickyHeaderRef}
          className="no-print weekly-schedule-sticky-header"
          sx={{
            flexShrink: 0,
            bgcolor: "#fff",
            borderBottom: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
            borderRadius: { md: "12px 12px 0 0" },
          }}
        >
          <Box
            sx={{
              px: { xs: 1.25, md: 1.5 },
              py: { xs: 0.5, md: 0.65 },
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 1,
              flexWrap: "wrap",
            }}
          >
            <Stack direction="row" spacing={1.25} alignItems="baseline" flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
              <Typography
                variant="subtitle1"
                fontWeight={800}
                sx={{ letterSpacing: "-0.02em", color: VEEWASH_DASHBOARD.primaryBlueDark, lineHeight: 1.2 }}
              >
                Weekly Schedule
              </Typography>
              {hideEmployerTabs ? (
                <Typography variant="body2" sx={{ color: "text.secondary", fontWeight: 600, lineHeight: 1.2 }}>
                  {ENTITY_TAB_LABELS[employerTab]}
                </Typography>
              ) : null}
            </Stack>
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
              <Stack
                direction="row"
                spacing={0.25}
                alignItems="center"
                sx={{
                  border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  borderRadius: 999,
                  bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
                  px: 0.25,
                  py: 0.125,
                }}
              >
                <IconButton
                  size="small"
                  onClick={() => changeWeek(-1)}
                  disabled={!canGoToPreviousWeek}
                  sx={{
                    color: VEEWASH_DASHBOARD.primaryBlueDark,
                    opacity: canGoToPreviousWeek ? 1 : 0.4,
                  }}
                >
                  <ChevronLeftIcon fontSize="small" />
                </IconButton>
                <Typography
                  variant="body2"
                  sx={{
                    minWidth: { xs: 160, md: 200 },
                    textAlign: "center",
                    fontWeight: 700,
                    color: VEEWASH_DASHBOARD.primaryBlueDark,
                    fontSize: "0.8125rem",
                  }}
                >
                  {formatWeekRange(weekStart)}
                </Typography>
                <IconButton
                  size="small"
                  onClick={() => changeWeek(1)}
                  sx={{ color: VEEWASH_DASHBOARD.primaryBlueDark }}
                >
                  <ChevronRightIcon fontSize="small" />
                </IconButton>
              </Stack>
              <ToggleButtonGroup
                size="small"
                exclusive
                value={viewMode}
                onChange={(_, value) => {
                  if (!value) return;
                  if (value === VIEW_MODE.TIME_ROLE) setSelectedRoleView([]);
                  setViewMode(value);
                }}
                sx={{
                  height: 30,
                  "& .MuiToggleButton-root": {
                    px: 1,
                    py: 0.25,
                    fontWeight: 700,
                    fontSize: "0.74rem",
                    textTransform: "none",
                  },
                }}
              >
                <ToggleButton value={VIEW_MODE.EMPLOYEE}>By employee</ToggleButton>
                <ToggleButton value={VIEW_MODE.TIME_ROLE}>By time &amp; role</ToggleButton>
              </ToggleButtonGroup>
              {canEdit && addableEmployees.length ? (
                <Select
                  size="small"
                  displayEmpty
                  value=""
                  onChange={(e) => {
                    const uid = Number(e.target.value);
                    if (!uid) return;
                    openCreate(uid, visibleDayColumns[0] ?? 0);
                  }}
                  startAdornment={<PersonAddAlt1OutlinedIcon sx={{ fontSize: 16, mr: 0.5, color: "text.secondary" }} />}
                  sx={{
                    minWidth: 168,
                    fontWeight: 700,
                    fontSize: "0.78rem",
                    height: 30,
                    "& .MuiSelect-select": { py: 0.35 },
                  }}
                  renderValue={() => "Add employee"}
                >
                  {addableEmployees.map((emp) => (
                    <MenuItem key={emp.user_id} value={emp.user_id}>
                      {emp.display_name || `User #${emp.user_id}`}
                    </MenuItem>
                  ))}
                </Select>
              ) : null}
              {canEdit ? (
                <Button
                  size="small"
                  variant="outlined"
                  component={RouterLink}
                  to="/performance/user-mapping"
                  sx={{ fontWeight: 700, py: 0.35 }}
                >
                  User mapping
                </Button>
              ) : null}
              {canEdit ? (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setRolesOpen(true)}
                  sx={{ fontWeight: 700, py: 0.35 }}
                >
                  Roles &amp; tasks
                </Button>
              ) : null}
              {canEdit ? (
                <Button
                  size="small"
                  variant="outlined"
                  disabled={bulkEmployerSaving || !data?.entries?.length}
                  onClick={handleBulkMoveToRinseExclusive}
                  sx={{ fontWeight: 700, py: 0.35 }}
                >
                  {bulkEmployerSaving ? "Moving…" : "All → Rinse Exclusive"}
                </Button>
              ) : null}
              {canEdit ? (
                <Button
                  size="small"
                  variant="outlined"
                  disabled={!data?.entries?.length && !data?.daily_responsibilities?.length}
                  onClick={() => setCascadeOpen(true)}
                  sx={{ fontWeight: 700, py: 0.35 }}
                >
                  Copy to future weeks
                </Button>
              ) : null}
              <Button
                size="small"
                variant="outlined"
                startIcon={<FileDownloadOutlinedIcon />}
                onClick={handleExport}
                disabled={!visibleEmployees.length}
                sx={{ fontWeight: 700, py: 0.35 }}
              >
                Export Excel
              </Button>
              <Button
                size="small"
                variant="contained"
                startIcon={<PrintIcon />}
                onClick={handlePrint}
                disabled={!visibleEmployees.length}
                sx={{
                  fontWeight: 700,
                  py: 0.35,
                  bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                  "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
                }}
              >
                Print
              </Button>
            </Stack>
          </Box>

              {!hideEmployerTabs ? (
            <Box sx={{ px: 1.25, pt: 0, pb: 0, borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}` }}>
              <Tabs
                value={employerTab}
                onChange={(_, value) => setEmployerTab(value)}
                sx={{
                  minHeight: 30,
                  "& .MuiTab-root": {
                    minHeight: 30,
                    py: 0.25,
                    fontWeight: 700,
                    fontSize: "0.78rem",
                    textTransform: "none",
                  },
                }}
              >
                {entityTabs.map((tabKey) => (
                  <Tab
                    key={tabKey}
                    value={tabKey}
                    label={`${ENTITY_TAB_LABELS[tabKey]} (${countEmployeesForEmployerTab(
                      data?.employees || [],
                      tabKey,
                      data?.entries || [],
                      organizationSlug,
                    )})`}
                  />
                ))}
              </Tabs>
            </Box>
          ) : null}

          {!loading && data ? (
            <WeeklyScheduleViewTabs
              entries={tabEntries}
              selectedRoles={selectedRoleView}
              onSelectedRolesChange={setSelectedRoleView}
              dayTab={dayViewTab}
              onDayTabChange={setDayViewTab}
              hiddenRoles={hiddenScheduleRoles}
              roleCatalog={roleCatalog}
              responsibilities={tabResponsibilities}
              hideRoles={viewMode === VIEW_MODE.TIME_ROLE}
            />
          ) : null}

          {showToolbarChips ? (
            <Box
              sx={{
                px: 1.25,
                py: 0.35,
                borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                display: "flex",
                alignItems: "center",
                gap: 0.75,
                flexWrap: "wrap",
              }}
            >
              {excludedCount > 0 && canManageExclusions ? (
                <Chip
                  icon={<PersonOffOutlinedIcon />}
                  label={showExcluded ? `Showing excluded (${excludedCount})` : `Show excluded (${excludedCount})`}
                  onClick={() => setShowExcluded((v) => !v)}
                  color={showExcluded ? "warning" : "default"}
                  variant={showExcluded ? "filled" : "outlined"}
                  size="small"
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
                  size="small"
                  sx={{ fontWeight: 700 }}
                />
              ) : null}
            </Box>
          ) : null}
        </Box>

        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            p: { xs: 0.75, md: 0.85 },
          }}
        >
          {excludedCount > 0 && !showExcluded && canManageExclusions ? (
            <Alert
              severity="info"
              className="no-print"
              sx={{ mb: 1.25, borderRadius: 2, flexShrink: 0 }}
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
          {scheduleTemplate?.enabled ? (
            <Alert
              severity={scheduleTemplate.is_source ? "success" : "info"}
              sx={{ mb: 1.25, borderRadius: 2, flexShrink: 0 }}
              className="no-print"
              action={
                canEdit ? (
                  <Stack direction="row" spacing={0.5}>
                    {scheduleTemplate.follows_template ? (
                      <Button
                        color="inherit"
                        size="small"
                        sx={{ fontWeight: 700 }}
                        onClick={() => {
                          setWeekStart(scheduleTemplate.source_week_start);
                          load(scheduleTemplate.source_week_start);
                        }}
                      >
                        Open template week
                      </Button>
                    ) : null}
                    <Button
                      color="inherit"
                      size="small"
                      sx={{ fontWeight: 700 }}
                      disabled={templateSaving}
                      onClick={stopTemplateFromBanner}
                    >
                      {templateSaving ? "Stopping…" : "Stop"}
                    </Button>
                  </Stack>
                ) : null
              }
            >
              {scheduleTemplate.is_source
                ? "Propagation on: this week is the ongoing template. Additions, edits, and deletions here are copied to every later week automatically."
                : scheduleTemplate.follows_template
                  ? `Propagation on: this week follows the template week of ${formatWeekRange(
                      scheduleTemplate.source_week_start,
                    )}. Changes to that week replace this week's planned assignments.`
                  : `Propagation on from the template week of ${formatWeekRange(scheduleTemplate.source_week_start)} to all later weeks.`}
            </Alert>
          ) : null}
          {data?.carried_forward_from ? (
            <Alert severity="info" sx={{ mb: 1.25, borderRadius: 2, flexShrink: 0 }} className="no-print">
              Schedule copied from the week of{" "}
              {formatWeekRange(normalizeWeekStart(data.carried_forward_from))}. Edit shifts here as needed.
            </Alert>
          ) : null}
          {!loading && data && scheduleViewLabel ? (
            <Typography
              variant="caption"
              className="no-print"
              sx={{ display: "block", mb: 0.5, px: 0.25, color: "text.secondary", fontWeight: 600 }}
            >
              View: {entityLabel(employerTab)} · {scheduleViewLabel}
              {employerTab === ENTITY_TAB.COMBINED ? " (admin)" : ""}
            </Typography>
          ) : null}

          {error ? (
            <Alert severity="error" sx={{ mb: 1.25, flexShrink: 0 }} className="no-print">
              {error}
            </Alert>
          ) : null}
          {loading ? (
            <Stack alignItems="center" py={6} className="no-print" sx={{ flex: 1 }}>
              <CircularProgress size={32} />
            </Stack>
          ) : (
            <>
              <Box sx={{ flexShrink: 0 }}>
                <WeeklyScheduleSummaryBar
                  summary={weekSummary}
                  showCost={showCost && costAllowed}
                  compact
                  hideRoleBreakdown={hasRoleViewFilter(selectedRoleView) || dayViewTab !== SCHEDULE_VIEW_ALL}
                />
              </Box>

              <Box
                sx={{
                  flex: 1,
                  minHeight: 0,
                  overflow: "auto",
                  WebkitOverflowScrolling: "touch",
                  width: "100%",
                  maxWidth: "100%",
                }}
                className="weekly-schedule-grid-scroll"
              >
                {viewMode === VIEW_MODE.TIME_ROLE ? (
                  <>
                    <HourlyCoverageControls
                      roleOptions={coverageRoleOptions}
                      selectedRoles={matrixRoles}
                      onSelectedRolesChange={setMatrixRoles}
                      showNames={showCoverageNames}
                      onShowNamesChange={setShowCoverageNames}
                      fromHour={coverageRange.fromHour}
                      toHour={coverageRange.toHour}
                      hourBounds={coverageHourBounds}
                      onHourRangeChange={setCoverageRange}
                    />
                    <WeeklyScheduleHoursSummary summary={hoursSummary} scopeLabel={scheduleViewLabel} />
                    <WeeklyScheduleTimeRoleView
                      weekStart={weekStart}
                      days={coverageDays}
                      columns={coverageMatrixColumns}
                      showNames={showCoverageNames}
                      endTimeEnabled={scheduleEndTimeEnabled}
                      canEdit={canEdit}
                      onEditEntry={openEdit}
                      onEditResponsibility={openEditResponsibility}
                      onAdd={openCreateFromTimeView}
                    />
                  </>
                ) : isMobile ? (
                  <Stack spacing={1.5} className="weekly-schedule-mobile-stack" sx={{ pb: 2 }}>
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
                          entries={viewEntries}
                          excluded={excluded}
                          canManageExclusions={canManageExclusions}
                          excludeSaving={excludeSavingUserId === employee.user_id}
                          onExcludeToggle={handleExcludeToggle}
                          showCost={showCost}
                          showRates={showEmployeeRates}
                          costAllowed={costAllowed}
                          daysOnly={daysOnly}
                          onViewSchedule={openEmployeeView}
                        />
                        <Box sx={{ px: 1.25, pb: 1.25, display: "grid", gap: 0.75 }}>
                          {visibleDayColumns.map((dow) => {
                            const dayLabel = DAY_LABELS[dow];
                            const cellKey = `${employee.user_id}:${dow}`;
                            const cellEntries = entriesByCell[cellKey] || [];
                            const cellResponsibilities = responsibilitiesByCell[cellKey] || [];
                            if (!cellEntries.length && !cellResponsibilities.length && excluded) return null;
                            return (
                              <ScheduleDayCell
                                key={cellKey}
                                employee={employee}
                                dow={dow}
                                dayLabel={dayLabel}
                                cellEntries={cellEntries}
                                cellResponsibilities={cellResponsibilities}
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
                <Box
                  sx={{
                    width: "100%",
                    minWidth: 0,
                    pb: 1,
                  }}
                  className="weekly-schedule-screen-grid"
                >
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: `${employeeColWidth} repeat(${visibleDayColumns.length}, ${dayColWidth})`,
                      minWidth: gridMinWidth,
                      gap: 0,
                      border: "1px solid #e2e8f0",
                      borderRadius: 2.5,
                      overflow: "visible",
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
                        top: 0,
                        zIndex: 5,
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
                    {visibleDayColumns.map((dow) => {
                      const label = DAY_LABELS[dow];
                      return (
                      <Box
                        key={label}
                        sx={{
                          borderBottom: "1px solid #e2e8f0",
                          borderLeft: "1px solid #e2e8f0",
                          position: "sticky",
                          top: 0,
                          zIndex: 3,
                          bgcolor: "#f8fafc",
                        }}
                      >
                        <WeeklyScheduleDayHeader
                          dayLabel={label}
                          summary={daySummary(filteredDaySummaries[dow] || dayTotals[dow])}
                          daysOnly={daysOnly}
                          compact
                        />
                      </Box>
                    );})}

                    {(visibleEmployees || []).map((employee) => {
                      const excluded = Boolean(employee.excluded);
                      return (
                        <Box key={employee.user_id} sx={{ display: "contents" }}>
                          <WeeklyScheduleEmployeeCell
                            employee={employee}
                            entries={viewEntries}
                            excluded={excluded}
                            canManageExclusions={canManageExclusions}
                            excludeSaving={excludeSavingUserId === employee.user_id}
                            onExcludeToggle={handleExcludeToggle}
                            showCost={showCost}
                            showRates={showEmployeeRates}
                            costAllowed={costAllowed}
                            onViewSchedule={openEmployeeView}
                          />
                          {visibleDayColumns.map((dow) => {
                            const dayLabel = DAY_LABELS[dow];
                            const cellKey = `${employee.user_id}:${dow}`;
                            const cellEntries = entriesByCell[cellKey] || [];
                            return (
                              <ScheduleDayCell
                                key={cellKey}
                                employee={employee}
                                dow={dow}
                                dayLabel={dayLabel}
                                cellEntries={cellEntries}
                                cellResponsibilities={responsibilitiesByCell[cellKey] || []}
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
              </Box>
            </>
          )}
        </Box>
      </Paper>

      {!loading && data ? (
        <Box
          ref={printContentRef}
          className="weekly-schedule-print-document"
          aria-hidden
          sx={{
            position: "absolute",
            left: -10000,
            top: 0,
            width: "11in",
            pointerEvents: "none",
          }}
        >
          <div className="weekly-schedule-print-doc-header">
            <div className="weekly-schedule-print-doc-title">
              Weekly Schedule — {ENTITY_TAB_LABELS[employerTab]}
              {viewMode === VIEW_MODE.TIME_ROLE ? " — Hourly coverage by role" : ""}
              {scheduleViewLabel ? ` — ${scheduleViewLabel}` : ""}
            </div>
            <div className="weekly-schedule-print-doc-subtitle">{formatWeekRange(weekStart)}</div>
          </div>
          {viewMode === VIEW_MODE.TIME_ROLE ? (
            <WeeklyScheduleTimeRolePrint
              days={coverageDays}
              weekStart={weekStart}
              columns={coverageMatrixColumns}
              showNames={showCoverageNames}
              hoursSummary={hoursSummary}
            />
          ) : (
            <WeeklySchedulePrintTable
              employees={visibleEmployees}
              entries={viewEntries}
              dayLabels={visibleDayLabels}
              dayIndices={visibleDayColumns}
              daySummaries={filteredDaySummaries}
              showRoleLabels={showRoleLabels}
              daysOnly={daysOnly}
              responsibilities={timeViewResponsibilities}
            />
          )}
        </Box>
      ) : null}

      <WeeklyScheduleEntryDialog
        open={dialogOpen && canEdit}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        onDelete={editingEntry?.id || editingResponsibility?.id ? handleDialogDelete : undefined}
        saving={saving}
        error={dialogError}
        entry={editingEntry}
        responsibility={editingResponsibility}
        defaultUserId={dialogDefaults.userId}
        defaultDay={dialogDefaults.day}
        defaultKind={dialogDefaults.kind}
        defaultRole={dialogDefaults.role}
        defaultStartTime={dialogDefaults.startTime}
        defaultEndTime={dialogDefaults.endTime}
        employees={dialogDefaults.pickEmployee ? pickerEmployees : undefined}
        scheduleEndTimeEnabled={scheduleEndTimeEnabled}
        shiftCategoryChoices={shiftCategoryChoices}
        categoryLabel={entityLabel}
        dailyResponsibilities={data?.daily_responsibilities}
      />
      <WeeklyScheduleManageRolesDialog
        open={rolesOpen && canEdit}
        onClose={() => setRolesOpen(false)}
        roles={roleCatalog}
        groups={roleGroups}
        onCatalogChange={handleCatalogChange}
        onGroupsChange={handleGroupsChange}
      />
      <WeeklyScheduleCascadeDialog
        open={cascadeOpen && canEdit}
        onClose={() => setCascadeOpen(false)}
        sourceWeekStart={weekStart}
        template={scheduleTemplate}
        onEnableTemplate={handleEnableTemplate}
        onCopySelected={handleCopySelected}
        onStopTemplate={handleStopTemplate}
      />
    </Box>
  );
}
