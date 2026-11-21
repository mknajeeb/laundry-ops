import { useState } from "react";
import { Alert, Box, Paper, Stack, Typography } from "@mui/material";
import TaskRecurrenceFields from "../components/tasks/TaskRecurrenceFields";
import TaskCompletionInputs from "../opsMobile/TaskCompletionInputs";
import { FacilityProgress } from "./CleaningTaskReviewPinPage";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";

const ASSIGNEES = [
  { user_id: 36, name: "Yesenia" },
  { user_id: 56, name: "Gabriela" },
];

const MACHINES = [
  { machine_code: "W22-30-VW", machine_type: "washer", display_number: "W22-30-VW", operational_status: "operational", cleaning_eligible: true, cleaned_this_week: false },
  { machine_code: "W23-30-VW", machine_type: "washer", display_number: "W23-30-VW", operational_status: "operational", cleaning_eligible: true, cleaned_this_week: false },
  { machine_code: "W24-30-VW", machine_type: "washer", display_number: "W24-30-VW", operational_status: "operational", cleaning_eligible: true, cleaned_this_week: true },
  { machine_code: "W25-30-VW", machine_type: "washer", display_number: "W25-30-VW", operational_status: "out_of_service", cleaning_eligible: false, exclusion_reason: "Bearing noise" },
];

export function DevFacilityTaskConfigPreviewPage() {
  const [draft, setDraft] = useState({
    name: "Washer Deep Cleaning",
    recurrence: {
      mode: "recurring",
      weekly_frequency: 1,
      weekdays: [1, 4],
      effective_start: "2026-11-15",
      effective_end: "",
      time_window: { start: "14:00" },
      assignee_user_ids: [36],
      temporary_exceptions: [{ date: "2026-11-26", reason: "Skipped by management" }],
      paused: false,
    },
  });
  const [notice, setNotice] = useState("");
  return (
    <Box sx={{ p: 2, maxWidth: 720, mx: "auto" }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 1 }}>Task Management · Facility Cleaning</Typography>
      <Alert severity="info" sx={{ mb: 1.5 }}>Washer Deep Cleaning. This preview does not write a task.</Alert>
      {notice ? <Alert severity="success" sx={{ mb: 1.5 }}>{notice}</Alert> : null}
      <Paper sx={{ p: 2 }}>
        <Stack spacing={1.25}>
          <Typography fontWeight={800}>{draft.name}</Typography>
          <TaskRecurrenceFields
            draft={draft}
            setDraft={setDraft}
            assignees={ASSIGNEES}
            onReconcile={() => setNotice("Reconcile requested. Opening the schedule also creates missing weeks automatically.")}
          />
        </Stack>
      </Paper>
    </Box>
  );
}

export function DevFacilityProgressPreviewPage() {
  return (
    <Box sx={{ p: 1.5, maxWidth: 720, mx: "auto" }}>
      <FacilityProgress
        date="2026-11-15"
        onShift={() => {}}
        progress={{
          week_start: "2026-11-15",
          tasks: [
            {
              task_code: "custom_washer_deep_cleaning",
              name: "Washer Deep Cleaning",
              required: 2,
              completed: 1,
              verified: 1,
              pending_verification: 0,
              skipped: 0,
              remaining: 1,
              overdue: 1,
              assignees: ["Yesenia"],
              machines: [
                { machine_code: "W23-30-VW", display_number: "W23-30-VW", remaining: 1, excluded: false },
                { machine_code: "W24-30-VW", display_number: "W24-30-VW", remaining: 0, excluded: false },
                { machine_code: "W25-30-VW", display_number: "W25-30-VW", remaining: 0, excluded: true, reason: "Bearing noise" },
              ],
            },
            {
              task_code: "custom_bathroom_cleaning",
              name: "Bathroom Cleaning",
              required: 3,
              completed: 1,
              verified: 0,
              pending_verification: 1,
              skipped: 1,
              remaining: 1,
              overdue: 0,
              assignees: [],
            },
          ],
          exclusions: [{ machine_code: "W25-30-VW", reason: "Bearing noise" }],
        }}
      />
    </Box>
  );
}

export function DevFacilityMachineSelectPreviewPage() {
  const [values, setValues] = useState({ machines: ["W23-30-VW"] });
  return (
    <Box sx={{ p: 1.5, maxWidth: 480, mx: "auto" }}>
      <Typography fontWeight={800} sx={{ mb: 1 }}>Employee task · select machines</Typography>
      <TaskCompletionInputs
        schema={[{ id: "machines", type: "machine_numbers", label: "Washers", machine_kind: "washer", required: true }]}
        values={values}
        onChangeValues={setValues}
        machines={MACHINES}
      />
    </Box>
  );
}

export function DevFacilityReportPreviewPage() {
  return (
    <Box sx={{ p: 1, maxWidth: 480, mx: "auto" }}>
      <LostFoundReportForm
        initialCategory="equipment"
        initialKind="washer"
        initialNumber="W24-30-VW"
        choices={{ washers: ["W23-30-VW", "W24-30-VW"], dryers: ["D1-50-VW"] }}
        onSubmit={async () => {}}
      />
    </Box>
  );
}
