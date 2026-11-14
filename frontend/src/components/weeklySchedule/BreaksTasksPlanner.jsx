import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getManagementTaskActivityHistory, getManagementTaskDashboard } from "../../api";
import { useI18n } from "../../i18n/I18nContext";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import { DAY_LABELS, DISPLAY_DAY_ORDER, formatDayDate } from "./weeklyScheduleDates";
import { makeBreakSlot, scheduleRoleLabel, validateBreakSlots } from "./weeklyScheduleRoles";
import { suggestedBreakSlot } from "./weeklyScheduleBreakAssignment";
import {
  BREAK_OVERLAP_CAP,
  PLANNER_SECTION,
  applyDashboardRow,
  breaksAfterEdit,
  buildEmployeeRows,
  buildTaskGroups,
  calendarDateForDay,
  dayBreaks,
  filterTaskGroups,
  matchDashboardAssignment,
  maxSimultaneous,
  overlapExceedsCap,
  peopleByState,
  recentCompletions,
  simultaneousBreaks,
  taskGroupCounts,
  timelineScale,
  weekBreakSummary,
} from "./breaksTasksPlannerModel";

function hm(total) {
  const value = ((total % 1440) + 1440) % 1440;
  const hour = Math.floor(value / 60);
  const minute = value % 60;
  const suffix = hour >= 12 ? "PM" : "AM";
  return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

function timerLabel(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "";
  const total = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
}

function SectionButton({ value, current, children, onClick }) {
  const selected = value === current;
  return (
    <Button
      size="small"
      variant={selected ? "contained" : "outlined"}
      onClick={() => onClick(value)}
      aria-pressed={selected}
      sx={{ fontWeight: 800, textTransform: "none" }}
    >
      {children}
    </Button>
  );
}

export function BreaksTasksPlannerPrint({
  section,
  day,
  timeline,
  tasks,
  employeeRows,
  week,
  employees,
}) {
  if (section === PLANNER_SECTION.TASKS) {
    return (
      <table>
        <thead>
          <tr>
            <th>Task</th>
            <th>Day</th>
            <th>Assigned</th>
            <th>Started</th>
            <th>Completed</th>
            <th>Awaiting</th>
          </tr>
        </thead>
        <tbody>
          {(tasks || []).map((group) => {
            const counts = taskGroupCounts(group, employees);
            return (
              <tr key={group.key}>
                <td>{group.label}</td>
                <td>{DAY_LABELS[group.day]}</td>
                <td>{counts.assigned}</td>
                <td>{counts.started}</td>
                <td>{counts.completed}</td>
                <td>{counts.awaiting}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }
  if (section === PLANNER_SECTION.EMPLOYEES) {
    return (
      <table>
        <thead>
          <tr>
            <th>Employee</th>
            <th>Shift</th>
            <th>Breaks</th>
            <th>Tasks</th>
          </tr>
        </thead>
        <tbody>
          {(employeeRows || []).map((row) => (
            <tr key={row.userId}>
              <td>{row.name}</td>
              <td>{row.shiftLabel || "No shift"}</td>
              <td>{row.breakLabel || "—"}</td>
              <td>{row.tasks.map((task) => task.label).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Employee</th>
            <th>Start</th>
            <th>End</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {(timeline?.timed || []).map((item) => (
            <tr key={item.key}>
              <td>{item.name}</td>
              <td>{item.startLabel}</td>
              <td>{item.endLabel}</td>
              <td>{item.duration}</td>
            </tr>
          ))}
          {(timeline?.untimed || []).map((item) => (
            <tr key={item.key}>
              <td>{item.name}</td>
              <td colSpan={3}>{`${item.minutes} min, no time`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>{`Day ${DAY_LABELS[day] || ""}. Overlap above ${BREAK_OVERLAP_CAP} is marked on screen.`}</p>
      <table>
        <thead>
          <tr>
            <th>Day</th>
            <th>Maximum overlap</th>
            <th>Untimed breaks</th>
          </tr>
        </thead>
        <tbody>
          {(week || []).map((item) => (
            <tr key={item.day}>
              <td>{item.label}</td>
              <td>{item.maxOverlap}</td>
              <td>{item.untimed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export default function BreaksTasksPlanner({
  weekStart,
  day,
  onDayChange,
  section,
  onSectionChange,
  employees = [],
  employeesById = {},
  entries = [],
  responsibilities = [],
  canEdit = false,
  onSaveBreak,
  onEditEntry,
  onEditResponsibility,
  onAssign,
  onMoveTask,
}) {
  const { t } = useI18n();
  const [showWeek, setShowWeek] = useState(false);
  const [draft, setDraft] = useState(null);
  const [draftError, setDraftError] = useState("");
  const [overlapPrompt, setOverlapPrompt] = useState(null);
  const [saving, setSaving] = useState(false);
  const [taskRole, setTaskRole] = useState("");
  const [taskEmployee, setTaskEmployee] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [taskScope, setTaskScope] = useState("day");
  const [selectedKey, setSelectedKey] = useState("");
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    if (section !== PLANNER_SECTION.TASKS) return undefined;
    let cancelled = false;
    getManagementTaskDashboard({ date: calendarDateForDay(weekStart, day) })
      .then((res) => {
        if (!cancelled) setDashboard(res.data || null);
      })
      .catch(() => {
        if (!cancelled) setDashboard(null);
      });
    return () => {
      cancelled = true;
    };
  }, [section, weekStart, day, responsibilities]);

  const timeline = useMemo(() => dayBreaks(entries, employeesById, day), [entries, employeesById, day]);
  const segments = useMemo(() => simultaneousBreaks(timeline.timed), [timeline]);
  const scale = useMemo(
    () => timelineScale(timeline.timed, entries.filter((entry) => Number(entry.day_of_week) === Number(day))),
    [timeline, entries, day],
  );
  const week = useMemo(() => weekBreakSummary(entries, employeesById), [entries, employeesById]);
  const groups = useMemo(() => {
    const built = buildTaskGroups(responsibilities, employeesById);
    const shared = dashboard?.shared_assignments || [];
    return built.map((group) => applyDashboardRow(group, matchDashboardAssignment(group, shared)));
  }, [responsibilities, employeesById, dashboard]);
  const visibleTasks = useMemo(
    () =>
      filterTaskGroups(groups, {
        day,
        role: taskRole,
        userId: taskEmployee === "" ? null : Number(taskEmployee),
        status: taskStatus,
        scope: taskScope,
      }),
    [groups, day, taskRole, taskEmployee, taskStatus, taskScope],
  );
  const selected = visibleTasks.find((group) => group.key === selectedKey) || null;
  const employeeRows = useMemo(
    () => buildEmployeeRows({ employees, entries, responsibilities, day, employeesById }),
    [employees, entries, responsibilities, day, employeesById],
  );
  const roleOptions = [...new Set(groups.map((group) => group.role))];

  const saveBreak = async (entry, slots, unscheduled, force = false) => {
    const validation = validateBreakSlots(entry.start_time, entry.end_time, slots);
    if (validation) {
      setDraftError(validation);
      return;
    }
    const next = breaksAfterEdit(entries, employeesById, day, entry.id, slots);
    if (!force && overlapExceedsCap(next)) {
      setOverlapPrompt({ entry, slots, unscheduled, count: maxSimultaneous(next) });
      return;
    }
    setSaving(true);
    setDraftError("");
    const ok = await onSaveBreak?.(entry, {
      break_slots: slots.map((slot) => ({ start_time: slot.start_time, end_time: slot.end_time })),
      unscheduled_break_minutes: Math.max(0, Math.round(Number(unscheduled || 0))),
    });
    setSaving(false);
    if (ok) {
      setDraft(null);
      setOverlapPrompt(null);
    }
  };

  const openBreak = (entry, slots) => {
    setDraftError("");
    setDraft({
      entry,
      slots: (slots?.length ? slots : [suggestedBreakSlot(entry)]).map((slot) =>
        makeBreakSlot({ start_time: slot.start_time, end_time: slot.end_time }),
      ),
      unscheduled: Number(entry.unscheduled_break_minutes || 0),
    });
  };

  const bar = (start, end, color) => {
    const span = Math.max(1, scale.end - scale.start);
    const left = ((Math.max(start, scale.start) - scale.start) / span) * 100;
    const width = ((Math.min(end, scale.end) - Math.max(start, scale.start)) / span) * 100;
    return { left: `${left}%`, width: `${Math.max(width, 1.2)}%`, background: color };
  };

  return (
    <Stack spacing={1} data-breaks-planner={section} sx={{ pb: 2 }}>
      <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
        <SectionButton value={PLANNER_SECTION.TIMELINE} current={section} onClick={onSectionChange}>
          {t("weeklySchedule.planner.timeline")}
        </SectionButton>
        <SectionButton value={PLANNER_SECTION.TASKS} current={section} onClick={onSectionChange}>
          {t("weeklySchedule.planner.tasks")}
        </SectionButton>
        <SectionButton value={PLANNER_SECTION.EMPLOYEES} current={section} onClick={onSectionChange}>
          {t("weeklySchedule.planner.employees")}
        </SectionButton>
      </Stack>
      <Stack direction="row" spacing={0.5} sx={{ overflowX: "auto", pb: 0.25 }}>
        {DISPLAY_DAY_ORDER.map((dow) => (
          <Button
            key={dow}
            size="small"
            variant={dow === day ? "contained" : "text"}
            onClick={() => onDayChange(dow)}
            aria-pressed={dow === day}
            sx={{ minWidth: 72, flexDirection: "column", lineHeight: 1.1, fontWeight: 800, textTransform: "none" }}
          >
            {DAY_LABELS[dow]}
            <Typography component="span" sx={{ fontSize: "0.65rem", fontWeight: 600 }}>
              {weekStart ? formatDayDate(weekStart, dow).replace(/, \d{4}$/, "") : ""}
            </Typography>
          </Button>
        ))}
      </Stack>

      {section === PLANNER_SECTION.TIMELINE ? (
        <Stack spacing={1}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography sx={{ fontWeight: 800, fontSize: "0.9rem" }}>
              {`${t("weeklySchedule.planner.onBreakNow")} · max ${maxSimultaneous(timeline.timed)}`}
            </Typography>
            <Button size="small" onClick={() => setShowWeek((value) => !value)}>
              {showWeek ? t("weeklySchedule.planner.hideWeek") : t("weeklySchedule.planner.weekSummary")}
            </Button>
          </Stack>
          {showWeek ? (
            <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
              {week.map((item) => (
                <Chip
                  key={item.day}
                  size="small"
                  color={item.overCap ? "error" : "default"}
                  label={`${item.label}: ${item.maxOverlap} overlap, ${item.untimed} untimed`}
                />
              ))}
            </Stack>
          ) : null}
          <Box sx={{ position: "relative", height: 22, borderRadius: 1, bgcolor: "#f8fafc", overflow: "hidden" }}>
            {segments.map((segment) => (
              <Box
                key={`${segment.start}-${segment.end}`}
                title={`${segment.count} on break ${hm(segment.start)}–${hm(segment.end)}`}
                sx={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  ...bar(segment.start, segment.end, segment.count > BREAK_OVERLAP_CAP ? "#fca5a5" : "#bfdbfe"),
                }}
              />
            ))}
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            {t("weeklySchedule.planner.overlapNote", { count: BREAK_OVERLAP_CAP })}
          </Typography>
          {timeline.timed.map((item) => (
            <Box
              key={item.key}
              data-break-bar={item.entryId}
              onClick={() => canEdit && openBreak(item.entry, item.entry.break_slots || [])}
              sx={{ display: "grid", gridTemplateColumns: "104px 92px minmax(0, 1fr)", gap: 0.75, alignItems: "center", cursor: canEdit ? "pointer" : "default" }}
            >
              <Typography sx={{ fontSize: "0.8rem", fontWeight: 800 }} noWrap>
                {item.name}
              </Typography>
              <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: "#9a3412" }} noWrap>
                {`${item.startLabel} · ${item.duration}`}
              </Typography>
              <Box sx={{ position: "relative", height: 16, bgcolor: "#f8fafc", borderRadius: 1 }}>
                <Box sx={{ position: "absolute", top: 3, height: 10, borderRadius: 1, ...bar(item.start, item.end, "#fb923c") }} />
              </Box>
            </Box>
          ))}
          {!timeline.timed.length ? (
            <Typography variant="body2" color="text.secondary">
              {t("weeklySchedule.planner.noTimedBreaks")}
            </Typography>
          ) : null}
          <Typography sx={{ fontWeight: 800, fontSize: "0.8rem" }}>{t("weeklySchedule.planner.untimed")}</Typography>
          {timeline.untimed.length ? (
            timeline.untimed.map((item) => (
              <Button key={item.key} size="small" sx={{ justifyContent: "flex-start" }} onClick={() => canEdit && openBreak(item.entry, item.entry.break_slots || [])}>
                {`${item.name} · ${item.minutes} min`}
              </Button>
            ))
          ) : (
            <Typography variant="caption" color="text.secondary">
              {t("weeklySchedule.planner.noUntimed")}
            </Typography>
          )}
          {draft ? (
            <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1 }}>
              <Typography sx={{ fontWeight: 800, fontSize: "0.85rem" }}>{draft.entry ? employeesById[draft.entry.user_id]?.display_name : ""}</Typography>
              {draft.slots.map((slot) => (
                <Stack key={slot.id} direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 0.5 }}>
                  <PlanningTimePicker label={t("weeklySchedule.planner.start")} value={slot.start_time} onChange={(value) => setDraft({ ...draft, slots: draft.slots.map((item) => (item.id === slot.id ? { ...item, start_time: value } : item)) })} />
                  <PlanningTimePicker label={t("weeklySchedule.planner.end")} value={slot.end_time} onChange={(value) => setDraft({ ...draft, slots: draft.slots.map((item) => (item.id === slot.id ? { ...item, end_time: value } : item)) })} />
                </Stack>
              ))}
              <TextField
                size="small"
                type="number"
                label={t("weeklySchedule.planner.untimedMinutes")}
                value={draft.unscheduled}
                onChange={(event) => setDraft({ ...draft, unscheduled: Math.max(0, Number(event.target.value) || 0) })}
                sx={{ mt: 1, maxWidth: 220 }}
              />
              {draftError ? <Alert severity="error" sx={{ mt: 1 }}>{draftError}</Alert> : null}
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <Button size="small" variant="contained" disabled={saving} onClick={() => saveBreak(draft.entry, draft.slots, draft.unscheduled)}>
                  {t("weeklySchedule.planner.save")}
                </Button>
                <Button size="small" color="error" disabled={saving} onClick={() => saveBreak(draft.entry, [], 0, true)}>
                  {t("weeklySchedule.planner.remove")}
                </Button>
                <Button size="small" onClick={() => setDraft(null)}>{t("weeklySchedule.cancel")}</Button>
              </Stack>
            </Box>
          ) : null}
          {canEdit ? (
            <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
              {employeeRows.filter((row) => row.hasShift).map((row) => (
                <Button key={row.userId} size="small" onClick={() => openBreak(row.shifts[0], row.shifts[0].break_slots || [])}>
                  {row.name}
                </Button>
              ))}
            </Stack>
          ) : null}
        </Stack>
      ) : null}

      {section === PLANNER_SECTION.TASKS ? (
        <Stack spacing={1}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
            <TextField select size="small" label={t("weeklySchedule.planner.scope")} value={taskScope} onChange={(event) => setTaskScope(event.target.value)} sx={{ minWidth: 140, flex: "1 1 140px" }}>
              <MenuItem value="day">{t("weeklySchedule.planner.thisDay")}</MenuItem>
              <MenuItem value="week">{t("weeklySchedule.planner.thisWeek")}</MenuItem>
            </TextField>
            <TextField select size="small" label={t("weeklySchedule.taskOrGroup")} value={taskRole} onChange={(event) => setTaskRole(event.target.value)} sx={{ minWidth: 220, flex: "1 1 220px" }}>
              <MenuItem value="">{t("weeklySchedule.planner.allTasks")}</MenuItem>
              {roleOptions.map((role) => (
                <MenuItem key={role} value={role}>{scheduleRoleLabel(role)}</MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label={t("weeklySchedule.employees")} value={taskEmployee} onChange={(event) => setTaskEmployee(event.target.value)} sx={{ minWidth: 160, flex: "1 1 160px" }}>
              <MenuItem value="">{t("weeklySchedule.planner.allEmployees")}</MenuItem>
              {employees.map((employee) => (
                <MenuItem key={employee.user_id} value={String(employee.user_id)}>{employee.display_name}</MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label={t("weeklySchedule.planner.status")} value={taskStatus} onChange={(event) => setTaskStatus(event.target.value)} sx={{ minWidth: 180, flex: "1 1 180px" }}>
              <MenuItem value="">{t("weeklySchedule.planner.anyStatus")}</MenuItem>
              <MenuItem value="not_started">{t("weeklySchedule.planner.notStarted")}</MenuItem>
              <MenuItem value="started">{t("weeklySchedule.planner.started")}</MenuItem>
              <MenuItem value="completed">{t("weeklySchedule.planner.completed")}</MenuItem>
              <MenuItem value="awaiting">{t("weeklySchedule.planner.awaiting")}</MenuItem>
            </TextField>
          </Stack>
          {visibleTasks.map((group) => {
            const counts = taskGroupCounts(group, employees);
            return (
              <Box
                key={group.key}
                data-task-group={group.key}
                onClick={() => setSelectedKey(group.key)}
                sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1, cursor: "pointer", bgcolor: selectedKey === group.key ? "#f0fdfa" : "#fff" }}
              >
                <Typography sx={{ fontWeight: 800, fontSize: "0.86rem" }}>
                  {`${group.label} · ${DAY_LABELS[group.day]}${group.shared ? ` · ${t("weeklySchedule.planner.shared")}` : ""}`}
                </Typography>
                <Typography variant="caption">
                  {`${counts.assigned} assigned · ${counts.started} started · ${counts.completed} completed · ${counts.awaiting} awaiting verification`}
                </Typography>
              </Box>
            );
          })}
          {!visibleTasks.length ? <Typography variant="body2" color="text.secondary">{t("weeklySchedule.planner.noTasks")}</Typography> : null}
          {selected ? (
            <Box sx={{ border: "1px solid #99f6e4", borderRadius: 1, p: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>{selected.label}</Typography>
              <Typography variant="caption" color="text.secondary">
                {selected.shared
                  ? t("weeklySchedule.planner.sharedTimers")
                  : t("weeklySchedule.planner.individualTask")}
              </Typography>
              {["assigned", "started", "completed", "awaiting"].map((state) => (
                <Typography key={state} sx={{ fontSize: "0.8rem" }}>
                  {`${t(`weeklySchedule.planner.bucket.${state}`)}: ${peopleByState(selected, state).map((member) => `${member.name}${member.duration != null ? ` (${timerLabel(member.duration)})` : ""}`).join(", ") || "—"}`}
                </Typography>
              ))}
              <Typography sx={{ fontSize: "0.8rem" }}>
                {`${t("weeklySchedule.planner.bucket.unassigned")}: ${employees.filter((employee) => !selected.members.some((member) => member.userId === Number(employee.user_id))).map((employee) => employee.display_name).join(", ") || "—"}`}
              </Typography>
              {selected.checklist?.length ? (
                <Box sx={{ mt: 0.5 }}>
                  <Typography sx={{ fontWeight: 800, fontSize: "0.8rem" }}>
                    {`${t("weeklySchedule.planner.checklist")} · ${selected.checklistStatus || ""}`}
                  </Typography>
                  {selected.checklist.map((item) => (
                    <Typography key={item.id || item.task_code} variant="caption" sx={{ display: "block" }}>
                      {`${item.task_name || item.task_code || "Item"} · ${item.completed_by_name || item.status || ""}`}
                    </Typography>
                  ))}
                </Box>
              ) : null}
              <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", mt: 0.5 }}>{t("weeklySchedule.planner.recent")}</Typography>
              {recentCompletions(dashboard?.activity_log || [], selected.role).map((item) => (
                <Typography key={item.id} variant="caption" sx={{ display: "block" }}>
                  {`${item.name} · ${item.status}${item.duration != null ? ` · ${timerLabel(item.duration)}` : ""}`}
                </Typography>
              ))}
              {historyError ? <Alert severity="error">{historyError}</Alert> : null}
              {history ? (
                history.length ? history.map((item) => (
                  <Typography key={item.id} variant="caption" sx={{ display: "block" }}>
                    {`${item.change_type || "correction"} · ${item.reason || ""} · ${String(item.created_at || "").replace("T", " ").slice(0, 19)}`}
                  </Typography>
                )) : <Typography variant="caption">{t("weeklySchedule.planner.noHistory")}</Typography>
              ) : null}
              <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                <Button size="small" variant="contained" onClick={() => onAssign?.({ day: selected.day, role: selected.role })}>{t("weeklySchedule.assign")}</Button>
                <Button size="small" onClick={() => onMoveTask?.(selected.members[0] ? { id: selected.members[0].responsibilityId, ...selected } : selected)}>{t("weeklySchedule.planner.reassign")}</Button>
                <Button size="small" onClick={() => onEditResponsibility?.({ id: selected.id, role: selected.role, day_of_week: selected.day, user_id: selected.members[0]?.userId })}>{t("weeklySchedule.planner.edit")}</Button>
                <Button
                  size="small"
                  onClick={async () => {
                    const activityId = selected.members.map((member) => member.activityId).find(Boolean);
                    if (!activityId) {
                      setHistory([]);
                      return;
                    }
                    setHistoryError("");
                    try {
                      const res = await getManagementTaskActivityHistory({ activity_id: activityId });
                      setHistory(res.data?.revisions || []);
                    } catch (error) {
                      setHistoryError(error?.response?.data?.error || t("weeklySchedule.planner.historyFailed"));
                    }
                  }}
                >
                  {t("weeklySchedule.planner.history")}
                </Button>
              </Stack>
            </Box>
          ) : null}
        </Stack>
      ) : null}

      {section === PLANNER_SECTION.EMPLOYEES ? (
        <Stack spacing={0.5}>
          {employeeRows.map((row) => (
            <Box
              key={row.userId}
              data-employee-row={row.userId}
              title={row.roles.map((role) => scheduleRoleLabel(role)).join(", ")}
              onClick={() => setSelectedEmployee(row)}
              sx={{ borderBottom: "1px solid #e2e8f0", py: 0.5, cursor: "pointer" }}
            >
              <Stack direction="row" spacing={1} justifyContent="space-between">
                <Typography sx={{ fontWeight: 800, fontSize: "0.82rem" }} noWrap>{row.name}</Typography>
                <Typography sx={{ fontSize: "0.78rem" }} noWrap>{row.shiftLabel || t("weeklySchedule.planner.noShift")}</Typography>
              </Stack>
              <Typography sx={{ fontSize: "0.75rem", color: "text.secondary" }} noWrap>
                {`${row.breakLabel || t("weeklySchedule.planner.noBreak")} · ${row.tasks.map((task) => task.label).join(", ") || "—"}`}
              </Typography>
            </Box>
          ))}
          {selectedEmployee ? (
            <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1 }}>
              <Typography sx={{ fontWeight: 800 }}>{selectedEmployee.name}</Typography>
              <Typography variant="body2">{selectedEmployee.shiftLabel || t("weeklySchedule.planner.noShift")}</Typography>
              <Typography variant="body2">{selectedEmployee.breakLabel || t("weeklySchedule.planner.noBreak")}</Typography>
              <Typography variant="body2">{selectedEmployee.tasks.map((task) => task.label).join(", ") || t("weeklySchedule.planner.noTasks")}</Typography>
              <Typography variant="caption" color="text.secondary">
                {selectedEmployee.roles.length
                  ? selectedEmployee.roles.map((role) => scheduleRoleLabel(role)).join(", ")
                  : selectedEmployee.hasShift
                    ? t("weeklySchedule.planner.noRole")
                    : ""}
              </Typography>
              {canEdit && selectedEmployee.shifts[0] ? (
                <Button size="small" sx={{ mt: 0.5 }} onClick={() => onEditEntry?.(selectedEmployee.shifts[0])}>
                  {t("weeklySchedule.planner.editShift")}
                </Button>
              ) : null}
            </Box>
          ) : null}
        </Stack>
      ) : null}

      <Dialog open={Boolean(overlapPrompt)} onClose={() => setOverlapPrompt(null)}>
        <DialogTitle>{t("weeklySchedule.planner.overlapTitle")}</DialogTitle>
        <DialogContent>
          <Typography>
            {t("weeklySchedule.planner.overlapConfirm", { count: overlapPrompt?.count || 0, cap: BREAK_OVERLAP_CAP })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOverlapPrompt(null)}>{t("weeklySchedule.cancel")}</Button>
          <Button
            variant="contained"
            color="warning"
            onClick={() => saveBreak(overlapPrompt.entry, overlapPrompt.slots, overlapPrompt.unscheduled, true)}
          >
            {t("weeklySchedule.planner.saveAnyway")}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
