import { useEffect, useMemo, useState } from "react";
import { Box } from "@mui/material";
import AssignTasksDialog from "../components/weeklySchedule/AssignTasksDialog";
import OperationsPlanner, { OPS_LENS, OPS_MODE } from "../components/weeklySchedule/OperationsPlanner";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";
import { DISPLAY_DAY_ORDER } from "../components/weeklySchedule/weeklyScheduleDates";
import { buildHourlyCoverage } from "../components/weeklySchedule/weeklyScheduleTimeBlocks";
import {
  computeWeekSummary,
  setScheduleRoleCatalog,
  setScheduleRoleGroups,
  withDisplayedTotals,
} from "../components/weeklySchedule/weeklyScheduleRoles";

const NAMES = [
  "Amna", "Maria Rodriguez", "Gabriela", "Angelica", "Rocio", "Yesenia", "Luis", "Camila",
  "Nora", "Hassan", "Priya", "Diego", "Sofia", "Elena", "Omar", "Lina", "Jonah", "Aisha", "Pedro", "Mei",
];
const PEOPLE = NAMES.map((display_name, index) => ({ user_id: index + 1, display_name }));
const ROLE_CYCLE = ["wash", "sort", "fold", "dry", "hd_operator"];

let nextId = 1;
function shift(userId, day, start, end, role, extra = {}) {
  const id = nextId;
  nextId += 1;
  const roles = extra.roles || [role];
  return {
    id,
    user_id: userId,
    day_of_week: day,
    start_time: start,
    end_time: end,
    role: roles.join(","),
    roles,
    assignments: extra.assignments || roles.map((code) => ({ role: code, full_shift: true })),
    break_minutes: extra.break_minutes || 0,
    break_slots: extra.break_slots || [],
    unscheduled_break_minutes: extra.unscheduled_break_minutes || 0,
  };
}

/** Local sample only. Monday noon has four timed breaks overlapping, plus breaks without a time. */
const ENTRIES = [
  shift(1, 1, "07:00", "15:00", "wash", {
    roles: ["wash", "fold"],
    assignments: [
      { role: "wash", full_shift: false, start_time: "07:00", end_time: "11:00" },
      { role: "fold", full_shift: false, start_time: "11:00", end_time: "15:00" },
    ],
    break_minutes: 30,
    break_slots: [{ start_time: "12:00", end_time: "12:30" }],
  }),
  shift(2, 1, "08:00", "16:00", "fold", { break_minutes: 30, break_slots: [{ start_time: "12:00", end_time: "12:30" }] }),
  shift(3, 1, "09:00", "17:00", "sort", { break_minutes: 30, break_slots: [{ start_time: "12:00", end_time: "12:20" }] }),
  shift(4, 1, "10:00", "18:00", "dry", { break_minutes: 30, break_slots: [{ start_time: "12:00", end_time: "12:25" }] }),
  shift(5, 1, "09:00", "17:00", "fold", { break_minutes: 30, unscheduled_break_minutes: 30 }),
  shift(6, 1, "08:00", "14:00", "hd_operator", { break_minutes: 15, unscheduled_break_minutes: 15 }),
  shift(7, 1, "06:00", "14:00", "wash", { break_minutes: 30, break_slots: [{ start_time: "10:00", end_time: "10:30" }] }),
  shift(8, 1, "11:00", "19:00", "fold"),
  ...PEOPLE.filter((person) => person.user_id >= 9).flatMap((person) => {
    const role = ROLE_CYCLE[person.user_id % ROLE_CYCLE.length];
    const startHour = 6 + (person.user_id % 4);
    const endHour = startHour + 8;
    const pad = (hour) => `${String(hour).padStart(2, "0")}:00`;
    const days = [1, 2, 3, 4, 5, 6].filter((day) => (person.user_id + day) % 3 !== 0).slice(0, 4);
    return days.map((day) => shift(person.user_id, day, pad(startHour), pad(endHour), role, day === 1 && person.user_id % 2 === 0
      ? { break_minutes: 20, unscheduled_break_minutes: 20 }
      : {}));
  }),
  shift(1, 2, "07:00", "15:00", "wash"),
  shift(2, 3, "08:00", "16:00", "fold"),
  shift(3, 4, "09:00", "15:00", "sort"),
  shift(7, 5, "06:00", "14:00", "sort"),
  shift(4, 6, "10:00", "16:00", "dry"),
  shift(5, 6, "10:00", "16:00", "dry"),
];

