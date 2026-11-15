import { useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { useI18n } from "../../i18n/I18nContext";
import {
  Box,
  Button,
  IconButton,
  InputAdornment,
  Menu,
  MenuItem,
  Popper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import AccessTimeOutlinedIcon from "@mui/icons-material/AccessTimeOutlined";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CoffeeOutlinedIcon from "@mui/icons-material/CoffeeOutlined";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import GroupsOutlinedIcon from "@mui/icons-material/GroupsOutlined";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import PersonAddAlt1OutlinedIcon from "@mui/icons-material/PersonAddAlt1Outlined";
import SearchIcon from "@mui/icons-material/Search";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import { getManagementTaskDashboard } from "../../api";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { parseTimeToMinutes } from "../../payroll/schedulePlanner";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { DAY_LABELS } from "./weeklyScheduleDates";
import {
  BREAK_OVERLAP_CAP,
  applyDashboardRow,
  calendarDateForDay,
  matchDashboardAssignment,
} from "./breaksTasksPlannerModel";
import {
  dayBreakDetail,
  describeRoleHourDisplay,
  entryHasRole,
  roleTimelineFromCoverage,
  roundHoursForDisplay,
  shiftRoleSegments,
  taskStatusRollup,
} from "./operationsPlannerModel";
import {
  entryBreakBreakdown,
  formatRoleHoursLabel,
  isScheduleTask,
  parseEntryRoles,
  roleCompactLabel,
  roleStyle,
  scheduleRoleLabel,
} from "./weeklyScheduleRoles";

const CORE_ROLES = ["weigher", "sort", "wash", "dry", "fold", "hd_operator", "hd_folder"];
const AVATAR_COLORS = ["#1d4ed8", "#0f766e", "#b45309", "#7c3aed", "#be185d", "#0369a1", "#047857"];

const LENS = { EMPLOYEES: "employees", BREAKS: "breaks", TASKS: "tasks" };
const MODE = { WEEK: "week", DAY: "day" };
const PANEL = { SUMMARY: "summary", ROLES: "roles", BREAKS: "breaks", TASKS: "tasks" };

function clockMinutes(value) {
  const parsed = parseTimeToMinutes(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function minutesLabel(mins) {
  if (mins == null || !Number.isFinite(mins)) return "";
  const h = Math.floor(mins / 60) % 24;
  const m = Math.floor(mins % 60);
  return formatTime12(`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`);
}

function timerLabel(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "";
  const total = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}

function checklistLine(items, status) {
  if (!Array.isArray(items) || !items.length) return "";
  const done = items.filter((item) => item.completed_by_name || ["completed", "approved", "done"].includes(String(item.status || "").toLowerCase())).length;
  return `${done}/${items.length}${status ? ` · ${status}` : ""}`;
}

function hourText(value) {
  return roundHoursForDisplay(value).toFixed(1);
}

function exactHourText(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "0h";
  return `${Math.round(number * 10000) / 10000}h`;
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function dayStamp(weekStart, day) {
  const iso = calendarDateForDay(weekStart, day);
  if (!iso) return "";
  const [year, month, date] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function placeBar(start, end, windowStart, span) {
  if (start == null || end == null) return null;
  let finish = end;
  while (finish <= start) finish += 24 * 60;
  const left = ((start - windowStart) / span) * 100;
  const width = ((finish - start) / span) * 100;
  return {
    left: `${Math.max(0, left)}%`,
    width: `${Math.max(1.5, Math.min(100 - Math.max(0, left), width))}%`,
  };
}

function Segmented({ value, onChange, options, label }) {
  return (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={value}
      aria-label={label}
      onChange={(_, next) => {
        if (next) onChange(next);
      }}
      sx={{
        height: 26,
        bgcolor: "#fff",
        "& .MuiToggleButton-root": {
          px: 0.9,
          py: 0,
          fontSize: "0.68rem",
          fontWeight: 700,
          textTransform: "none",
          lineHeight: 1.2,
          borderColor: VEEWASH_DASHBOARD.snapshotBorder,
        },
      }}
    >
      {options.map((option) => (
        <ToggleButton key={option.value} value={option.value}>
          {option.label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}

function statusText(t, bucket) {
  const key = {
    notStarted: "weeklySchedule.ops.notStarted",
    inProgress: "weeklySchedule.ops.inProgress",
    awaiting: "weeklySchedule.ops.awaiting",
    verified: "weeklySchedule.ops.verified",
    completed: "weeklySchedule.ops.completed",
    rejected: "weeklySchedule.ops.rejected",
  }[bucket];
  return key ? t(key) : bucket || "";
}

/**
 * One operations board. Week and Day share the week payload.
 * Drag moves a shift to another employee or day. Clock times stay in the shift editor.
 * A role card highlights. It does not change week headcount, gross, or net.
 */
export default function OperationsPlanner({
  weekLabel,
  weekStart = "",
  onPrevWeek,
  onNextWeek,
  canGoPrev = true,
  employerTabs = [],
  employerTab,
  onEmployerTab,
  hideEmployerTabs = false,
  employees = [],
  dayColumns = [],
  entriesByCell = {},
  responsibilitiesByCell = {},
  entries = [],
  weekSummary,
  coverageDays = [],
  focusDay,
  onFocusDay,
  mode,
  onMode,
  lens,
  onLens,
  canEdit = false,
  showBreaks = true,
  hideLaborHours = false,
  showRoleLabels = true,
  employeesById = {},
  onEditEntry,
  onCreate,
  onDropEntry,
  onEditResponsibility,
  onViewEmployee,
  draggingId = null,
  onDragStart,
  onDragEnd,
  addableEmployees = [],
  onAddEmployee,
  onAssign,
  onOpenMenu,
  menuAnchor,
  onCloseMenu,
  menuItems = [],
  children,
}) {
  const { t } = useI18n();
  const [hover, setHover] = useState(null);
  const [query, setQuery] = useState("");
  const [roleTip, setRoleTip] = useState(null);
  const [coverageTip, setCoverageTip] = useState(null);
  const coverageTimer = useRef(null);
  const showCoverageTip = (next) => {
    window.clearTimeout(coverageTimer.current);
    setCoverageTip(next);
  };
  const hideCoverageTip = () => {
    window.clearTimeout(coverageTimer.current);
    coverageTimer.current = window.setTimeout(() => setCoverageTip(null), 160);
  };
  const [dropKey, setDropKey] = useState("");
  const [highlightRole, setHighlightRole] = useState("");
  const [panel, setPanel] = useState(PANEL.SUMMARY);
  const [drill, setDrill] = useState("");
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [coverageOpen, setCoverageOpen] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  useEffect(() => {
    setHover(null);
  }, [mode, lens, focusDay]);
  useEffect(() => {
    if (!weekStart) {
      setDashboard(null);
      return undefined;
    }
    let cancelled = false;
    getManagementTaskDashboard({ date: calendarDateForDay(weekStart, focusDay) })
      .then((res) => {
        if (!cancelled) setDashboard(res.data || null);
      })
      .catch(() => {
        if (!cancelled) setDashboard(null);
      });
    return () => {
      cancelled = true;
    };
  }, [weekStart, focusDay]);

  const summary = weekSummary || {};
  const allTasks = useMemo(
    () => dayColumns.flatMap((day) => employees.flatMap((employee) => responsibilitiesByCell[`${employee.user_id}:${day}`] || [])),
    [dayColumns, employees, responsibilitiesByCell],
  );
  const rollup = useMemo(() => taskStatusRollup(allTasks, employeesById), [allTasks, employeesById]);
  const coverageDay = (coverageDays || []).find((day) => Number(day.dow) === Number(focusDay)) || null;
  const timeline = roleTimelineFromCoverage(coverageDay);
  const breaksByDay = useMemo(() => {
    const map = {};
    for (const day of dayColumns) map[day] = dayBreakDetail(entries, employeesById, day);
    return map;
  }, [dayColumns, entries, employeesById]);
  const dayBreaks = breaksByDay[focusDay] || { timed: [], untimed: [], maxOverlap: 0, hot: [] };
  const dayRoles = summary.roles || [];
  const dayLabel = DAY_LABELS[focusDay] || "";
  const tasksFor = (userId, day) => responsibilitiesByCell[`${userId}:${day}`] || [];
  const shiftsFor = (userId, day) => entriesByCell[`${userId}:${day}`] || [];
  const focusTasks = employees.flatMap((employee) => tasksFor(employee.user_id, focusDay));
  const groupsByDay = useMemo(() => {
    const map = {};
    for (const day of dayColumns) {
      const items = employees.flatMap((employee) => responsibilitiesByCell[`${employee.user_id}:${day}`] || []);
      map[day] = taskStatusRollup(items, employeesById).groups;
    }
    return map;
  }, [dayColumns, employees, responsibilitiesByCell, employeesById]);
  const dayRollup = useMemo(() => {
    const base = taskStatusRollup(focusTasks, employeesById);
    const shared = dashboard?.shared_assignments || [];
    base.groups = base.groups.map((group) => {
      const merged = applyDashboardRow(group, matchDashboardAssignment(group, shared));
      const again = taskStatusRollup(
        merged.members.map((member) => ({
          id: member.responsibilityId,
          user_id: member.userId,
          day_of_week: group.day,
          role: group.role,
          activity_status: member.status,
          assignment_group_id: group.groupId,
          execution_mode: group.shared ? "shared" : "individual",
          timing_label: group.timingLabel,
        })),
        employeesById,
      ).groups[0];
      if (!again) return { ...group, checklist: merged.checklist, checklistStatus: merged.checklistStatus };
      return {
        ...again,
        checklist: merged.checklist,
        checklistStatus: merged.checklistStatus,
        members: again.members.map((member) => {
          const live = merged.members.find((item) => Number(item.userId) === Number(member.userId));
          return { ...member, duration: live?.duration ?? null };
        }),
      };
    });
    return base;
  }, [focusTasks, employeesById, dashboard]);
  const finishedGroups = rollup.byGroup.verified + rollup.byGroup.completed;
  const roster = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return employees;
    return employees.filter((employee) => String(employee.display_name || "").toLowerCase().includes(needle));
  }, [employees, query]);
  const roleHourDisplay = useMemo(
    () => describeRoleHourDisplay(summary.roles || [], summary.totalHours),
    [summary.roles, summary.totalHours],
  );
  const roleCards = useMemo(() => {
    const byRole = new Map((summary.roles || []).map((row) => [row.role, row]));
    const extras = (summary.roles || []).map((row) => row.role).filter((role) => !CORE_ROLES.includes(role) && !isScheduleTask(role));
    return [...CORE_ROLES, ...extras].map((role) => {
      const row = byRole.get(role);
      return {
        role,
        label: row?.label || scheduleRoleLabel(role),
        employees: Number(row?.employees || 0),
        hours: Number(row?.hours || 0),
        unallocatedBreakHours: Number(row?.unallocatedBreakHours || 0),
      };
    });
  }, [summary.roles]);
  const warningDays = dayColumns.filter((day) => (breaksByDay[day]?.maxOverlap || 0) > BREAK_OVERLAP_CAP);
  const untimedCount = dayColumns.reduce((count, day) => count + (breaksByDay[day]?.untimed?.length || 0), 0);
  const hoursByUser = useMemo(() => {
    const map = {};
    for (const employee of employees) {
      let gross = 0;
      let breaks = 0;
      for (const entry of entries) {
        if (Number(entry.user_id) !== Number(employee.user_id)) continue;
        const parts = entryBreakBreakdown(entry);
        gross += parts.grossMinutes;
        breaks += parts.breakMinutes;
      }
      map[employee.user_id] = { gross: gross / 60, net: (gross - breaks) / 60 };
    }
    return map;
  }, [employees, entries]);
  const dayTotals = useMemo(() => {
    const map = {};
    for (const day of dayColumns) {
      let gross = 0;
      let breaks = 0;
      for (const entry of entries) {
        if (Number(entry.day_of_week) !== Number(day)) continue;
        const parts = entryBreakBreakdown(entry);
        gross += parts.grossMinutes;
        breaks += parts.breakMinutes;
      }
      map[day] = { gross: gross / 60, net: (gross - breaks) / 60 };
    }
    return map;
  }, [dayColumns, entries]);
  const copyItem = menuItems.find((item) => item.id === "copy");
  const onShift = employees.filter((employee) => shiftsFor(employee.user_id, focusDay).length).length;
  const dayGross = entries
    .filter((entry) => Number(entry.day_of_week) === Number(focusDay))
    .reduce((sum, entry) => sum + entryBreakBreakdown(entry).grossMinutes, 0) / 60;
  const dayNet = entries
    .filter((entry) => Number(entry.day_of_week) === Number(focusDay))
    .reduce((sum, entry) => sum + (entryBreakBreakdown(entry).grossMinutes - entryBreakBreakdown(entry).breakMinutes), 0) / 60;

  const windowStart = timeline.hours.length ? timeline.hours[0].hour * 60 : 6 * 60;
  const windowEnd = timeline.hours.length ? (timeline.hours[timeline.hours.length - 1].hour + 1) * 60 : 22 * 60;
  const span = Math.max(60, windowEnd - windowStart);

  const dropOn = (event, userId, day) => {
    event.preventDefault();
    const entryId = event.dataTransfer.getData("text/plain");
    setDropKey("");
    if (entryId) onDropEntry?.(userId, day, entryId);
  };
  const openDrill = (nextPanel, note, nextLens) => {
    setPanel(nextPanel);
    setDrill(note);
    if (nextLens) onLens?.(nextLens);
  };
  const toggleRole = (role) => {
    setHighlightRole((current) => (current === role ? "" : role));
    setPanel(PANEL.ROLES);
    setDrill(t("weeklySchedule.ops.highlightNote"));
  };

  const boardProps = {
    employees: roster,
    weekStart,
    hoursByUser,
    dayTotals,
    dayColumns,
    focusDay,
    onFocusDay,
    shiftsFor,
    tasksFor,
    lens,
    showBreaks,
    hideLaborHours,
    showRoleLabels,
    canEdit,
    dropKey,
    setDropKey,
    dropOn,
    onEditEntry,
    onCreate,
    onEditResponsibility,
    onViewEmployee,
    onDragStart,
    onDragEnd,
    draggingId,
    highlightRole,
    selectedUserId,
    onSelectUser: setSelectedUserId,
    breaksByDay,
    groupsByDay,
    employeesById,
    onHover: (anchor, entry, tasks) => setHover({ anchor, entry, tasks }),
    onLeave: () => setHover(null),
    t,
  };

  return (
    <Box data-ops-planner data-ops-mode={mode} data-ops-lens={lens} sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, flex: 1, overflow: "hidden", bgcolor: "#f4f7fb" }}>
      <Box
        data-ops-toolbar
        className="no-print"
        sx={{
          display: "flex",
          flexDirection: "column",
          gap: 0.6,
          px: 1.25,
          py: 0.7,
          bgcolor: "#fff",
          borderBottom: "1px solid #e6ebf2",
          flexShrink: 0,
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, fontSize: "1.15rem", lineHeight: 1.1, color: "#0f2744" }}>
              {t("weeklySchedule.ops.title")}
            </Typography>
            <Typography sx={{ fontSize: "0.68rem", color: "#64748b", fontWeight: 600 }}>
              Planned Labor · Shifts · Breaks · Tasks
            </Typography>
          </Box>
          <TextField
            size="small"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search employees..."
            aria-label="Search employees"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon sx={{ fontSize: 16, color: "#94a3b8" }} />
                </InputAdornment>
              ),
            }}
            sx={{ ml: "auto", width: 220, "& .MuiOutlinedInput-root": { borderRadius: 999, bgcolor: "#f8fafc", height: 32, fontSize: "0.75rem" } }}
          />
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, overflowX: "auto" }}>
        <Stack direction="row" alignItems="center" spacing={0.25} sx={{ border: "1px solid #e2e8f0", borderRadius: 999, px: 0.25, bgcolor: "#fff" }}>
          <IconButton size="small" onClick={onPrevWeek} disabled={!canGoPrev} aria-label="Previous week">
            <ChevronLeftIcon fontSize="small" />
          </IconButton>
          <Typography sx={{ fontSize: "0.74rem", fontWeight: 700, minWidth: 140, textAlign: "center" }}>{weekLabel}</Typography>
          <IconButton size="small" onClick={onNextWeek} aria-label="Next week">
            <ChevronRightIcon fontSize="small" />
          </IconButton>
        </Stack>
        {hideEmployerTabs ? null : (
          <Segmented
            value={employerTab}
            onChange={onEmployerTab}
            label="Employer"
            options={employerTabs.map((tab) => ({ value: tab.key, label: `${tab.label} ${tab.count}` }))}
          />
        )}
        <Box sx={{ flex: 1 }} />
        {copyItem ? (
          <Button size="small" variant="outlined" startIcon={<ContentCopyOutlinedIcon />} disabled={copyItem.disabled} onClick={() => copyItem.onClick?.()} sx={{ fontWeight: 700, py: 0.2, borderRadius: 999, whiteSpace: "nowrap", textTransform: "none" }}>
            Copy Week
          </Button>
        ) : null}
        {canEdit ? (
          <Button size="small" variant="contained" onClick={onAssign} sx={{ fontWeight: 800, py: 0.2, borderRadius: 999, whiteSpace: "nowrap", textTransform: "none", bgcolor: "#1d4ed8" }}>
            {t("weeklySchedule.assignBreaksTasks")}
          </Button>
        ) : null}
        {canEdit && addableEmployees.length ? (
          <Button size="small" variant="outlined" startIcon={<PersonAddAlt1OutlinedIcon />} onClick={(event) => onAddEmployee?.(event.currentTarget)} sx={{ fontWeight: 700, py: 0.2, borderRadius: 999, whiteSpace: "nowrap", textTransform: "none" }}>
            {t("weeklySchedule.addEmployee")}
          </Button>
        ) : null}
        <Button size="small" variant="text" aria-label="More schedule actions" onClick={onOpenMenu} endIcon={<MoreHorizIcon />} sx={{ fontWeight: 700, textTransform: "none", color: "#334155" }}>
          More
        </Button>
        <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={onCloseMenu}>
          {menuItems.map((item) => (
            <MenuItem
              key={item.id}
              disabled={item.disabled}
              component={item.to ? RouterLink : "li"}
              to={item.to}
              onClick={() => {
                onCloseMenu?.();
                item.onClick?.();
              }}
            >
              {item.label}
            </MenuItem>
          ))}
        </Menu>
        </Box>
      </Box>

      <Box sx={{ flexShrink: 0, px: 1.25, pt: 0.75, display: "flex", flexDirection: "column", gap: 0.7 }}>
        {children}
        <Box data-ops-kpis sx={{ display: "flex", gap: 0.7 }}>
          <KpiCard tone="blue" icon={<GroupsOutlinedIcon sx={{ fontSize: 16 }} />} label="Employees" value={summary.employeesScheduled ?? 0} hint="Scheduled (Week)" onClick={() => openDrill(PANEL.SUMMARY, "Employees scheduled · Entire week")} />
          {hideLaborHours ? null : <KpiCard tone="blue" icon={<AccessTimeOutlinedIcon sx={{ fontSize: 16 }} />} label="Gross Hours" value={`${hourText(summary.grossHours)} h`} hint="Planned (Week)" onClick={() => openDrill(PANEL.SUMMARY, "Gross planned hours · Entire week")} />}
          {hideLaborHours ? null : <KpiCard tone="green" icon={<AccessTimeOutlinedIcon sx={{ fontSize: 16 }} />} label="Net Hours" value={`${hourText(summary.totalHours)} h`} hint="Planned (Week)" onClick={() => openDrill(PANEL.SUMMARY, "Net planned hours · Entire week")} />}
          {showBreaks && !hideLaborHours ? <KpiCard tone="orange" icon={<CoffeeOutlinedIcon sx={{ fontSize: 16 }} />} label="Breaks" value={`${hourText(summary.breakHours)} h`} hint={`${hourText(summary.timedBreakHours)}h timed · ${untimedCount} untimed`} onClick={() => openDrill(PANEL.BREAKS, "Planned breaks · Entire week", LENS.BREAKS)} /> : null}
          <KpiCard tone="purple" icon={<AssignmentOutlinedIcon sx={{ fontSize: 16 }} />} label="Tasks (Groups)" value={rollup.byGroup.total || 0} hint={`${rollup.byGroup.inProgress} in progress`} onClick={() => openDrill(PANEL.TASKS, "Task groups · Entire week", LENS.TASKS)} />
          <KpiCard tone="green" icon={<CheckCircleOutlineIcon sx={{ fontSize: 16 }} />} label="Completed" value={`${finishedGroups}/${rollup.byGroup.total || 0}`} hint={`${rollup.byGroup.awaiting} awaiting verification`} onClick={() => openDrill(PANEL.TASKS, "Completed groups · Entire week", LENS.TASKS)} />
          <KpiCard tone={warningDays.length ? "red" : "green"} icon={<WarningAmberOutlinedIcon sx={{ fontSize: 16 }} />} label="Coverage" value={warningDays.length} hint={warningDays.length ? `Breaks > 3 at once (${warningDays.map((day) => DAY_LABELS[day]).join(", ")})` : "No overlap above 3"} onClick={() => openDrill(PANEL.BREAKS, "Coverage warnings · Entire week", LENS.BREAKS)} />
        </Box>

        <Box>
          <Typography sx={{ fontSize: "0.62rem", fontWeight: 800, letterSpacing: "0.04em", color: "#64748b", mb: 0.4 }}>ROLE COVERAGE · WEEKLY HOURS</Typography>
          <Box data-ops-role-cards sx={{ display: "flex", gap: 0.6, overflowX: "auto" }}>
            {roleCards.map((row) => {
              const style = roleStyle(row.role);
              const selected = highlightRole === row.role;
              return (
                <Box
                  key={row.role}
                  data-role-card={row.role}
                  data-role-selected={selected ? "yes" : "no"}
                  onClick={() => toggleRole(row.role)}
                  onMouseEnter={(event) => setRoleTip({ anchor: event.currentTarget, role: row.role, label: row.label })}
                  onMouseLeave={() => setRoleTip(null)}
                  sx={{
                    flex: "0 0 auto",
                    minWidth: 132,
                    display: "flex",
                    alignItems: "center",
                    gap: 0.7,
                    px: 0.8,
                    py: 0.55,
                    borderRadius: 2,
                    cursor: "pointer",
                    bgcolor: selected ? style.bg : "#fff",
                    border: selected ? `1.5px solid ${style.accent}` : "1px solid #e6ebf2",
                    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
                  }}
                >
                  <Box sx={{ width: 26, height: 26, borderRadius: 1, bgcolor: style.accent, color: "#fff", display: "grid", placeItems: "center", fontSize: "0.68rem", fontWeight: 800 }}>
                    {(row.label || "?").slice(0, 1)}
                  </Box>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: "#0f172a" }} noWrap>{row.label}</Typography>
                    <Typography sx={{ fontSize: "0.58rem", color: "#64748b" }} noWrap>
                      {`${row.employees} ${row.employees === 1 ? "person" : "people"}${hideLaborHours ? "" : ` · ${hourText(row.hours)}h`}`}
                    </Typography>
                  </Box>
                </Box>
              );
            })}
          </Box>
          {!hideLaborHours && roleHourDisplay.sourceAgrees && roleHourDisplay.displayGap ? (
            <Typography sx={{ mt: 0.35, fontSize: "0.55rem", color: "#64748b" }} title="Each role card is rounded half away from zero to 0.1h on its own. The week net is that same full-precision total rounded once. No role is changed to absorb the difference.">
              {`Role hours equal the week net before rounding (${exactHourText(roleHourDisplay.exactSum)}). Each card is rounded to 0.1h on its own, so the cards read ${hourText(roleHourDisplay.shownSum)}h beside the ${hourText(roleHourDisplay.weekShown)}h week net.`}
            </Typography>
          ) : null}
        </Box>

        <Box data-ops-controls sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>
          <Segmented
            value={lens}
            onChange={onLens}
            label="Roster"
            options={[
              { value: LENS.EMPLOYEES, label: t("weeklySchedule.ops.employees") },
              { value: LENS.BREAKS, label: t("weeklySchedule.ops.breaks") },
              { value: LENS.TASKS, label: t("weeklySchedule.ops.tasks") },
            ]}
          />
          <Typography sx={{ fontSize: "0.6rem", color: "#94a3b8", flex: 1, textAlign: "center" }} noWrap>
            {query ? `Showing ${roster.length} of ${employees.length}` : t("weeklySchedule.ops.noResize")}
          </Typography>
          <Segmented
            value={mode}
            onChange={onMode}
            label="Range"
            options={[
              { value: MODE.WEEK, label: t("weeklySchedule.ops.week") },
              { value: MODE.DAY, label: t("weeklySchedule.ops.day") },
            ]}
          />
        </Box>
      </Box>

      <Box sx={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(250px, 320px)", gap: 0.75, px: 1.25, py: 0.6 }}>
        <Box data-ops-grid sx={{ minWidth: 0, minHeight: 0, overflow: "auto", border: "1px solid #e6ebf2", borderRadius: 2, bgcolor: "#fff", boxShadow: "0 1px 2px rgba(15,23,42,0.04)" }}>
          {mode === MODE.DAY ? (
            <DayBoard {...boardProps} day={focusDay} windowStart={windowStart} span={span} hours={timeline.hours} dayBreaks={dayBreaks} />
          ) : (
            <WeekBoard {...boardProps} />
          )}
        </Box>
        <SidePanel
          t={t}
          panel={panel}
          onPanel={setPanel}
          drill={drill}
          dayLabel={dayLabel}
          weekLabel={weekLabel}
          onMode={onMode}
          warningDays={warningDays}
          untimedCount={untimedCount}
          finishedGroups={finishedGroups}
          summary={summary}
          onShift={onShift}
          dayGross={dayGross}
          dayNet={dayNet}
          hideLaborHours={hideLaborHours}
          showBreaks={showBreaks}
          highlightRole={highlightRole}
          selectedUserId={selectedUserId}
          dayRoles={dayRoles}
          dayBreaks={dayBreaks}
          breaksByDay={breaksByDay}
          dayColumns={dayColumns}
          rollup={rollup}
          dayRollup={dayRollup}
          employees={employees}
          employeesById={employeesById}
          shiftsFor={shiftsFor}
          focusDay={focusDay}
          dashboardLoaded={Boolean(dashboard)}
          timeline={timeline}
          roleHourDisplay={roleHourDisplay}
          onEditEntry={onEditEntry}
          onEditResponsibility={onEditResponsibility}
          onClearUser={() => setSelectedUserId(null)}
        />
      </Box>

      <Box
        data-ops-timeline
        sx={{
          flexShrink: 0,
          mx: 1,
          mb: 0.5,
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
          borderRadius: 1.5,
          bgcolor: "#fff",
          maxHeight: coverageOpen ? 210 : 32,
          overflow: "auto",
        }}
      >
        <Button
          data-ops-coverage-toggle
          size="small"
          onClick={() => setCoverageOpen((open) => !open)}
          endIcon={coverageOpen ? <ExpandMoreIcon /> : <ExpandLessIcon />}
          sx={{ fontSize: "0.68rem", fontWeight: 800, py: 0.15, minHeight: 0, color: "text.primary" }}
        >
          {`Role Coverage Timeline — ${dayLabel}${weekStart ? `, ${dayStamp(weekStart, focusDay)}` : ""}`}
        </Button>
        {coverageOpen && timeline.roles.length && timeline.hours.length ? (
          <Box sx={{ px: 1, pb: 0.7 }}>
            <Box sx={{ display: "flex", gap: 1.2, px: 0.2, pb: 0.35 }}>
              <Typography sx={{ fontSize: "0.55rem", color: "#64748b" }}>Color depth is people available after timed breaks.</Typography>
              <Typography sx={{ fontSize: "0.55rem", color: "#9a3412" }}>Striped band = on a timed break. Scheduled hours stay the same.</Typography>
            </Box>
            <Box sx={{ display: "grid", gridTemplateColumns: "118px minmax(0, 1fr) 92px", gap: 0.55, alignItems: "center" }}>
              <Box />
              <Box sx={{ display: "grid", gridTemplateColumns: `repeat(${timeline.hours.length}, 1fr)` }}>
                {timeline.hours.map((hour) => (
                  <Typography key={hour.hour} sx={{ fontSize: "0.55rem", fontWeight: 700, color: "#64748b", textAlign: "center" }}>{hour.label}</Typography>
                ))}
              </Box>
              <Typography sx={{ fontSize: "0.55rem", fontWeight: 800, textAlign: "right", color: "#64748b" }}>Gross / Net</Typography>
              {timeline.roles.map((row) => {
                const style = roleStyle(row.role);
                const dim = highlightRole && highlightRole !== row.role;
                return (
                  <Box key={row.role} sx={{ display: "contents", opacity: dim ? 0.35 : 1 }}>
                    <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, color: style.accent }} noWrap>{`${row.label} (${row.people})`}</Typography>
                    <Box sx={{ display: "flex", height: 20, borderRadius: 1, overflow: "hidden", bgcolor: "#f1f5f9" }}>
                      {row.slices.map((slice, index) => {
                        const active = slice.scheduledCount > 0 || slice.hours > 0.001;
                        const strength = active ? 0.2 + (0.8 * slice.availableCount) / row.peak : 0;
                        return (
                          <Box
                            key={`${row.role}-${index}`}
                            data-coverage-slice={`${row.role}-${index}`}
                            onMouseEnter={(event) => {
                              if (!active && slice.breakCount <= 0) return;
                              showCoverageTip({ anchor: event.currentTarget, role: row, slice, label: timeline.hours[index]?.label || "" });
                            }}
                            onMouseLeave={hideCoverageTip}
                            sx={{ flex: 1, position: "relative", cursor: active ? "default" : "auto" }}
                          >
                            <Box sx={{ position: "absolute", inset: 0, bgcolor: active ? style.accent : "transparent", opacity: strength }} />
                            {slice.breakHours > 0.001 ? (
                              <Box sx={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 5, backgroundImage: "repeating-linear-gradient(135deg, #9a3412 0 2px, #fff7ed 2px 4px)" }} />
                            ) : null}
                          </Box>
                        );
                      })}
                    </Box>
                    <Typography sx={{ fontSize: "0.6rem", fontWeight: 700, textAlign: "right" }}>
                      {hideLaborHours ? row.people : `${hourText(row.gross)} / ${hourText(row.net)}`}
                    </Typography>
                  </Box>
                );
              })}
            </Box>
          </Box>
        ) : null}
      </Box>

      <Popper open={Boolean(roleTip?.anchor)} anchorEl={roleTip?.anchor} placement="bottom-start" sx={{ zIndex: 30 }}>
        <Box sx={{ maxWidth: 240, p: 0.8, borderRadius: 1.5, bgcolor: "#fff", border: "1px solid #e6ebf2", boxShadow: "0 8px 24px rgba(15,23,42,0.12)" }}>
          <Typography sx={{ fontSize: "0.68rem", fontWeight: 800 }}>{roleTip?.label} · weekly</Typography>
          <Typography sx={{ fontSize: "0.6rem", color: "#64748b" }}>
            {employees.filter((employee) => entries.some((entry) => Number(entry.user_id) === Number(employee.user_id) && entryHasRole(entry, roleTip?.role))).map((employee) => employee.display_name).join(", ") || "No assignments"}
          </Typography>
        </Box>
      </Popper>
      <CoverageTip tip={coverageTip} hideLabor={hideLaborHours} onHold={() => window.clearTimeout(coverageTimer.current)} onClose={hideCoverageTip} />
      <HoverCard
        anchor={hover?.anchor}
        entry={hover?.entry}
        tasks={hover?.tasks || []}
        employeeName={employeesById[hover?.entry?.user_id]?.display_name || "Employee"}
        dayLabel={`${DAY_LABELS[hover?.entry?.day_of_week] || ""}${weekStart ? `, ${dayStamp(weekStart, hover?.entry?.day_of_week)}` : ""}`}
        showBreaks={showBreaks}
        hideLabor={hideLaborHours}
        onClose={() => setHover(null)}
        onOpen={() => onEditEntry?.(hover?.entry)}
      />
    </Box>
  );
}

