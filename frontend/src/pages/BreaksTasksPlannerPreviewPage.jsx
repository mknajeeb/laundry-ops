import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Box } from "@mui/material";
import AssignTasksDialog from "../components/weeklySchedule/AssignTasksDialog";
import BreaksTasksPlanner from "../components/weeklySchedule/BreaksTasksPlanner";
import { PLANNER_SECTION } from "../components/weeklySchedule/breaksTasksPlannerModel";
import { scheduleRoleCatalog, setScheduleRoleCatalog } from "../components/weeklySchedule/weeklyScheduleRoles";

const WEEK = "2026-11-09";
const PEOPLE = [
  { user_id: 56, display_name: "Gabriela" },
  { user_id: 36, display_name: "Yesenia" },
  { user_id: 1, display_name: "Ana" },
  { user_id: 2, display_name: "Ben" },
  { user_id: 3, display_name: "Cam" },
  { user_id: 4, display_name: "Dee" },
];

function shift(id, userId, slots, unscheduled = 0) {
  return {
    id,
    user_id: userId,
    day_of_week: 6,
    start_time: "07:00",
    end_time: "15:00",
    role: "wash",
    break_slots: slots,
    unscheduled_break_minutes: unscheduled,
  };
}

const PREVIEW_ROLES = [
  { code: "wash", name: "Wash", display_order: 1, active: true, uses_time_slots: true },
  {
    code: "agroup_washer_and_floor_cleaning",
    name: "Washer and Floor Cleaning",
    display_order: 2,
    active: true,
    uses_time_slots: false,
  },
];

export default function BreaksTasksPlannerPreviewPage() {
  const previousCatalog = useRef(null);
  if (previousCatalog.current == null) {
    previousCatalog.current = scheduleRoleCatalog();
    setScheduleRoleCatalog(PREVIEW_ROLES);
  }
  useEffect(() => () => setScheduleRoleCatalog(previousCatalog.current), []);
  const [params] = useSearchParams();
  const initial = params.get("section") || PLANNER_SECTION.TIMELINE;
  const [section, setSection] = useState(
    initial === "assign" ? PLANNER_SECTION.TIMELINE : initial,
  );
  const [day, setDay] = useState(6);
  const [entries, setEntries] = useState(() => [
    shift(56, 56, [{ start_time: "12:00", end_time: "12:30" }]),
    shift(1, 1, [{ start_time: "10:00", end_time: "10:30" }]),
    shift(2, 2, [{ start_time: "10:00", end_time: "10:30" }]),
    shift(3, 3, [{ start_time: "10:00", end_time: "10:30" }]),
    shift(4, 4, [{ start_time: "10:00", end_time: "10:20" }]),
  ]);
  const [notice, setNotice] = useState("");
  const [assignOpen, setAssignOpen] = useState(params.get("section") === "assign");
  const [assignError, setAssignError] = useState("");
  const employeesById = useMemo(
    () => Object.fromEntries(PEOPLE.map((person) => [person.user_id, person])),
    [],
  );
  const responsibilities = [
    {
      id: 1,
      user_id: 56,
      day_of_week: 6,
      role: "agroup_washer_and_floor_cleaning",
      assignment_group_id: "shared-1",
      execution_mode: "shared",
      activity_status: "completed",
      timing_label: "10:00 AM",
    },
    {
      id: 2,
      user_id: 36,
      day_of_week: 6,
      role: "agroup_washer_and_floor_cleaning",
      assignment_group_id: "shared-1",
      execution_mode: "shared",
      activity_status: "pending_approval",
      timing_label: "10:00 AM",
    },
  ];

  return (
    <Box sx={{ p: 1.5, maxWidth: 980, mx: "auto" }}>
      <Alert severity="info" sx={{ mb: 1 }}>
        Fixture preview for Saturday, November 14, 2026. Nothing here is saved to a schedule.
      </Alert>
      {notice ? <Alert severity="success" sx={{ mb: 1 }}>{notice}</Alert> : null}
      <BreaksTasksPlanner
        weekStart={WEEK}
        day={day}
        onDayChange={setDay}
        section={section}
        onSectionChange={setSection}
        employees={PEOPLE}
        employeesById={employeesById}
        entries={entries}
        responsibilities={responsibilities}
        canEdit
        onSaveBreak={async (entry, patch) => {
          setEntries((current) =>
            current.map((item) => (item.id === entry.id ? { ...item, ...patch } : item)),
          );
          setNotice("Break saved in this preview only.");
          return true;
        }}
        onEditEntry={() => setNotice("Shift detail opened. Roles stay on this detail, not on the list.")}
        onEditResponsibility={() => setNotice("Task edit opened. Existing completion rules are unchanged.")}
        onAssign={() => {
          setAssignError("");
          setAssignOpen(true);
        }}
        onMoveTask={() => setNotice("Reassign opened for this shared group.")}
      />
      <AssignTasksDialog
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        saving={false}
        error={assignError}
        weekStart={WEEK}
        employees={PEOPLE}
        entries={entries}
        responsibilities={[]}
        defaultDays={[6]}
        defaultUserIds={[56, 36]}
        defaultRole="agroup_washer_and_floor_cleaning"
        defaultTiming="specific_time"
        defaultStart="10:00"
        onSaveBreak={async () => true}
        onAssign={(body) => {
          if (!body.confirm_unscheduled || !body.user_ids.includes(36) || !body.user_ids.includes(56)) {
            setAssignError("Scheduled employees must stay on the assignment.");
            return;
          }
          setAssignOpen(false);
          setNotice("Assigned anyway in this preview. Yesenia was unscheduled. Gabriela stayed on the shared assignment. No shift was created.");
        }}
      />
    </Box>
  );
}
