import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  Typography,
} from "@mui/material";
import { getWeeklyScheduleDisplaySettings, updateWeeklyScheduleDisplaySettings } from "../../api";

export default function WeeklyScheduleDisplaySettingsPanel() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getWeeklyScheduleDisplaySettings();
      setSettings(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load weekly schedule display settings");
      setSettings(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = (key) => {
    setSettings((prev) => ({ ...prev, [key]: !prev?.[key] }));
    setSuccess("");
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await updateWeeklyScheduleDisplaySettings(settings);
      setSettings(res.data);
      setSuccess("Weekly schedule display settings saved.");
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Typography variant="body2" color="text.secondary">Loading…</Typography>;
  }

  if (!settings) {
    return error ? <Alert severity="error">{error}</Alert> : null;
  }

  const toggles = [
    {
      key: "schedule_end_time_enabled",
      label: "Require shift end time (calculate hours)",
      hint: "When off, only a start time is required and shifts count by day instead of hours.",
    },
    {
      key: "show_estimated_cost_default",
      label: "Show estimated labor cost (admin view)",
      hint: "Default for managers viewing the weekly schedule.",
    },
    {
      key: "show_employee_rates_default",
      label: "Show hourly rates on cards",
      hint: "Display each employee's hourly rate on their row.",
    },
    {
      key: "share_cost_with_external",
      label: "Share estimated cost with external viewers",
      hint: "When sharing with Rinse or other partners, allow cost visibility.",
    },
    {
      key: "share_role_labels_with_external",
      label: "Share role labels with external viewers",
    },
    {
      key: "share_break_minutes_with_external",
      label: "Share break minutes with external viewers",
    },
    {
      key: "share_rates_with_external",
      label: "Share hourly rates with external viewers",
    },
  ];

  return (
    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 2 }}>
      <Stack spacing={2}>
        {error ? <Alert severity="error">{error}</Alert> : null}
        {success ? <Alert severity="success">{success}</Alert> : null}
        {toggles.map(({ key, label, hint }) => (
          <Box key={key}>
            <FormControlLabel
              control={
                <Switch
                  checked={Boolean(settings[key])}
                  onChange={() => handleToggle(key)}
                />
              }
              label={label}
            />
            {hint ? (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ pl: 4.5 }}>
                {hint}
              </Typography>
            ) : null}
          </Box>
        ))}
        <Box>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save display settings"}
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}