function KpiCard({ label, value, hint, onClick, icon, tone = "blue" }) {
  const tones = {
    blue: { bg: "#eef4ff", fg: "#1d4ed8" },
    green: { bg: "#e9f9ef", fg: "#047857" },
    orange: { bg: "#fff6eb", fg: "#c2410c" },
    purple: { bg: "#f5f0ff", fg: "#6d28d9" },
    red: { bg: "#fff1f2", fg: "#be123c" },
  };
  const paint = tones[tone] || tones.blue;
  return (
    <Box
      data-ops-kpi={label}
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        flex: "1 1 0",
        minWidth: 0,
        display: "flex",
        alignItems: "center",
        gap: 0.8,
        px: 0.9,
        py: 0.7,
        borderRadius: 2,
        bgcolor: paint.bg,
        border: "1px solid rgba(15,23,42,0.04)",
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
      }}
    >
      <Box sx={{ width: 28, height: 28, borderRadius: 1.2, bgcolor: "#fff", color: paint.fg, display: "grid", placeItems: "center", flexShrink: 0 }}>
        {icon}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontSize: "1rem", fontWeight: 800, lineHeight: 1.05, color: "#0f172a" }}>{value}</Typography>
        <Typography sx={{ fontSize: "0.62rem", fontWeight: 800, color: "#1e293b" }} noWrap>{label}</Typography>
        {hint ? <Typography sx={{ fontSize: "0.55rem", color: "#64748b", lineHeight: 1.2 }} noWrap>{hint}</Typography> : null}
      </Box>
    </Box>
  );
}

