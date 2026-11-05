import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

export default function TaskExcuseDialog({ open, row, contribution, busy, onClose, onSubmit }) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [action, setAction] = useState("excuse");
  const [replacement, setReplacement] = useState("");
  const others = (row?.contributions || []).filter(
    (person) => Number(person.employee_id) !== Number(contribution?.employee_id),
  );

  useEffect(() => {
    if (!open) return;
    setReason("");
    setAction("excuse");
    setReplacement(others[0] ? String(others[0].employee_id) : "");
  }, [open, contribution?.employee_id]);

  const assigned = (row?.contributions || []).map((person) => Number(person.employee_id)).filter((id) => id > 0);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("tasks.dashboard.excuseTitle")}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          <Typography variant="body2">{contribution?.employee_name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {t("tasks.dashboard.excuseHelp")}
          </Typography>
          <TextField
            select
            size="small"
            label={t("tasks.dashboard.excuse")}
            value={action}
            onChange={(e) => setAction(e.target.value)}
          >
            <MenuItem value="excuse">{t("tasks.dashboard.excuse")}</MenuItem>
            <MenuItem value="reassign">Reassign</MenuItem>
          </TextField>
          {action === "reassign" ? (
            <TextField select size="small" label="Replacement" value={replacement} onChange={(e) => setReplacement(e.target.value)}>
              {others.map((person) => (
                <MenuItem key={person.employee_id} value={String(person.employee_id)}>
                  {person.employee_name}
                </MenuItem>
              ))}
            </TextField>
          ) : null}
          <TextField
            size="small"
            label={t("tasks.dashboard.excuseReason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button
          variant="contained"
          disabled={busy || reason.trim().length < 3 || (action === "reassign" && !replacement)}
          onClick={() =>
            onSubmit?.({
              action,
              reason: reason.trim(),
              employee_user_id: contribution?.employee_id,
              replacement_user_id: action === "reassign" ? Number(replacement) : undefined,
              shared_session_id: row?.shared_session_id,
              assignment_group_id: row?.assignment_group_id,
              role: row?.role,
              business_date: row?.business_date,
              assigned_user_ids: assigned,
            })
          }
        >
          {t("common.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
