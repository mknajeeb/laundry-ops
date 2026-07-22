import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import {
  getCategoryRoleTrackingFeatureFlag,
  putCategoryRoleTrackingFeatureFlag,
} from "../api";

/**
 * Payroll Management control for enabling Category & Role Tracking.
 */
export default function CategoryRoleTrackingSettingsPanel({ onChanged }) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getCategoryRoleTrackingFeatureFlag();
      setEnabled(!!res.data?.category_role_tracking_enabled);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load setting");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onToggle = async (next) => {
    setSaving(true);
    setError("");
    setInfo("");
    try {
      const res = await putCategoryRoleTrackingFeatureFlag({
        category_role_tracking_enabled: next,
      });
      setEnabled(!!res.data?.category_role_tracking_enabled);
      if (next) {
        setInfo(
          "When enabled, employees will be required to select a Category and Role during shared-register check-in."
        );
      } else {
        const closed = res.data?.open_segments_closed ?? 0;
        setInfo(
          `Disabling this feature stops new category and role tracking. Existing task history will be preserved.${
            closed ? ` Closed ${closed} open assignment(s).` : ""
          }`
        );
      }
      if (typeof onChanged === "function") onChanged(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not save setting");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2.5, mb: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="h6" fontWeight={800}>
          Employee Category & Role Tracking
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Requires employees to select a work category and role when checking in and allows them
          to change assignments during an active shift. Disable this setting to use the existing
          attendance workflow without category or role tracking.
        </Typography>
        {error ? <Alert severity="error">{error}</Alert> : null}
        {info ? <Alert severity="warning">{info}</Alert> : null}
        <FormControlLabel
          control={
            <Switch
              checked={enabled}
              disabled={loading || saving}
              onChange={(e) => onToggle(e.target.checked)}
            />
          }
          label="Enable Category & Role Tracking"
        />
        {!enabled && !loading ? (
          <Alert severity="info">
            Category & Role Tracking is currently disabled. Changes in Categories & Roles
            maintenance will become available when the feature is enabled.
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );
}
