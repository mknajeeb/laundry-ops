import { Button, FormControlLabel, MenuItem, Stack, Switch, TextField, Typography } from "@mui/material";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function TaskRecurrenceFields({ draft, setDraft, assignees = [], busy = false, onReconcile }) {
  const recurrence = draft?.recurrence || {};
  const setRecurrence = (patch) => setDraft({ ...draft, recurrence: { ...recurrence, ...patch } });
  return (
    <>
      <Typography fontWeight={800}>Recurrence</Typography>
      <TextField
        select
        size="small"
        label="Assignment"
        value={recurrence.mode || "manual"}
        onChange={(e) => setRecurrence({ mode: e.target.value })}
      >
        <MenuItem value="manual">Manual assignment</MenuItem>
        <MenuItem value="recurring">Recurring</MenuItem>
      </TextField>
      <TextField
        size="small"
        type="number"
        label="Times per week"
        value={recurrence.weekly_frequency || 1}
        onChange={(e) => setRecurrence({ weekly_frequency: Number(e.target.value) || 1 })}
        inputProps={{ min: 1, max: 14 }}
      />
      <Typography variant="caption">Preferred days</Typography>
      <Stack direction="row" flexWrap="wrap" gap={0.5}>
        {DAYS.map((label, day) => {
          const selected = (recurrence.weekdays || []).includes(day);
          return (
            <Button
              key={label}
              size="small"
              variant={selected ? "contained" : "outlined"}
              onClick={() => {
                const current = new Set(recurrence.weekdays || []);
                if (current.has(day)) current.delete(day);
                else current.add(day);
                setRecurrence({ weekdays: [...current].sort((a, b) => a - b) });
              }}
            >
              {label}
            </Button>
          );
        })}
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          size="small"
          type="date"
          label="Effective start"
          InputLabelProps={{ shrink: true }}
          value={recurrence.effective_start || ""}
          onChange={(e) => setRecurrence({ effective_start: e.target.value || null })}
        />
        <TextField
          size="small"
          type="date"
          label="Effective end"
          InputLabelProps={{ shrink: true }}
          value={recurrence.effective_end || ""}
          onChange={(e) => setRecurrence({ effective_end: e.target.value || null })}
        />
        <TextField
          size="small"
          type="time"
          label="Start time"
          InputLabelProps={{ shrink: true }}
          value={recurrence.time_window?.start || ""}
          onChange={(e) =>
            setRecurrence({ time_window: { ...(recurrence.time_window || {}), start: e.target.value || null } })
          }
        />
      </Stack>
      <TextField
        select
        size="small"
        label="Assigned employees"
        SelectProps={{ multiple: true }}
        value={recurrence.assignee_user_ids || []}
        onChange={(e) =>
          setRecurrence({
            assignee_user_ids: (typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value).map(Number),
          })
        }
      >
        {assignees.map((person) => (
          <MenuItem key={person.user_id || person.id} value={Number(person.user_id || person.id)}>
            {person.name || person.full_name || person.username}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        size="small"
        label="Skip dates (YYYY-MM-DD, one per line)"
        multiline
        minRows={2}
        value={(recurrence.temporary_exceptions || []).map((item) => item.date).filter(Boolean).join("\n")}
        onChange={(e) =>
          setRecurrence({
            temporary_exceptions: e.target.value
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
              .map((date) => ({ date, reason: "Skipped by management" })),
          })
        }
        helperText="These dates are not generated. Completed work is kept."
      />
      <FormControlLabel
        control={
          <Switch checked={!recurrence.paused} onChange={(e) => setRecurrence({ paused: !e.target.checked })} />
        }
        label={recurrence.paused ? "Paused" : "Active schedule"}
      />
      <Button size="small" variant="outlined" disabled={busy || !onReconcile} onClick={onReconcile}>
        Reconcile occurrences
      </Button>
    </>
  );
}
