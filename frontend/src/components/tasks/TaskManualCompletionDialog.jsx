import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { businessTodayYmd } from "../../utils/businessTime";

/**
 * Supervisor Record Completion / Correct Completion dialog.
 * Shared Activity Groups require per-item employee attribution.
 */
export default function TaskManualCompletionDialog({
  open,
  mode = "manual", // manual | correct
  assignment,
  contribution,
  onClose,
  onSubmit,
  busy = false,
}) {
  const employeeId = contribution?.employee_id || "";
  const members = useMemo(() => {
    if (Array.isArray(assignment?.members) && assignment.members.length) {
      return assignment.members;
    }
    return (assignment?.contributions || []).map((c) => ({
      employee_id: c.employee_id,
      employee_name: c.employee_name,
      responsibility_id: c.responsibility_id,
    }));
  }, [assignment]);

  const isShared =
    assignment?.execution_mode === "shared" ||
    Boolean(assignment?.shared_session_id) ||
    (members.length > 1 && Boolean(assignment?.assignment_group_id));

  const checklistItems = useMemo(() => {
    const fromShared = assignment?.shared_checklist_items || [];
    if (fromShared.length) {
      return fromShared.map((it) => ({
        task_code: it.task_code,
        task_name: it.task_name || it.task_code,
      }));
    }
    const fromTemplate = assignment?.activity_group_items || [];
    if (fromTemplate.length) {
      return fromTemplate.map((it) => ({
        task_code: it.task_code,
        task_name: it.task_name || it.task_code,
      }));
    }
    const fromGroup = contribution?.group_items || [];
    return fromGroup.map((gi) => ({
      task_code: gi.task_code || gi.role,
      task_name: gi.role_label || gi.task_name || gi.task_code || gi.role,
    }));
  }, [assignment, contribution]);

  const [completionDate, setCompletionDate] = useState(businessTodayYmd());
  const [completionTime, setCompletionTime] = useState("10:00");
  const [includeStart, setIncludeStart] = useState(false);
  const [startDate, setStartDate] = useState(businessTodayYmd());
  const [startTime, setStartTime] = useState("09:45");
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [itemCodes, setItemCodes] = useState([]);
  /** @type {Record<string, number|''>} */
  const [itemOwners, setItemOwners] = useState({});

  useEffect(() => {
    if (!open) return;
    setReason("");
    setRemarks("");
    setIncludeStart(false);
    setCompletionDate(businessTodayYmd());
    setCompletionTime("10:00");
    const codes = checklistItems.map((i) => i.task_code).filter(Boolean);
    setItemCodes(codes);
    const owners = {};
    checklistItems.forEach((it) => {
      const prior = (assignment?.shared_checklist_items || []).find(
        (s) => s.task_code === it.task_code
      );
      owners[it.task_code] =
        prior?.completed_by_user_id ||
        (members.length === 1 ? members[0].employee_id : employeeId || "");
    });
    setItemOwners(owners);
  }, [open, checklistItems, members, employeeId, assignment?.shared_checklist_items]);

  const title = mode === "correct" ? "Correct Completion Record" : "Record Completion";
  const sharedReady =
    !isShared ||
    checklistItems.every((it) => itemOwners[it.task_code]) ||
    checklistItems.length === 0;

  const submit = () => {
    const body = {
      reason,
      remarks: remarks || undefined,
      completion_date: completionDate,
      completion_time: completionTime,
      business_date: completionDate,
      employee_user_id: employeeId,
      responsibility_id: contribution?.responsibility_id,
      activity_id: contribution?.activity?.id,
    };
    if (includeStart) {
      body.start_date = startDate;
      body.start_time = startTime;
    }
    if (isShared && checklistItems.length) {
      body.shared_item_completions = checklistItems
        .filter((it) => itemOwners[it.task_code])
        .map((it) => ({
          task_code: it.task_code,
          completed_by_user_id: Number(itemOwners[it.task_code]),
        }));
    } else if (itemCodes.length) {
      body.group_item_codes = itemCodes;
    }
    onSubmit?.(body);
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {assignment?.role_label || assignment?.role} · {contribution?.employee_name}
          {mode === "manual"
            ? " — use when work was done outside the PIN app."
            : " — audited revision; original history is preserved."}
        </Typography>
        <Stack spacing={1.5}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              type="date"
              size="small"
              label="Completion date"
              InputLabelProps={{ shrink: true }}
              value={completionDate}
              onChange={(e) => setCompletionDate(e.target.value)}
              fullWidth
            />
            <TextField
              type="time"
              size="small"
              label="Completion time (ET)"
              InputLabelProps={{ shrink: true }}
              value={completionTime}
              onChange={(e) => setCompletionTime(e.target.value)}
              fullWidth
            />
          </Stack>
          <FormControlLabel
            control={
              <Switch checked={includeStart} onChange={(e) => setIncludeStart(e.target.checked)} />
            }
            label="Actual start known (optional — leave off to avoid fabricating duration)"
          />
          {includeStart ? (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                type="date"
                size="small"
                label="Start date"
                InputLabelProps={{ shrink: true }}
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                fullWidth
              />
              <TextField
                type="time"
                size="small"
                label="Start time (ET)"
                InputLabelProps={{ shrink: true }}
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                fullWidth
              />
            </Stack>
          ) : null}

          {isShared && checklistItems.length ? (
            <Stack spacing={1}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                Who completed each shared item?
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Do not attribute every item to one employee by default — select the person who
                actually did each task.
              </Typography>
              {checklistItems.map((it) => (
                <TextField
                  key={it.task_code}
                  select
                  size="small"
                  label={it.task_name || it.task_code}
                  value={itemOwners[it.task_code] || ""}
                  onChange={(e) =>
                    setItemOwners((prev) => ({
                      ...prev,
                      [it.task_code]: e.target.value ? Number(e.target.value) : "",
                    }))
                  }
                  fullWidth
                >
                  <MenuItem value="">Select employee…</MenuItem>
                  {members.map((m) => (
                    <MenuItem key={m.employee_id} value={m.employee_id}>
                      {m.employee_name}
                    </MenuItem>
                  ))}
                </TextField>
              ))}
            </Stack>
          ) : null}

          {!isShared && checklistItems.length ? (
            <TextField
              select
              SelectProps={{ multiple: true }}
              size="small"
              label="Completed group items"
              value={itemCodes}
              onChange={(e) => setItemCodes(e.target.value)}
              fullWidth
            >
              {checklistItems.map((gi) => (
                <MenuItem key={gi.task_code} value={gi.task_code}>
                  {gi.task_name || gi.task_code}
                </MenuItem>
              ))}
            </TextField>
          ) : null}

          <TextField
            size="small"
            label="Reason (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            fullWidth
            multiline
            minRows={2}
            placeholder="Employee forgot to complete task in PIN app."
          />
          <TextField
            size="small"
            label="Remarks (optional)"
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={busy || reason.trim().length < 3 || !sharedReady}
          onClick={submit}
        >
          {mode === "correct" ? "Save correction" : "Record completion"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