const TASKS = [
  { id: 101, user_id: 1, day_of_week: 1, role: "floor_cleaning", activity_status: "completed", assignment_group_id: "shared-floor", execution_mode: "shared" },
  { id: 102, user_id: 2, day_of_week: 1, role: "floor_cleaning", activity_status: "pending_approval", assignment_group_id: "shared-floor", execution_mode: "shared" },
  { id: 103, user_id: 4, day_of_week: 6, role: "lint_cleaning", activity_status: "in_progress", assignment_group_id: "shared-lint", execution_mode: "shared" },
  { id: 104, user_id: 5, day_of_week: 6, role: "lint_cleaning", activity_status: null, assignment_group_id: "shared-lint", execution_mode: "shared" },
  { id: 105, user_id: 7, day_of_week: 3, role: "washer_cleaning", activity_status: "approved" },
  { id: 106, user_id: 9, day_of_week: 1, role: "washer_cleaning", activity_status: null },
];

function indexByCell(rows) {
  const out = {};
  for (const row of rows) {
    const key = `${row.user_id}:${row.day_of_week}`;
    if (!out[key]) out[key] = [];
    out[key].push(row);
  }
  return out;
}

/** Local layout review only. Saves stay in this page and do not call the schedule API. */
export default function OperationsPlannerPreviewPage() {
  const [mode, setMode] = useState(OPS_MODE.WEEK);
  const [lens, setLens] = useState(OPS_LENS.EMPLOYEES);
  const [focusDay, setFocusDay] = useState(1);
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [editEntry, setEditEntry] = useState(null);
  const [editTask, setEditTask] = useState(null);
  const [assignOpen, setAssignOpen] = useState(false);
  useEffect(() => {
    setScheduleRoleCatalog(null);
    setScheduleRoleGroups([]);
  }, []);
  const employeesById = useMemo(() => Object.fromEntries(PEOPLE.map((person) => [person.user_id, person])), []);
  const employees = useMemo(() => withDisplayedTotals(PEOPLE, ENTRIES), []);
  const weekSummary = useMemo(() => computeWeekSummary({ employees: PEOPLE, entries: ENTRIES }, {}), []);
  const coverageDays = useMemo(
    () => buildHourlyCoverage(ENTRIES, { dayIndices: DISPLAY_DAY_ORDER, employeesById, responsibilities: TASKS }),
    [employeesById],
  );

  return (
    <Box sx={{ height: "100vh", display: "flex", bgcolor: "#f4f7f8" }}>
      <OperationsPlanner
        weekLabel="Nov 9 – Nov 15, 2026"
        weekStart="2026-11-09"
        onPrevWeek={() => {}}
        onNextWeek={() => {}}
        employerTabs={[
          { key: "veewash", label: "VeeWash", count: 0 },
          { key: "rinse", label: "Rinse Exclusive", count: PEOPLE.length },
          { key: "combined", label: "Combined", count: PEOPLE.length },
        ]}
        employerTab="rinse"
        onEmployerTab={() => {}}
        employees={employees}
        dayColumns={DISPLAY_DAY_ORDER}
        entriesByCell={indexByCell(ENTRIES)}
        responsibilitiesByCell={indexByCell(TASKS)}
        entries={ENTRIES}
        weekSummary={weekSummary}
        coverageDays={coverageDays}
        focusDay={focusDay}
        onFocusDay={setFocusDay}
        mode={mode}
        onMode={setMode}
        lens={lens}
        onLens={setLens}
        canEdit
        showBreaks
        employeesById={employeesById}
        onEditEntry={setEditEntry}
        onCreate={() => setEditEntry({ user_id: 10, day_of_week: focusDay })}
        onEditResponsibility={(item) => setEditTask(item)}
        onDropEntry={() => {}}
        addableEmployees={[{ user_id: 21, display_name: "New hire" }]}
        onAddEmployee={() => {}}
        onAssign={() => setAssignOpen(true)}
        menuAnchor={menuAnchor}
        onOpenMenu={(event) => setMenuAnchor(event.currentTarget)}
        onCloseMenu={() => setMenuAnchor(null)}
        menuItems={[
          { id: "mapping", label: "User mapping" },
          { id: "roles", label: "Roles & tasks" },
          { id: "bulk", label: "All to Rinse Exclusive" },
          { id: "copy", label: "Copy to future weeks" },
          { id: "export", label: "Export CSV" },
          { id: "print", label: "Print" },
        ]}
      />
      <WeeklyScheduleEntryDialog
        open={Boolean(editEntry?.start_time) || Boolean(editTask)}
        entry={editEntry?.start_time ? editEntry : null}
        responsibility={editTask}
        employees={PEOPLE}
        employeesById={employeesById}
        scheduleEntries={ENTRIES}
        dailyResponsibilities={TASKS}
        weekStart="2026-11-09"
        onClose={() => {
          setEditEntry(null);
          setEditTask(null);
        }}
        onSave={() => {
          setEditEntry(null);
          setEditTask(null);
        }}
      />
      <AssignTasksDialog
        open={assignOpen}
        weekStart="2026-11-09"
        employees={PEOPLE}
        entries={ENTRIES}
        responsibilities={TASKS}
        onClose={() => setAssignOpen(false)}
        onAssign={() => setAssignOpen(false)}
        onSaveBreak={() => true}
      />
    </Box>
  );
}