function SidePanel(props) {
  const {
    t, panel, onPanel, drill, dayLabel, weekLabel, onMode, warningDays = [], untimedCount = 0, finishedGroups = 0, summary, onShift, dayGross, dayNet, hideLaborHours, showBreaks,
    highlightRole, selectedUserId, dayRoles, dayBreaks, breaksByDay, dayColumns, rollup, dayRollup,
    employees, employeesById, shiftsFor, focusDay, dashboardLoaded, onEditEntry, onEditResponsibility, onClearUser,
    timeline, roleHourDisplay,
  } = props;
  const person = selectedUserId != null ? employeesById[selectedUserId] || employees.find((employee) => Number(employee.user_id) === Number(selectedUserId)) : null;
  const roleRow = dayRoles.find((row) => row.role === highlightRole);
  const visibleGroups = (dayRollup.groups || []).filter((group) => {
    if (highlightRole && group.role !== highlightRole) return false;
    if (selectedUserId != null && !group.members.some((member) => Number(member.userId) === Number(selectedUserId))) return false;
    return true;
  });
  const timed = dayBreaks.timed.filter((item) => selectedUserId == null || Number(item.userId) === Number(selectedUserId));
  const untimed = dayBreaks.untimed.filter((item) => selectedUserId == null || Number(item.userId) === Number(selectedUserId));
  return (
    <Box data-ops-side data-ops-panel={panel} sx={{ minHeight: 0, overflow: "auto", border: "1px solid #e6ebf2", borderRadius: 2, bgcolor: "#fff", p: 1, display: "flex", flexDirection: "column", gap: 0.8, boxShadow: "0 1px 2px rgba(15,23,42,0.04)" }}>
      <Segmented
        value={panel}
        onChange={onPanel}
        label="Detail"
        options={[
          { value: PANEL.SUMMARY, label: t("weeklySchedule.ops.summary") },
          { value: PANEL.ROLES, label: t("weeklySchedule.ops.roles") },
          { value: PANEL.BREAKS, label: t("weeklySchedule.ops.breaks") },
          { value: PANEL.TASKS, label: t("weeklySchedule.ops.tasks") },
        ]}
      />
      <Typography sx={{ fontSize: "0.62rem", color: "text.secondary" }}>
        {drill || `${dayLabel} · ${t("weeklySchedule.ops.scopeDay")}`}
      </Typography>
      {highlightRole ? <Typography sx={{ fontSize: "0.62rem", fontWeight: 700 }}>{t("weeklySchedule.ops.highlightNote")}</Typography> : null}
      {person ? (
        <Button size="small" onClick={onClearUser} sx={{ alignSelf: "flex-start", py: 0, fontSize: "0.64rem" }}>
          {person.display_name || "Employee"}
        </Button>
      ) : null}
      {panel === PANEL.SUMMARY ? (
        <Stack spacing={0.8}>
          <Box sx={{ p: 0.8, borderRadius: 1.5, bgcolor: "#f8fafc", border: "1px solid #eef2f6" }}>
            <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, mb: 0.5 }}>{`Week at a Glance${weekLabel ? ` (${weekLabel})` : ""}`}</Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0.5 }}>
              <Glance label="Employees" value={summary.employeesScheduled ?? 0} />
              {hideLaborHours ? null : <Glance label="Gross" value={`${hourText(summary.grossHours)}h`} />}
              {hideLaborHours ? null : <Glance label="Net" value={`${hourText(summary.totalHours)}h`} />}
              {showBreaks && !hideLaborHours ? <Glance label="Breaks" value={`${hourText(summary.breakHours)}h`} /> : null}
              <Glance label="Tasks" value={rollup.byGroup.total || 0} />
              <Glance label="Completed" value={`${finishedGroups}/${rollup.byGroup.total || 0}`} />
            </Box>
          </Box>
          <Box>
            <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, mb: 0.4 }}>Key Insights</Typography>
            {warningDays.length ? <Insight tone="red" text={`${warningDays.map((day) => DAY_LABELS[day]).join(", ")}: more than 3 breaks at once`} /> : <Insight tone="green" text="No break overlap above 3" />}
            {untimedCount ? <Insight tone="orange" text={`${untimedCount} untimed breaks this week`} /> : null}
            {rollup.byGroup.awaiting ? <Insight tone="blue" text={`${rollup.byGroup.awaiting} task group${rollup.byGroup.awaiting === 1 ? "" : "s"} awaiting verification`} /> : <Insight tone="green" text="No tasks awaiting verification" />}
            {Number(summary.unallocatedBreakHours) > 0.001 ? <Insight tone="orange" text={`${hourText(summary.unallocatedBreakHours)}h of untimed break is not allocated to a role`} /> : null}
            {!hideLaborHours && roleHourDisplay?.sourceAgrees && roleHourDisplay.displayGap ? (
              <Insight tone="blue" text={`Role cards round each role to 0.1h (${hourText(roleHourDisplay.shownSum)}h). The week net rounds the same total once (${hourText(roleHourDisplay.weekShown)}h).`} />
            ) : null}
          </Box>
          <Box sx={{ p: 0.8, borderRadius: 1.5, border: "1px solid #e6ebf2" }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Typography sx={{ fontSize: "0.68rem", fontWeight: 800 }}>{`Today (${dayLabel})`}</Typography>
              <Button size="small" onClick={() => onMode?.(MODE.DAY)} sx={{ minWidth: 0, py: 0, fontSize: "0.62rem", textTransform: "none" }}>View day</Button>
            </Box>
            <Line label="On shift" value={String(onShift)} />
            {hideLaborHours ? null : <Line label="Gross" value={`${hourText(dayGross)}h`} />}
            {hideLaborHours ? null : <Line label="Net" value={`${hourText(dayNet)}h`} />}
            {showBreaks ? <Line label="Peak breaks" value={String(dayBreaks.maxOverlap)} warn={dayBreaks.maxOverlap > BREAK_OVERLAP_CAP} /> : null}
            <Line label="Task groups" value={String((dayRollup.groups || []).length)} />
          </Box>
          {drill ? <Typography sx={{ fontSize: "0.58rem", color: "#64748b" }}>{drill}</Typography> : null}
        </Stack>
      ) : null}
      {panel === PANEL.ROLES ? (
        <RolePanel
          rows={roleRow ? [roleRow] : dayRoles}
          timeline={timeline}
          dayLabel={dayLabel}
          employees={employees}
          shiftsFor={shiftsFor}
          focusDay={focusDay}
          hideLaborHours={hideLaborHours}
          t={t}
        />
      ) : null}
      {panel === PANEL.BREAKS ? (
        <BreakPanel
          dayColumns={dayColumns}
          breaksByDay={breaksByDay}
          dayBreaks={dayBreaks}
          dayLabel={dayLabel}
          timed={timed}
          untimed={untimed}
          employeesById={employeesById}
          onEditEntry={onEditEntry}
          t={t}
        />
      ) : null}
      {panel === PANEL.TASKS ? (
        <TaskPanel
          t={t}
          rollup={rollup}
          visibleGroups={visibleGroups}
          dashboardLoaded={dashboardLoaded}
          onEditResponsibility={onEditResponsibility}
        />
      ) : null}
    </Box>
  );
}

