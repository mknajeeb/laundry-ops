/**
 * Local visual preview for Activity checklist responsibility.
 * Route: /dev/activity-responsibility-preview?panel=assign|pin|review
 * Not linked from production nav.
 */
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Stack, Typography } from "@mui/material";
import SharedActivityChecklist from "../components/tasks/SharedActivityChecklist";
import TaskVerificationReviewCard from "../components/tasks/TaskVerificationReviewCard";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";

const PREVIEW_ITEMS = [
  {
    group_item_id: 11,
    task_code: "floor_cleaning",
    task_name: "Floor broom",
    responsibility_mode: "team",
    user_ids: [],
    dirty: false,
  },
  {
    group_item_id: 12,
    task_code: "lint_cleaning",
    task_name: "Dryer lint",
    responsibility_mode: "named",
    user_ids: [5],
    dirty: false,
  },
];

const PIN_ITEMS = [
  {
    task_code: "floor_cleaning",
    task_name: "Floor broom",
    required: true,
    status: "pending",
    responsibility_mode: "team",
    responsibility_label: "Anyone on Team",
    instructions: "Start at the washers and work toward the door.",
  },
  {
    task_code: "lint_cleaning",
    task_name: "Dryer lint",
    required: true,
    status: "completed",
    responsibility_mode: "named",
    responsibility_user_ids: [7],
    responsibility_label: "Alex",
    completed_by_name: "Sam",
  },
  {
    task_code: "trash",
    task_name: "Trash run",
    required: true,
    status: "pending",
    responsibility_mode: "named",
    responsibility_user_ids: [9],
    responsibility_label: "Sam",
  },
];

const REVIEW_CARD = {
  assignment_key: "preview",
  role_label: "Routine Cleaning",
  category_label: "Intra-Day",
  timing_label: "Anytime",
  assigned_employees: ["Alex", "Sam"],
  overall_status: "pending_verification",
  overall_label: "Pending verification",
  checklist: [
    {
      task_code: "floor_cleaning",
      task_label: "Floor broom",
      checked_off: true,
      responsibility_label: "Anyone on Team",
      completed_by_name: "Sam",
      records: [
        {
          activity_id: 1,
          employee_name: "Sam",
          checked_off_at: "2026-11-01 14:12:00",
          status: "pending_approval",
        },
      ],
    },
    {
      task_code: "lint_cleaning",
      task_label: "Dryer lint",
      checked_off: false,
      responsibility_label: "Alex",
      records: [],
    },
  ],
};

const RESPONSIBILITY = {
  id: 1,
  role: "agroup_routine",
  user_id: 7,
  user_ids: [7, 9],
  day_of_week: 0,
  remarks: "",
};

const EMPLOYEES = {
  7: { display_name: "Alex" },
  9: { display_name: "Sam" },
};

export default function ActivityResponsibilityPreviewPage() {
  const [params] = useSearchParams();
  const panel = params.get("panel") || "all";
  const conflicts = useMemo(
    () => [
      {
        task_code: "lint_cleaning",
        task_name: "Dryer lint",
        removed_user_ids: [5],
      },
    ],
    []
  );
  const show = (name) => panel === "all" || panel === name;

  return (
    <Box sx={{ p: 2, bgcolor: "#f8fafc", minHeight: "100vh" }}>
      <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
        Activity responsibility preview
      </Typography>
      {show("assign") ? (
        <WeeklyScheduleEntryDialog
          open
          onClose={() => {}}
          onSave={() => {}}
          responsibility={RESPONSIBILITY}
          employeesById={EMPLOYEES}
          taskEmployees={[
            { user_id: 7, display_name: "Alex" },
            { user_id: 9, display_name: "Sam" },
          ]}
          responsibilityConflicts={conflicts}
          previewActivityItems={PREVIEW_ITEMS}
          error="Resolve checklist responsibility before removing this employee. Affected items: Dryer lint."
        />
      ) : null}
      {show("pin") ? (
        <Stack spacing={1} sx={{ maxWidth: 420, mb: 3 }}>
          <Typography sx={{ fontWeight: 800 }}>Employee PIN</Typography>
          <SharedActivityChecklist items={PIN_ITEMS} userId={7} onCheckoff={() => {}} />
        </Stack>
      ) : null}
      {show("review") ? (
        <Stack spacing={1} sx={{ maxWidth: 480 }}>
          <Typography sx={{ fontWeight: 800 }}>Supervisor review</Typography>
          <TaskVerificationReviewCard card={REVIEW_CARD} onApproveAll={() => {}} onNeedsRedo={() => {}} onRejectItem={() => {}} />
        </Stack>
      ) : null}
    </Box>
  );
}
