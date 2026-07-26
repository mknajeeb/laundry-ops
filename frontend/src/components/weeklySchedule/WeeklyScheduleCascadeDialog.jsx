import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { formatWeekRange, shiftWeek } from "./weeklyScheduleDates";

export default function WeeklyScheduleCascadeDialog({
  open,
  onClose,
  onConfirm,
  sourceWeekStart,
  saving = false,
}) {
  const [targetWeekStart, setTargetWeekStart] = useState(() =>
    sourceWeekStart ? shiftWeek(sourceWeekStart, 1) : "",
  );
  const [replace, setReplace] = useState(true);

  useEffect(() => {
    if (!open || !sourceWeekStart) return;
    setTargetWeekStart(shiftWeek(sourceWeekStart, 1));
    setReplace(true);
  }, [open, sourceWeekStart]);

  const sameWeek = Boolean(sourceWeekStart && targetWeekStart && sourceWeekStart === targetWeekStart);

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontWeight: 800, pb: 1 }}>Cascade week schedule</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            Copy every shift and exclusion from the source week onto another week. Use this when next
            week was seeded too early, or when you want to push the current schedule forward.
          </Typography>

          <Stack spacing={0.5}>
            <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: "0.06em" }}>
              SOURCE WEEK
            </Typography>
            <Typography variant="body2" sx={{ fontWeight: 700 }}>
              {sourceWeekStart ? formatWeekRange(sourceWeekStart) : "—"}
            </Typography>
          </Stack>

          <Stack spacing={0.5}>
            <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: "0.06em" }}>
              TARGET WEEK
            </Typography>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <IconButton
                size="small"
                disabled={saving}
                onClick={() => setTargetWeekStart((prev) => shiftWeek(prev || sourceWeekStart, -1))}
              >
                <ChevronLeftIcon fontSize="small" />
              </IconButton>
              <Typography variant="body2" sx={{ fontWeight: 700, minWidth: 190, textAlign: "center" }}>
                {targetWeekStart ? formatWeekRange(targetWeekStart) : "—"}
              </Typography>
              <IconButton
                size="small"
                disabled={saving}
                onClick={() => setTargetWeekStart((prev) => shiftWeek(prev || sourceWeekStart, 1))}
              >
                <ChevronRightIcon fontSize="small" />
              </IconButton>
            </Stack>
          </Stack>

          <FormControlLabel
            control={
              <Switch
                checked={replace}
                onChange={(e) => setReplace(e.target.checked)}
                disabled={saving}
              />
            }
            label="Replace existing shifts on the target week"
          />

          {sameWeek ? (
            <Alert severity="warning">Source and target weeks must be different.</Alert>
          ) : replace ? (
            <Alert severity="warning">
              Existing shifts on {targetWeekStart ? formatWeekRange(targetWeekStart) : "the target week"}{" "}
              will be deleted and replaced.
            </Alert>
          ) : (
            <Alert severity="info">
              If the target week already has shifts, the cascade will be blocked unless replace is on.
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={saving || !sourceWeekStart || !targetWeekStart || sameWeek}
          onClick={() => onConfirm({ targetWeekStart, replace })}
        >
          {saving ? "Cascading…" : "Cascade schedule"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