const STATUS_TONE = {
  notStarted: { bg: "#f1f5f9", fg: "#475569" },
  inProgress: { bg: "#fff7ed", fg: "#c2410c" },
  awaiting: { bg: "#eff6ff", fg: "#1d4ed8" },
  verified: { bg: "#ecfdf5", fg: "#047857" },
  completed: { bg: "#ecfdf5", fg: "#047857" },
  rejected: { bg: "#fff1f2", fg: "#be123c" },
};

function RolePanel({ rows, timeline, dayLabel, employees, shiftsFor, focusDay, hideLaborHours, t }) {
  const maxHours = Math.max(1, ...rows.map((row) => Number(row.hours || 0)));
  return (
    <Stack spacing={0.55}>
      {rows.map((row) => {
        const style = roleStyle(row.role);
        const dayRow = (timeline?.roles || []).find((item) => item.role === row.role);
        const names = employees.filter((employee) => shiftsFor(employee.user_id, focusDay).some((entry) => entryHasRole(entry, row.role)));
        return (
          <Box key={row.role} sx={{ p: 0.65, borderRadius: 1.5, border: "1px solid #e6ebf2", borderLeft: `4px solid ${style.accent}`, bgcolor: "#fff" }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
              <Typography sx={{ fontSize: "0.7rem", fontWeight: 800, color: style.accent }} noWrap>{row.label}</Typography>
              <Typography sx={{ fontSize: "0.62rem", fontWeight: 700, color: "#334155" }} noWrap>
                {`${row.employees} ${row.employees === 1 ? "person" : "people"}${hideLaborHours ? "" : ` · ${hourText(row.hours)}h`}`}
              </Typography>
            </Box>
            {hideLaborHours ? null : (
              <Box sx={{ mt: 0.4, height: 6, borderRadius: 1, bgcolor: "#f1f5f9", overflow: "hidden" }}>
                <Box sx={{ width: `${Math.min(100, (Number(row.hours || 0) / maxHours) * 100)}%`, height: "100%", bgcolor: style.accent }} />
              </Box>
            )}
            <Typography sx={{ mt: 0.45, fontSize: "0.55rem", fontWeight: 800, color: "#64748b" }}>{`${dayLabel} coverage`}</Typography>
            <Box sx={{ mt: 0.25, display: "flex", height: 8, borderRadius: 0.6, overflow: "hidden", bgcolor: "#f8fafc" }}>
              {(dayRow?.slices || []).map((slice, index) => (
                <Box key={index} title={slice.scheduledCount ? `${slice.availableCount} available of ${slice.scheduledCount} scheduled` : ""} sx={{ flex: 1, bgcolor: slice.scheduledCount ? style.accent : "transparent", opacity: slice.scheduledCount ? 0.2 + (0.8 * slice.availableCount) / (dayRow.peak || 1) : 1 }} />
              ))}
            </Box>
            <Box sx={{ mt: 0.4, display: "flex", flexWrap: "wrap", gap: 0.3 }}>
              {names.length ? names.map((employee) => (
                <Box key={employee.user_id} sx={{ px: 0.45, py: 0.05, borderRadius: 0.7, bgcolor: style.bg, color: style.accent, fontSize: "0.55rem", fontWeight: 800 }}>
                  {employee.display_name}
                </Box>
              )) : <Typography sx={{ fontSize: "0.58rem", color: "#94a3b8" }}>{`No ${row.label} assignment ${dayLabel}`}</Typography>}
            </Box>
            {Number(row.unallocatedBreakHours) > 0.001 ? (
              <Typography sx={{ mt: 0.3, fontSize: "0.58rem", fontWeight: 700, color: "#9a3412" }}>Untimed break not allocated on a multi-role shift</Typography>
            ) : null}
          </Box>
        );
      })}
      {rows.length > 1 ? <Typography sx={{ fontSize: "0.55rem", color: "#94a3b8" }}>{t("weeklySchedule.ops.weeklyHours")} stay on the full week. The strip is the selected day.</Typography> : null}
    </Stack>
  );
}

function BreakPanel({ dayColumns, breaksByDay, dayBreaks, dayLabel, timed, untimed, employeesById, onEditEntry, t }) {
  return (
    <Stack spacing={0.55}>
      <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0.45 }}>
        <Glance label={`${dayLabel} peak`} value={`${dayBreaks.maxOverlap} at once`} />
        <Glance label={`${dayLabel} untimed`} value={String(untimed.length)} />
      </Box>
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 0.3 }}>
        {dayColumns.map((day) => {
          const detail = breaksByDay[day] || { maxOverlap: 0, untimed: [] };
          const hot = detail.maxOverlap > BREAK_OVERLAP_CAP;
          return (
            <Box key={day} sx={{ px: 0.2, py: 0.35, borderRadius: 1, textAlign: "center", bgcolor: hot ? "#fff1f2" : "#f8fafc", border: `1px solid ${hot ? "#fecdd3" : "#eef2f6"}` }}>
              <Typography sx={{ fontSize: "0.5rem", fontWeight: 800, color: hot ? "#be123c" : "#64748b" }}>{DAY_LABELS[day]}</Typography>
              <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, color: hot ? "#be123c" : "#0f172a" }}>{detail.maxOverlap}</Typography>
            </Box>
          );
        })}
      </Box>
      {dayBreaks.hot.map((window, index) => {
        const names = (window.userIds || []).map((id) => employeesById[id]?.display_name || employeesById[String(id)]?.display_name || `User #${id}`);
        return (
          <Box key={`hot-${index}`} data-break-hot sx={{ p: 0.6, borderRadius: 1.2, bgcolor: "#fff1f2", border: "1px solid #fecdd3" }}>
            <Typography sx={{ fontSize: "0.64rem", fontWeight: 800, color: "#9a3412" }}>
              {`${minutesLabel(window.start)}–${minutesLabel(window.end)} · ${window.count} people`}
            </Typography>
            <Typography sx={{ fontSize: "0.58rem", color: "#9a3412" }}>{names.join(", ") || "Timed overlap above 3"}</Typography>
          </Box>
        );
      })}
      <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: "#64748b" }}>{`${dayLabel} timed`}</Typography>
      {timed.length ? timed.map((item) => (
        <Box key={item.key} onClick={() => onEditEntry?.(item.entry)} sx={{ px: 0.6, py: 0.35, borderRadius: 1, bgcolor: "#fff7ed", border: "1px solid #ffedd5", cursor: "pointer" }}>
          <Typography sx={{ fontSize: "0.64rem", fontWeight: 700 }}>{`${item.name} · ${item.startLabel}–${item.endLabel}`}</Typography>
        </Box>
      )) : <Typography sx={{ fontSize: "0.58rem", color: "#94a3b8" }}>No timed breaks</Typography>}
      <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: "#64748b" }}>{`${dayLabel} ${t("weeklySchedule.ops.untimed")}`}</Typography>
      {untimed.length ? untimed.map((item) => (
        <Box key={item.key} onClick={() => onEditEntry?.(item.entry)} sx={{ px: 0.6, py: 0.35, borderRadius: 1, bgcolor: "#f8fafc", border: "1px dashed #cbd5e1", cursor: "pointer" }}>
          <Typography sx={{ fontSize: "0.64rem" }}>{`${item.name} · ${item.minutes}m off the clock`}</Typography>
        </Box>
      )) : <Typography sx={{ fontSize: "0.58rem", color: "#94a3b8" }}>No untimed breaks</Typography>}
    </Stack>
  );
}

