import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Radio,
  RadioGroup,
  Stack,
  Typography,
} from "@mui/material";
import { getWeeklyScheduleFutureWeeks } from "../../api";
import { currentWeekStart, formatWeekRange } from "./weeklyScheduleDates";

const MODE = { TEMPLATE: "template", SELECTED: "selected" };

const STATUS_LABELS = {
  replaced: { label: "Replaced", color: "warning" },
  created: { label: "Created", color: "success" },
  cleared: { label: "Cleared", color: "default" },
  unchanged: { label: "Unchanged", color: "default" },
};

function ResultList({ result }) {
  const weeks = result?.weeks || [];
  if (result?.disabled) {
    return (
      <Alert severity="info">
        Ongoing template stopped. Later weeks keep their current planned assignments and no longer follow changes.
      </Alert>
    );
  }
  return (
    <Stack spacing={1}>
      <Alert severity="success">
        {result?.mode === MODE.TEMPLATE
          ? `Template is on. ${weeks.length} existing later week${weeks.length === 1 ? "" : "s"} synced; weeks opened later will follow it automatically.`
          : `Copied to ${weeks.length} week${weeks.length === 1 ? "" : "s"}. Later changes to this week will not be copied.`}
        {result?.template_stopped
          ? ` The ongoing template from the week of ${formatWeekRange(result.template_stopped)} was stopped.`
          : ""}
      </Alert>
      {weeks.map((week) => {
        const status = STATUS_LABELS[week.status] || STATUS_LABELS.unchanged;
        return (
          <Stack key={week.week_start} direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={700} sx={{ minWidth: 170 }}>
              {formatWeekRange(week.week_start)}
            </Typography>
            <Chip size="small" label={status.label} color={status.color} />
            <Typography variant="caption" color="text.secondary">
              {week.shifts_copied} shift{week.shifts_copied === 1 ? "" : "s"}, {week.tasks_copied} task
              {week.tasks_copied === 1 ? "" : "s"}
              {week.shifts_removed || week.tasks_removed
                ? ` (removed ${week.shifts_removed} shift${week.shifts_removed === 1 ? "" : "s"}, ${week.tasks_removed} task${week.tasks_removed === 1 ? "" : "s"})`
                : ""}
            </Typography>
          </Stack>
        );
      })}
      <Typography variant="caption" color="text.secondary">
        Planned weekly schedules have no separate publish step — every synced week is live for employees right away.
      </Typography>
    </Stack>
  );
}

