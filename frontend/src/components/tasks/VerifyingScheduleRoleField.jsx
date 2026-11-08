import { MenuItem, TextField } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

export const SCHEDULE_ROLE_METHOD = "schedule_role";

export default function VerifyingScheduleRoleField({ method, value, roles = [], onChange }) {
  const { t } = useI18n();
  if (method !== SCHEDULE_ROLE_METHOD) return null;
  const choices = (roles || []).filter((role) => role.active !== false && role.code);
  return (
    <TextField
      select
      size="small"
      label={t("tasks.config.verifyingScheduleRole")}
      value={value || ""}
      onChange={(event) => onChange(event.target.value)}
      helperText={t("tasks.config.scheduleRoleHelp")}
    >
      {choices.map((role) => (
        <MenuItem key={role.code} value={role.code}>
          {role.name || role.code}
        </MenuItem>
      ))}
    </TextField>
  );
}