function TaskPanel({ t, rollup, visibleGroups, dashboardLoaded, onEditResponsibility }) {
  const counts = [
    ["notStarted", rollup.byGroup.notStarted],
    ["inProgress", rollup.byGroup.inProgress],
    ["awaiting", rollup.byGroup.awaiting],
    ["verified", rollup.byGroup.verified],
    ["completed", rollup.byGroup.completed],
  ].filter(([, count]) => count);
  return (
    <Stack spacing={0.55}>
      <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0.4 }}>
        <Glance label={t("weeklySchedule.ops.groups")} value={rollup.byGroup.total || 0} />
        <Glance label={t("weeklySchedule.ops.people")} value={rollup.people.total || 0} />
      </Box>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.35 }}>
        {counts.map(([bucket, count]) => {
          const tone = STATUS_TONE[bucket];
          return (
            <Box key={bucket} sx={{ px: 0.55, py: 0.2, borderRadius: 1, bgcolor: tone.bg, color: tone.fg, fontSize: "0.58rem", fontWeight: 800 }}>
              {`${count} ${statusText(t, bucket)}`}
            </Box>
          );
        })}
        <Box sx={{ px: 0.55, py: 0.2, borderRadius: 1, bgcolor: "#f5f3ff", color: "#6d28d9", fontSize: "0.58rem", fontWeight: 800 }}>
          {`${rollup.byGroup.shared || 0} ${t("weeklySchedule.ops.shared")}`}
        </Box>
      </Box>
      {!dashboardLoaded ? <Typography sx={{ fontSize: "0.58rem", color: "#64748b" }}>Timers and the shared checklist load with the task dashboard for this day.</Typography> : null}
      {visibleGroups.map((group) => {
        const tone = STATUS_TONE[group.bucket] || STATUS_TONE.notStarted;
        const done = group.members.filter((member) => member.bucket === "verified" || member.bucket === "completed").length;
        return (
          <Box key={group.key} data-task-group={group.key} sx={{ p: 0.6, borderRadius: 1.5, border: "1px solid #e6ebf2", borderLeft: `4px solid ${tone.fg}` }}>
            <Box sx={{ display: "flex", justifyContent: "space-between", gap: 0.6 }}>
              <Typography sx={{ fontSize: "0.68rem", fontWeight: 800 }} noWrap>
                {group.shared ? `${t("weeklySchedule.ops.shared")} · ` : ""}{group.label}
              </Typography>
              <Box sx={{ px: 0.45, borderRadius: 0.7, bgcolor: tone.bg, color: tone.fg, fontSize: "0.55rem", fontWeight: 800, whiteSpace: "nowrap" }}>{statusText(t, group.bucket)}</Box>
            </Box>
            <Box sx={{ mt: 0.35, height: 5, borderRadius: 1, bgcolor: "#f1f5f9", overflow: "hidden" }}>
              <Box sx={{ width: `${group.members.length ? (done / group.members.length) * 100 : 0}%`, height: "100%", bgcolor: tone.fg }} />
            </Box>
            {checklistLine(group.checklist, group.checklistStatus) ? (
              <Typography sx={{ mt: 0.3, fontSize: "0.58rem" }}>{`${t("weeklySchedule.planner.checklist")} ${checklistLine(group.checklist, group.checklistStatus)}`}</Typography>
            ) : null}
            {group.members.map((member) => {
              const memberTone = STATUS_TONE[member.bucket] || STATUS_TONE.notStarted;
              return (
                <Box
                  key={member.responsibilityId}
                  onClick={() => onEditResponsibility?.({ id: member.responsibilityId, user_id: member.userId, user_ids: group.members.map((person) => person.userId), day_of_week: group.day, role: group.role, activity_status: member.status, assignment_group_id: group.groupId, execution_mode: group.shared ? "shared" : "individual" })}
                  sx={{ mt: 0.3, display: "flex", justifyContent: "space-between", gap: 0.5, cursor: "pointer" }}
                >
                  <Typography sx={{ fontSize: "0.62rem", fontWeight: 700 }} noWrap>{member.name}</Typography>
                  <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: memberTone.fg }} noWrap>
                    {`${statusText(t, member.bucket)}${member.duration != null ? ` · ${timerLabel(member.duration)}` : ""}`}
                  </Typography>
                </Box>
              );
            })}
          </Box>
        );
      })}
    </Stack>
  );
}

function Glance({ label, value }) {
  return (
    <Box sx={{ bgcolor: "#fff", borderRadius: 1, px: 0.55, py: 0.4, border: "1px solid #eef2f6" }}>
      <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: "#0f172a" }}>{value}</Typography>
      <Typography sx={{ fontSize: "0.5rem", color: "#64748b" }}>{label}</Typography>
    </Box>
  );
}