export default function WeeklyScheduleCascadeDialog({
  open,
  onClose,
  sourceWeekStart,
  template = null,
  onEnableTemplate,
  onCopySelected,
  onStopTemplate,
}) {
  const [mode, setMode] = useState(MODE.TEMPLATE);
  const [weeks, setWeeks] = useState([]);
  const [selected, setSelected] = useState([]);
  const [loadingWeeks, setLoadingWeeks] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const isPastWeek = Boolean(sourceWeekStart) && sourceWeekStart < currentWeekStart();
  const templateIsThisWeek = Boolean(template?.enabled && template?.source_week_start === sourceWeekStart);

  useEffect(() => {
    if (!open || !sourceWeekStart) return;
    setMode(isPastWeek ? MODE.SELECTED : MODE.TEMPLATE);
    setSelected([]);
    setError("");
    setResult(null);
    setLoadingWeeks(true);
    getWeeklyScheduleFutureWeeks(sourceWeekStart)
      .then((res) => setWeeks(res.data?.weeks || []))
      .catch((e) => setError(e?.response?.data?.error || "Failed to load future weeks"))
      .finally(() => setLoadingWeeks(false));
  }, [open, sourceWeekStart, isPastWeek]);

  const existingLater = useMemo(() => weeks.filter((w) => w.has_schedule), [weeks]);

  const toggleWeek = (weekStart) =>
    setSelected((prev) => (prev.includes(weekStart) ? prev.filter((w) => w !== weekStart) : [...prev, weekStart]));

  const run = async (action) => {
    setSaving(true);
    setError("");
    try {
      setResult(await action());
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update future weeks");
    } finally {
      setSaving(false);
    }
  };

  const canApply = mode === MODE.TEMPLATE ? !isPastWeek : selected.length > 0;

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontWeight: 800, pb: 1 }}>Copy to future weeks</DialogTitle>
      <DialogContent>
        {result ? (
          <ResultList result={result} />
        ) : (
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <Typography variant="body2">
              Source week: <strong>{sourceWeekStart ? formatWeekRange(sourceWeekStart) : "—"}</strong>
            </Typography>
            {template?.enabled ? (
              <Alert
                severity="info"
                action={
                  <Button color="inherit" size="small" disabled={saving} onClick={() => run(onStopTemplate)}>
                    Stop
                  </Button>
                }
              >
                Ongoing template: week of {formatWeekRange(template.source_week_start)}. Changes there propagate to all
                later weeks.
              </Alert>
            ) : null}

            <RadioGroup value={mode} onChange={(e) => setMode(e.target.value)}>
              <FormControlLabel
                value={MODE.TEMPLATE}
                disabled={isPastWeek || saving}
                control={<Radio size="small" />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={800}>
                      All upcoming schedules
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      Make this week the ongoing template. Every later week mirrors it by weekday, including weeks
                      created later. Additions, edits, and deletions here are copied automatically until you stop it or
                      use “Select future weeks”.
                    </Typography>
                  </Box>
                }
                sx={{ alignItems: "flex-start", mb: 1, "& .MuiRadio-root": { pt: 0.25 } }}
              />
              <FormControlLabel
                value={MODE.SELECTED}
                disabled={saving}
                control={<Radio size="small" />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={800}>
                      Select future weeks
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      One-time copy to the weeks you pick. Later changes to this week are not copied.
                    </Typography>
                  </Box>
                }
                sx={{ alignItems: "flex-start", "& .MuiRadio-root": { pt: 0.25 } }}
              />
            </RadioGroup>

            {isPastWeek ? (
              <Alert severity="info">A past week cannot become the ongoing template; pick weeks to copy it to instead.</Alert>
            ) : null}

            {mode === MODE.SELECTED ? (
              loadingWeeks ? (
                <Stack alignItems="center" py={2}>
                  <CircularProgress size={22} />
                </Stack>
              ) : (
                <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1.5, maxHeight: 260, overflow: "auto", px: 1 }}>
                  {weeks.map((week) => (
                    <FormControlLabel
                      key={week.week_start}
                      sx={{ display: "flex", m: 0 }}
                      control={
                        <Checkbox
                          size="small"
                          checked={selected.includes(week.week_start)}
                          onChange={() => toggleWeek(week.week_start)}
                          disabled={saving}
                        />
                      }
                      label={
                        <Typography variant="body2">
                          {formatWeekRange(week.week_start)}{" "}
                          <Typography component="span" variant="caption" color="text.secondary">
                            {week.has_schedule ? `— has ${week.shifts} shifts, ${week.tasks} tasks` : "— empty"}
                          </Typography>
                        </Typography>
                      }
                    />
                  ))}
                </Box>
              )
            ) : null}

            <Alert severity="warning">
              {mode === MODE.TEMPLATE
                ? `Planned shifts, role ranges, tasks, instructions, breaks, and exclusions on every week after this one will be replaced${
                    existingLater.length ? ` (${existingLater.length} existing week${existingLater.length === 1 ? "" : "s"} now)` : ""
                  }, and kept in sync from now on.`
                : "Planned shifts, role ranges, tasks, instructions, breaks, and exclusions on the selected weeks will be replaced."}{" "}
              This week, earlier weeks, attendance, and payroll are not changed.
            </Alert>
            {templateIsThisWeek && mode === MODE.TEMPLATE ? (
              <Alert severity="info">This week is already the ongoing template. Applying again re-syncs all later weeks.</Alert>
            ) : null}
            {error ? <Alert severity="error">{error}</Alert> : null}
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {result ? (
          <Button variant="contained" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button
              variant="contained"
              disabled={saving || !canApply}
              onClick={() =>
                run(() => (mode === MODE.TEMPLATE ? onEnableTemplate() : onCopySelected([...selected].sort())))
              }
            >
              {saving
                ? "Applying…"
                : mode === MODE.TEMPLATE
                  ? "Use as template for all upcoming weeks"
                  : `Replace ${selected.length || ""} selected week${selected.length === 1 ? "" : "s"}`}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
