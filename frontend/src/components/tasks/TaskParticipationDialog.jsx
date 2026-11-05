import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

function blankSession(day) {
  return { startDate: day || "", startTime: "09:00", endDate: day || "", endTime: "09:30" };
}

function stamp(day, time) {
  if (!day || !time) return null;
  const clock = time.length === 5 ? `${time}:00` : time;
  return `${day} ${clock}`;
}

/**
 * Supervisor time correction for one assigned employee.
 * Checklist check-offs are not changed.
 */
export default function TaskParticipationDialog({ open, row, contribution, onClose, onSubmit, busy = false, endOpenSession = false }) {
  const { t } = useI18n();
  const day = String(row?.business_date || "").slice(0, 10);
  const [status, setStatus] = useState("finished");
  const [sessions, setSessions] = useState([blankSession(day)]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) return;
    const existing = contribution?.activity?.participation_sessions;
    const recordedStart = contribution?.activity?.started_at;
    const recordedEnd = contribution?.activity?.ended_at;
    const part = endOpenSession ? "finished" : contribution?.participation_status || "not_started";
    setStatus(part === "finished" || part === "in_progress" || part === "not_started" ? part : "not_started");
    if (Array.isArray(existing) && existing.length) {
      setSessions(
        existing.map((session, index) => ({
          startDate: String(session.started_at || "").slice(0, 10) || day,
          startTime: String(session.started_at || "").slice(11, 16) || "09:00",
          endDate: session.ended_at ? String(session.ended_at).slice(0, 10) : day,
          endTime: endOpenSession && index === existing.length - 1 && !session.ended_at
            ? ""
            : session.ended_at
              ? String(session.ended_at).slice(11, 16)
              : "",
        })),
      );
    } else if (recordedStart) {
      setSessions([
        {
          startDate: String(recordedStart).slice(0, 10) || day,
          startTime: String(recordedStart).slice(11, 16),
          endDate: recordedEnd ? String(recordedEnd).slice(0, 10) : day,
          endTime: endOpenSession && !recordedEnd ? "" : recordedEnd ? String(recordedEnd).slice(11, 16) : "",
        },
      ]);
    } else {
      setSessions([blankSession(day)]);
    }
    setReason("");
  }, [open, contribution, day, endOpenSession]);

  const updateSession = (index, field, value) => {
    setSessions((current) => current.map((session, at) => (at === index ? { ...session, [field]: value } : session)));
  };

  const submit = () => {
    const payloadSessions =
      status === "not_started"
        ? []
        : sessions.map((session, index) => {
            const last = index === sessions.length - 1;
            const openEnded = status === "in_progress" && last;
            return {
              started_at: stamp(session.startDate, session.startTime),
              ended_at: openEnded ? null : stamp(session.endDate, session.endTime),
            };
          });
    onSubmit?.({
      responsibility_id: contribution?.responsibility_id,
      employee_user_id: contribution?.employee_id,
      activity_id: contribution?.activity?.id || null,
      business_date: day,
      participation_status: status,
      sessions: payloadSessions,
      reason: reason.trim(),
    });
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("tasks.dashboard.editParticipation")}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          <Typography variant="body2">
            {contribution?.employee_name || ""} · {row?.role_label || row?.role || ""}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t("tasks.dashboard.participationTimeOnly")}
          </Typography>
          <TextField
            select
            size="small"
            label={t("tasks.dashboard.participationStatus")}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <MenuItem value="not_started">{t("tasks.pin.status.not_started")}</MenuItem>
            <MenuItem value="in_progress">{t("tasks.pin.status.in_progress")}</MenuItem>
            <MenuItem value="finished">{t("tasks.dashboard.finished")}</MenuItem>
          </TextField>
          {status === "not_started"
            ? null
            : sessions.map((session, index) => (
                <Stack key={index} direction={{ xs: "column", sm: "row" }} spacing={1}>
                  <TextField
                    size="small"
                    type="date"
                    label={t("tasks.dashboard.sessionStart")}
                    value={session.startDate}
                    onChange={(event) => updateSession(index, "startDate", event.target.value)}
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    size="small"
                    type="time"
                    value={session.startTime}
                    onChange={(event) => updateSession(index, "startTime", event.target.value)}
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    size="small"
                    type="date"
                    label={t("tasks.dashboard.sessionEnd")}
                    value={session.endDate}
                    onChange={(event) => updateSession(index, "endDate", event.target.value)}
                    InputLabelProps={{ shrink: true }}
                    disabled={status === "in_progress" && index === sessions.length - 1}
                  />
                  <TextField
                    size="small"
                    type="time"
                    value={session.endTime}
                    onChange={(event) => updateSession(index, "endTime", event.target.value)}
                    InputLabelProps={{ shrink: true }}
                    disabled={status === "in_progress" && index === sessions.length - 1}
                  />
                  {sessions.length > 1 ? (
                    <Button
                      size="small"
                      color="inherit"
                      onClick={() => setSessions((current) => current.filter((_, at) => at !== index))}
                    >
                      {t("tasks.dashboard.removeSession")}
                    </Button>
                  ) : null}
                </Stack>
              ))}
          {status === "not_started" ? null : (
            <Button size="small" onClick={() => setSessions((current) => [...current, blankSession(day)])}>
              {t("tasks.dashboard.addSession")}
            </Button>
          )}
          <TextField
            size="small"
            required
            label={t("tasks.dashboard.participationReason")}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button variant="contained" onClick={submit} disabled={busy || reason.trim().length < 3}>
          {t("common.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