function Insight({ tone, text }) {
  const color = tone === "red" ? "#be123c" : tone === "orange" ? "#c2410c" : tone === "blue" ? "#1d4ed8" : "#047857";
  const bg = tone === "red" ? "#fff1f2" : tone === "orange" ? "#fff7ed" : tone === "blue" ? "#eff6ff" : "#ecfdf5";
  return <Typography sx={{ fontSize: "0.62rem", fontWeight: 700, color, bgcolor: bg, borderRadius: 1, px: 0.7, py: 0.4, mb: 0.4 }}>{text}</Typography>;
}

function Line({ label, value, hint, warn = false }) {
  return (
    <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
      <Typography sx={{ fontSize: "0.64rem", color: "text.secondary" }}>{label}</Typography>
      <Box sx={{ textAlign: "right" }}>
        <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: warn ? "#9a3412" : "text.primary" }}>{value}</Typography>
        {hint ? <Typography sx={{ fontSize: "0.58rem", color: "#9a3412" }}>{hint}</Typography> : null}
      </Box>
    </Box>
  );
}

function WeekBoard(props) {
  const { employees, dayColumns, focusDay, onFocusDay, lens, breaksByDay, t, weekStart, dayTotals, hideLaborHours } = props;
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: `168px repeat(${dayColumns.length}, minmax(108px, 1fr))`, minWidth: 168 + dayColumns.length * 108 }}>
      <Box sx={{ px: 0.8, py: 0.55, position: "sticky", left: 0, top: 0, zIndex: 3, bgcolor: "#f8fafc", borderBottom: "1px solid #e7edf2" }}>
        <Typography sx={{ fontSize: "0.62rem", fontWeight: 800, color: "#64748b" }}>Employee</Typography>
        <Typography sx={{ fontSize: "0.52rem", color: "#94a3b8" }}>Weekly gross / net</Typography>
      </Box>
      {dayColumns.map((day) => {
        const detail = breaksByDay[day] || { maxOverlap: 0, untimed: [] };
        const hot = detail.maxOverlap > BREAK_OVERLAP_CAP;
        return (
          <Box
            key={day}
            onClick={() => onFocusDay?.(day)}
            sx={{
              px: 0.6,
              py: 0.4,
              cursor: "pointer",
              position: "sticky",
              top: 0,
              zIndex: 2,
              bgcolor: Number(focusDay) === Number(day) ? "#e8f1ff" : "#f8fafc",
              borderLeft: "1px solid #eef2f6",
              borderBottom: "1px solid #e7edf2",
            }}
          >
            <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, color: "#0f172a" }}>{DAY_LABELS[day]}</Typography>
            <Typography sx={{ fontSize: "0.55rem", color: "#64748b" }}>{dayStamp(weekStart, day)}</Typography>
            {lens === LENS.BREAKS ? (
              <Typography data-break-day={day} sx={{ fontSize: "0.55rem", fontWeight: 800, color: hot ? "#be123c" : "#64748b" }}>
                {`${detail.maxOverlap} at once${hot ? " · above 3" : ""}`}
              </Typography>
            ) : null}
          </Box>
        );
      })}
      {employees.map((employee) => (
        <WeekRow key={employee.user_id} employee={employee} {...props} />
      ))}
      <Box sx={{ position: "sticky", bottom: 0, left: 0, zIndex: 3, px: 0.8, py: 0.45, bgcolor: "#f8fafc", borderTop: "1px solid #e2e8f0" }}>
        <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: "#475569" }}>Daily totals</Typography>
      </Box>
      {dayColumns.map((day) => (
        <Box key={`total-${day}`} sx={{ position: "sticky", bottom: 0, zIndex: 2, px: 0.6, py: 0.45, bgcolor: "#f8fafc", borderTop: "1px solid #e2e8f0", borderLeft: "1px solid #eef2f6" }}>
          <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: "#334155" }}>
            {hideLaborHours ? "" : `${hourText(dayTotals?.[day]?.gross)}h / ${hourText(dayTotals?.[day]?.net)}h`}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function WeekRow({ employee, dayColumns, shiftsFor, tasksFor, lens, showBreaks, hideLaborHours, canEdit, dropKey, setDropKey, dropOn, highlightRole, selectedUserId, onSelectUser, onEditEntry, onCreate, onEditResponsibility, onViewEmployee, onDragStart, onDragEnd, draggingId, onHover, onLeave, breaksByDay, groupsByDay, showRoleLabels, employeesById, hoursByUser }) {
  const name = employee.display_name || `User #${employee.user_id}`;
  const selected = Number(selectedUserId) === Number(employee.user_id);
  const pair = hoursByUser?.[employee.user_id] || { gross: employee.total_hours || 0, net: employee.total_hours || 0 };
  return (
    <>
      <Box
        onClick={() => onSelectUser?.(employee.user_id)}
        sx={{ px: 0.7, py: 0.4, position: "sticky", left: 0, zIndex: 1, bgcolor: selected ? "#e8f1ff" : "#fff", borderBottom: "1px solid #f1f5f9", cursor: "pointer", display: "flex", alignItems: "center", gap: 0.7 }}
      >
        <Box sx={{ width: 26, height: 26, borderRadius: "50%", bgcolor: AVATAR_COLORS[Number(employee.user_id) % AVATAR_COLORS.length], color: "#fff", display: "grid", placeItems: "center", fontSize: "0.58rem", fontWeight: 800, flexShrink: 0 }}>
          {initials(name)}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            sx={{ fontSize: "0.72rem", fontWeight: 800, color: "#0f172a" }}
            noWrap
            title="Double-click to open this employee's week"
            onDoubleClick={(event) => {
              event.stopPropagation();
              onViewEmployee?.(employee);
            }}
          >
            {name}
          </Typography>
          {hideLaborHours ? null : <Typography sx={{ fontSize: "0.55rem", color: "#64748b" }}>{`${hourText(pair.gross)}h / ${hourText(pair.net)}h`}</Typography>}
        </Box>
      </Box>
      {dayColumns.map((day) => {
        const shifts = shiftsFor(employee.user_id, day);
        const tasks = tasksFor(employee.user_id, day);
        const key = `${employee.user_id}:${day}`;
        return (
          <Box
            key={key}
            onDragOver={(event) => {
              event.preventDefault();
              setDropKey(key);
            }}
            onDragLeave={() => setDropKey("")}
            onDrop={(event) => dropOn(event, employee.user_id, day)}
            onClick={() => {
              if (!shifts.length && canEdit) onCreate?.(employee.user_id, day);
            }}
            sx={{
              minHeight: 36,
              px: 0.35,
              py: 0.3,
              borderLeft: "1px solid #f1f5f9",
              borderBottom: "1px solid #f1f5f9",
              bgcolor: dropKey === key ? "#e8f2fb" : "transparent",
            }}
          >
            {lens === LENS.TASKS ? (
              <TaskCell tasks={tasks} dayGroups={groupsByDay?.[day]} userId={employee.user_id} onEditResponsibility={onEditResponsibility} />
            ) : lens === LENS.BREAKS ? (
              <BreakCell dayDetail={breaksByDay[day]} userId={employee.user_id} shifts={shifts} onEditEntry={onEditEntry} showBreaks={showBreaks} />
            ) : shifts.map((entry) => (
              <ShiftChip
                key={entry.id}
                entry={entry}
                tasks={tasks}
                muted={highlightRole && !entryHasRole(entry, highlightRole)}
                dragging={Number(draggingId) === Number(entry.id)}
                showRoleLabels={showRoleLabels}
                showBreaks={showBreaks}
                onEdit={onEditEntry}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                onHover={onHover}
                onLeave={onLeave}
              />
            ))}
          </Box>
        );
      })}
    </>
  );
}

function shiftFill(segments) {
  if (!segments.length) return roleStyle("fold").bg;
  if (segments.length === 1) return roleStyle(segments[0].role).bg;
  const widths = segments.map((segment) => {
    const start = clockMinutes(segment.start);
    const end = clockMinutes(segment.end);
    return Math.max(1, (end ?? 0) - (start ?? 0));
  });
  const total = widths.reduce((sum, value) => sum + value, 0) || 1;
  let cursor = 0;
  const stops = segments.map((segment, index) => {
    const from = (cursor / total) * 100;
    cursor += widths[index];
    const to = (cursor / total) * 100;
    const paint = roleStyle(segment.role).bg;
    return `${paint} ${from}%, ${paint} ${to}%`;
  });
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

function ShiftChip({ entry, tasks, muted, dragging, showRoleLabels, showBreaks, onEdit, onDragStart, onDragEnd, onHover, onLeave }) {
  const segments = shiftRoleSegments(entry);
  const roles = segments.length ? segments.map((segment) => segment.role) : parseEntryRoles(entry).filter(Boolean);
  const style = roleStyle(roles[0] || "fold");
  const parts = entryBreakBreakdown(entry);
  const multi = roles.length > 1;
  return (
    <Box
      data-shift-chip
      data-entry-id={entry.id}
      data-role-muted={muted ? "yes" : "no"}
      data-multi-role={multi ? "yes" : "no"}
      draggable
      onDragStart={(event) => {
        event.stopPropagation();
        event.dataTransfer.setData("text/plain", String(entry.id));
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={(event) => {
        event.stopPropagation();
        onEdit?.(entry);
      }}
      onMouseEnter={(event) => onHover?.(event.currentTarget, entry, tasks)}
      onMouseLeave={onLeave}
      sx={{
        mb: 0.25,
        display: "flex",
        overflow: "hidden",
        borderRadius: 1.1,
        cursor: "pointer",
        opacity: muted ? 0.28 : dragging ? 0.55 : 1,
        bgcolor: shiftFill(segments.length ? segments : roles.map((role) => ({ role, start: entry.start_time, end: entry.end_time }))),
        border: `1px solid ${style.border}`,
        boxShadow: multi ? `inset 0 0 0 1px ${style.accent}` : "none",
      }}
    >
      <Box sx={{ width: 4, flexShrink: 0, display: "flex", flexDirection: "column" }}>
        {(roles.length ? roles : ["fold"]).map((role, index) => (
          <Box key={`${role}-${index}`} sx={{ flex: 1, bgcolor: roleStyle(role).accent }} />
        ))}
      </Box>
      <Box sx={{ minWidth: 0, px: 0.45, py: 0.22 }}>
        <Typography sx={{ fontSize: "0.6rem", fontWeight: 800, lineHeight: 1.15, color: "#0f172a" }}>
          {`${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}`}
        </Typography>
        <Stack direction="row" spacing={0.3} sx={{ mt: 0.15, alignItems: "center", flexWrap: "wrap" }}>
          {showRoleLabels ? roles.map((role) => {
            const paint = roleStyle(role);
            return (
              <Box key={role} sx={{ px: 0.4, py: 0, borderRadius: 0.6, bgcolor: "#fff", color: paint.accent, border: `1px solid ${paint.border}`, fontSize: "0.52rem", fontWeight: 800, lineHeight: 1.35 }}>
                {roleCompactLabel(role)}
              </Box>
            );
          }) : null}
          {showBreaks && parts.breakMinutes > 0 ? <CoffeeOutlinedIcon sx={{ fontSize: 11, color: "#c2410c" }} titleAccess={parts.unscheduledBreakMinutes > 0 && parts.timedBreakMinutes <= 0 ? `${parts.unscheduledBreakMinutes}m untimed` : `${parts.timedBreakMinutes}m timed`} /> : null}
          {tasks?.length ? <CheckCircleOutlineIcon sx={{ fontSize: 11, color: "#0f766e" }} /> : null}
        </Stack>
      </Box>
    </Box>
  );
}

function BreakCell({ dayDetail, userId, shifts, onEditEntry, showBreaks }) {
  if (!showBreaks) return null;
  const timed = (dayDetail?.timed || []).filter((item) => Number(item.userId) === Number(userId));
  const untimed = (dayDetail?.untimed || []).filter((item) => Number(item.userId) === Number(userId));
  if (!timed.length && !untimed.length) return null;
  const open = shifts[0] || timed[0]?.entry || untimed[0]?.entry;
  return (
    <Box onClick={(event) => { event.stopPropagation(); onEditEntry?.(open); }} sx={{ cursor: "pointer" }}>
      {timed.map((item) => (
        <Typography key={item.key} sx={{ fontSize: "0.6rem", fontWeight: 700, color: (dayDetail?.maxOverlap || 0) > BREAK_OVERLAP_CAP ? "#9a3412" : "text.primary" }}>
          {`${item.startLabel}–${item.endLabel}`}
        </Typography>
      ))}
      {untimed.map((item) => (
        <Typography key={item.key} sx={{ fontSize: "0.58rem", color: "text.secondary" }}>{`${item.minutes}m untimed`}</Typography>
      ))}
    </Box>
  );
}

function TaskCell({ tasks, dayGroups, userId, employeesById, onEditResponsibility }) {
  const groups = (dayGroups || taskStatusRollup(tasks, employeesById).groups).filter((group) => (
    userId == null || group.members.some((member) => Number(member.userId) === Number(userId))
  ));
  if (!groups.length) return null;
  return groups.map((group) => (
    <Box
      key={group.key}
      data-task-shared={group.shared ? "yes" : "no"}
      onClick={(event) => {
        event.stopPropagation();
        const member = group.members[0];
        const source = (tasks || []).find((item) => Number(item.id) === Number(member?.responsibilityId)) || {};
        onEditResponsibility?.({
          ...source,
          id: member?.responsibilityId,
          user_id: member?.userId,
          user_ids: group.members.map((person) => person.userId),
          day_of_week: group.day,
          role: group.role,
          activity_status: member?.status,
          assignment_group_id: group.groupId,
          execution_mode: group.shared ? "shared" : source.execution_mode || "individual",
        });
      }}
      sx={{ mb: 0.3, px: 0.4, py: 0.2, borderRadius: 0.8, bgcolor: "#f8fafc", border: "1px solid #e2e8f0", cursor: "pointer" }}
    >
      <Typography sx={{ fontSize: "0.6rem", fontWeight: 800 }} noWrap>
        {group.shared ? "Shared · " : ""}{group.label}
      </Typography>
      <Typography sx={{ fontSize: "0.56rem", color: "text.secondary" }} noWrap>
        {group.members.map((member) => `${member.name.split(" ")[0]} ${member.bucket === "awaiting" ? "awaiting" : member.bucket === "verified" ? "verified" : member.bucket === "inProgress" ? "in progress" : member.bucket === "notStarted" ? "not started" : member.bucket === "completed" ? "completed" : "rejected"}`).join(" · ")}
      </Typography>
    </Box>
  ));
}

function DayBoard({ employees, day, dayColumns, onFocusDay, shiftsFor, tasksFor, windowStart, span, hours, lens, showBreaks, canEdit, dropKey, setDropKey, dropOn, onEditEntry, onCreate, onEditResponsibility, onDragStart, onDragEnd, draggingId, highlightRole, selectedUserId, onSelectUser, onHover, onLeave, dayBreaks, groupsByDay, employeesById, hideLaborHours }) {
  return (
    <Box sx={{ minWidth: 640 }}>
      <Box sx={{ display: "flex", position: "sticky", top: 0, zIndex: 2, bgcolor: "#f8fafc", borderBottom: "1px solid #e7edf2" }}>
        <Box sx={{ width: 132, flexShrink: 0, position: "sticky", left: 0, zIndex: 3, bgcolor: "#f8fafc", px: 0.7, py: 0.4 }}>
          <Typography sx={{ fontSize: "0.58rem", fontWeight: 800, color: "text.secondary" }}>EMPLOYEE</Typography>
        </Box>
        <Box sx={{ flex: 1, display: "grid", gridTemplateColumns: `repeat(${Math.max(hours.length, 1)}, 1fr)`, px: 0.5, py: 0.35 }}>
          {(hours.length ? hours : [{ hour: 0, label: "" }]).map((hour) => (
            <Typography key={hour.hour} sx={{ fontSize: "0.55rem", color: "text.secondary", textAlign: "center" }}>{hour.label}</Typography>
          ))}
        </Box>
      </Box>
      <Stack direction="row" spacing={0.4} sx={{ px: 0.7, py: 0.35 }}>
        {dayColumns.map((column) => (
          <Button key={column} size="small" variant={Number(column) === Number(day) ? "contained" : "text"} onClick={() => onFocusDay?.(column)} sx={{ minWidth: 0, px: 0.7, py: 0, fontSize: "0.62rem" }}>
            {DAY_LABELS[column]}
          </Button>
        ))}
      </Stack>
      {lens === LENS.BREAKS && dayBreaks.hot?.length ? (
        <Typography sx={{ px: 0.8, pb: 0.3, fontSize: "0.62rem", fontWeight: 800, color: "#9a3412" }}>
          {dayBreaks.hot.map((window) => `${minutesLabel(window.start)}–${minutesLabel(window.end)} · ${window.count} at once`).join(" · ")}
        </Typography>
      ) : null}
      {employees.map((employee) => {
        const shifts = shiftsFor(employee.user_id, day);
        const tasks = tasksFor(employee.user_id, day);
        const key = `${employee.user_id}:${day}`;
        const selected = Number(selectedUserId) === Number(employee.user_id);
        return (
          <Box
            key={employee.user_id}
            onDragOver={(event) => { event.preventDefault(); setDropKey(key); }}
            onDrop={(event) => dropOn(event, employee.user_id, day)}
            sx={{ display: "flex", minHeight: 34, borderBottom: "1px solid #f1f5f9", bgcolor: dropKey === key || selected ? "#e8f2fb" : "#fff" }}
          >
            <Box onClick={() => onSelectUser?.(employee.user_id)} sx={{ width: 132, flexShrink: 0, position: "sticky", left: 0, zIndex: 1, bgcolor: "inherit", px: 0.7, py: 0.35, cursor: "pointer" }}>
              <Typography sx={{ fontSize: "0.68rem", fontWeight: 700 }} noWrap>{employee.display_name || `User #${employee.user_id}`}</Typography>
              {hideLaborHours ? null : <Typography sx={{ fontSize: "0.56rem", color: "text.secondary" }}>{formatRoleHoursLabel(employee.total_hours || 0)}</Typography>}
            </Box>
            <Box
              sx={{ position: "relative", flex: 1, minHeight: 32 }}
              onClick={() => { if (!shifts.length && canEdit) onCreate?.(employee.user_id, day); }}
            >
              {lens === LENS.BREAKS ? (
                <DayBreakLane userId={employee.user_id} dayBreaks={dayBreaks} windowStart={windowStart} span={span} onEditEntry={onEditEntry} showBreaks={showBreaks} />
              ) : lens === LENS.TASKS ? (
                <Box sx={{ px: 0.4, py: 0.3 }}><TaskCell tasks={tasks} dayGroups={groupsByDay?.[day]} userId={employee.user_id} onEditResponsibility={onEditResponsibility} /></Box>
              ) : shifts.map((entry) => (
                <DayShiftBar
                  key={entry.id}
                  entry={entry}
                  tasks={tasks}
                  windowStart={windowStart}
                  span={span}
                  highlightRole={highlightRole}
                  showBreaks={showBreaks}
                  dragging={Number(draggingId) === Number(entry.id)}
                  onEdit={onEditEntry}
                  onDragStart={onDragStart}
                  onDragEnd={onDragEnd}
                  onHover={onHover}
                  onLeave={onLeave}
                />
              ))}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

function DayShiftBar({ entry, tasks, windowStart, span, highlightRole, showBreaks, dragging, onEdit, onDragStart, onDragEnd, onHover, onLeave }) {
  const segments = shiftRoleSegments(entry);
  const shiftStart = clockMinutes(entry.start_time);
  const shiftEnd = clockMinutes(entry.end_time);
  const bar = placeBar(shiftStart, shiftEnd, windowStart, span);
  if (!bar) return null;
  return (
    <Box
      data-shift-chip
      data-entry-id={entry.id}
      draggable
      onDragStart={(event) => {
        event.stopPropagation();
        event.dataTransfer.setData("text/plain", String(entry.id));
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={(event) => { event.stopPropagation(); onEdit?.(entry); }}
      onMouseEnter={(event) => onHover?.(event.currentTarget, entry, tasks)}
      onMouseLeave={onLeave}
      sx={{ position: "absolute", top: 5, height: 22, ...bar, borderRadius: 0.7, overflow: "hidden", cursor: "pointer", opacity: dragging ? 0.55 : 1, bgcolor: "#e2e8f0" }}
    >
      {segments.map((segment) => {
        const start = clockMinutes(segment.start);
        const end = clockMinutes(segment.end);
        const shiftSpan = Math.max(1, (shiftEnd > shiftStart ? shiftEnd : shiftEnd + 1440) - shiftStart);
        const piece = placeBar(start, end, shiftStart, shiftSpan);
        if (!piece) return null;
        const style = roleStyle(segment.role);
        const dim = highlightRole && highlightRole !== segment.role;
        const wide = ((end > start ? end - start : 0) / shiftSpan) >= 0.16;
        const timeLabel = `${segment.label} ${formatTime12(segment.start)}–${formatTime12(segment.end)}${segment.net == null ? "" : ` · ${hourText(segment.net)}h`}`;
        return (
          <Box
            key={`${segment.role}-${segment.start}`}
            data-role-segment={segment.role}
            title={timeLabel}
            sx={{ position: "absolute", top: 0, bottom: 0, ...piece, bgcolor: style.accent, opacity: dim ? 0.25 : 1 }}
          >
            {wide ? (
              <Typography sx={{ position: "absolute", left: 3, right: 3, top: 0, bottom: 4, display: "flex", alignItems: "center", color: "#fff", fontSize: "0.52rem", fontWeight: 800, pointerEvents: "none", textShadow: "0 1px 1px rgba(15,23,42,0.35)" }} noWrap>
                {roleCompactLabel(segment.role)}
              </Typography>
            ) : null}
          </Box>
        );
      })}
      {showBreaks && Array.isArray(entry.break_slots) ? entry.break_slots.map((slot, index) => {
        const piece = placeBar(clockMinutes(slot.start_time), clockMinutes(slot.end_time), shiftStart, Math.max(1, (shiftEnd > shiftStart ? shiftEnd : shiftEnd + 1440) - shiftStart));
        if (!piece) return null;
        return (
          <Box
            key={index}
            title={`Break ${formatTime12(slot.start_time)}–${formatTime12(slot.end_time)}`}
            sx={{ position: "absolute", bottom: 0, height: 4, ...piece, pointerEvents: "none", backgroundImage: "repeating-linear-gradient(135deg, #9a3412 0 2px, #fff7ed 2px 4px)" }}
          />
        );
      }) : null}
    </Box>
  );
}

function DayBreakLane({ userId, dayBreaks, windowStart, span, onEditEntry, showBreaks }) {
  if (!showBreaks) return null;
  const timed = (dayBreaks?.timed || []).filter((item) => Number(item.userId) === Number(userId));
  const untimed = (dayBreaks?.untimed || []).filter((item) => Number(item.userId) === Number(userId));
  return (
    <Box sx={{ position: "relative", height: 28 }}>
      {timed.map((item) => {
        const piece = placeBar(item.start, item.end, windowStart, span);
        if (!piece) return null;
        const hot = (dayBreaks?.maxOverlap || 0) > BREAK_OVERLAP_CAP;
        return (
          <Box
            key={item.key}
            onClick={(event) => { event.stopPropagation(); onEditEntry?.(item.entry); }}
            sx={{ position: "absolute", top: 6, height: 16, ...piece, borderRadius: 0.6, bgcolor: hot ? "#9a3412" : "#0f766e", cursor: "pointer" }}
            title={`${item.startLabel}–${item.endLabel}`}
          />
        );
      })}
      {untimed.map((item) => (
        <Typography key={item.key} onClick={(event) => { event.stopPropagation(); onEditEntry?.(item.entry); }} sx={{ position: "relative", fontSize: "0.58rem", px: 0.4, cursor: "pointer", color: "text.secondary" }}>
          {`${item.minutes}m untimed`}
        </Typography>
      ))}
    </Box>
  );
}

function CoverageTip({ tip, hideLabor, onHold, onClose }) {
  if (!tip?.anchor || !tip.role || !tip.slice) return null;
  const { role, slice, label } = tip;
  const paint = roleStyle(role.role);
  return (
    <Popper open anchorEl={tip.anchor} placement="top-start" modifiers={[{ name: "offset", options: { offset: [0, 8] } }, { name: "preventOverflow", options: { padding: 8 } }]} sx={{ zIndex: 1400 }}>
      <Box data-ops-coverage-tip onMouseEnter={onHold} onMouseLeave={onClose} sx={{ width: 260, p: 0.9, borderRadius: 1.5, bgcolor: "#fff", border: `1px solid ${paint.border}`, boxShadow: "0 12px 32px rgba(15,23,42,0.16)" }}>
        <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: paint.accent }}>{`${role.label} · ${label}`}</Typography>
        <Typography sx={{ mt: 0.35, fontSize: "0.58rem", fontWeight: 800, color: "#64748b" }}>{`Scheduled ${slice.scheduledCount}`}</Typography>
        {slice.scheduledPeople.map((person) => (
          <Typography key={`sched-${person.name}`} sx={{ fontSize: "0.6rem", color: "#334155" }}>
            {`${person.name}${person.range ? ` · ${person.range}` : person.breakRange ? ` · ${person.breakRange}` : ""}`}
          </Typography>
        ))}
        <Typography sx={{ mt: 0.4, fontSize: "0.58rem", fontWeight: 800, color: "#9a3412" }}>{`On timed break ${slice.breakCount}`}</Typography>
        {slice.breakCount ? slice.breakPeople.map((person) => (
          <Typography key={`break-${person.name}`} sx={{ fontSize: "0.6rem", color: "#9a3412" }}>
            {`${person.name}${person.breakRange ? ` · ${person.breakRange}` : ""}`}
          </Typography>
        )) : <Typography sx={{ fontSize: "0.6rem", color: "#94a3b8" }}>None</Typography>}
        <Typography sx={{ mt: 0.4, fontSize: "0.58rem", fontWeight: 800, color: "#047857" }}>{`Available ${slice.availableCount}`}</Typography>
        {slice.availableCount ? slice.availablePeople.map((person) => (
          <Typography key={`avail-${person.name}`} sx={{ fontSize: "0.6rem", color: "#047857" }}>
            {`${person.name}${person.range ? ` · ${person.range}` : ""}`}
          </Typography>
        )) : <Typography sx={{ fontSize: "0.6rem", color: "#94a3b8" }}>None this hour</Typography>}
        {hideLabor ? null : (
          <Typography sx={{ mt: 0.45, fontSize: "0.6rem", fontWeight: 800 }}>
            {`This hour · Gross ${hourText(slice.grossHours)}h · Net ${hourText(slice.netHours)}h`}
            <br />
            {`Day · Gross ${hourText(role.gross)}h · Net ${hourText(role.net)}h`}
          </Typography>
        )}
      </Box>
    </Popper>
  );
}

function HoverCard({ anchor, entry, tasks, employeeName, dayLabel, showBreaks, hideLabor, onClose, onOpen }) {
  if (!anchor || !entry) return null;
  const parts = entryBreakBreakdown(entry);
  const segments = shiftRoleSegments(entry);
  const gross = parts.grossMinutes / 60;
  const net = (parts.grossMinutes - parts.breakMinutes) / 60;
  const groups = taskStatusRollup(tasks).groups;
  return (
    <Popper open anchorEl={anchor} placement="right-start" modifiers={[{ name: "offset", options: { offset: [8, 8] } }, { name: "preventOverflow", options: { padding: 8 } }]} sx={{ zIndex: 1400 }}>
      <Box data-ops-hover onMouseLeave={onClose} sx={{ width: 280, p: 1.1, borderRadius: 2, bgcolor: "#fff", color: "#0f172a", border: "1px solid #e6ebf2", boxShadow: "0 16px 40px rgba(15,23,42,0.16)" }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 1 }}>
          <Box>
            <Typography sx={{ fontSize: "0.78rem", fontWeight: 800 }}>{employeeName}</Typography>
            <Typography sx={{ fontSize: "0.64rem", color: "#64748b" }}>{dayLabel}</Typography>
          </Box>
          <Button size="small" onClick={onOpen} sx={{ minWidth: 0, px: 1, py: 0.2, borderRadius: 999, fontSize: "0.65rem", fontWeight: 800, textTransform: "none" }}>Open</Button>
        </Box>
        <Typography sx={{ mt: 0.6, fontSize: "0.84rem", fontWeight: 800 }}>{`${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}`}</Typography>
        {hideLabor ? null : <Typography sx={{ fontSize: "0.62rem", color: "#64748b" }}>{`${hourText(gross)}h gross`}</Typography>}
        <Typography sx={{ mt: 0.7, fontSize: "0.6rem", fontWeight: 800, letterSpacing: "0.04em", color: "#94a3b8" }}>ROLE BREAKDOWN</Typography>
        {segments.map((segment) => {
          const paint = roleStyle(segment.role);
          return (
            <Box key={`${segment.role}-${segment.start}`} sx={{ display: "flex", justifyContent: "space-between", gap: 1, mt: 0.25 }}>
              <Typography sx={{ fontSize: "0.64rem", fontWeight: 800, color: paint.accent }}>
                {`${segment.label} · ${formatTime12(segment.start)} – ${formatTime12(segment.end)}`}
              </Typography>
              {hideLabor ? null : <Typography sx={{ fontSize: "0.64rem", fontWeight: 700 }}>{segment.net == null ? "—" : `${hourText(segment.net)}h`}</Typography>}
            </Box>
          );
        })}
        {showBreaks ? (
          <>
            <Typography sx={{ mt: 0.7, fontSize: "0.6rem", fontWeight: 800, letterSpacing: "0.04em", color: "#94a3b8" }}>BREAKS</Typography>
            {(entry.break_slots || []).map((slot, index) => (
              <Typography key={index} sx={{ fontSize: "0.64rem" }}>{`${formatTime12(slot.start_time)} – ${formatTime12(slot.end_time)} · timed`}</Typography>
            ))}
            {parts.unscheduledBreakMinutes > 0 ? <Typography sx={{ fontSize: "0.64rem", color: "#c2410c" }}>{`${parts.unscheduledBreakMinutes}m untimed`}</Typography> : null}
            {!((entry.break_slots || []).length) && parts.unscheduledBreakMinutes <= 0 ? <Typography sx={{ fontSize: "0.64rem", color: "#94a3b8" }}>None</Typography> : null}
          </>
        ) : null}
        <Typography sx={{ mt: 0.7, fontSize: "0.6rem", fontWeight: 800, letterSpacing: "0.04em", color: "#94a3b8" }}>TASKS</Typography>
        {groups.length ? groups.map((group) => (
          <Typography key={group.key} sx={{ fontSize: "0.64rem" }}>{`${group.shared ? "Shared · " : ""}${group.label}`}</Typography>
        )) : <Typography sx={{ fontSize: "0.64rem", color: "#94a3b8" }}>None</Typography>}
        {hideLabor ? null : (
          <Typography sx={{ mt: 0.8, pt: 0.6, borderTop: "1px solid #eef2f6", fontSize: "0.68rem", fontWeight: 800 }}>
            {`Gross ${hourText(gross)}h · Break ${hourText(parts.breakMinutes / 60)}h · Net ${hourText(net)}h`}
          </Typography>
        )}
      </Box>
    </Popper>
  );
}

export { LENS as OPS_LENS, MODE as OPS_MODE };
