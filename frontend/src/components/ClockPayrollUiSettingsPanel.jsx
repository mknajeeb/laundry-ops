import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getClockPayrollUiSettings, putClockPayrollUiSettings } from "../api";

export const DEFAULT_CLOCK_PAYROLL_UI = {
  clock: {
    outside_geofence_label_enabled: true,
    outside_geofence_label_text: "You are outside the designated work area.",
    clock_banner_enabled: false,
    clock_banner_text: "",
    show_outside_geofence_on_clock: true,
    show_outside_geofence_on_summary: true,
    ask_personal_laundry_bags: false,
    est_midnight_force_clock_out: true,
    clock_in_gate_enabled: true,
    clock_in_gate_strict: false,
    dim_app_until_clocked_in: false,
    sign_out_after_clock_out: false,
    shared_device_attendance: false,
    kiosk_idle_lock_enabled: true,
    kiosk_idle_lock_seconds: 30,
    clock_out_require_inside_geofence: true,
    geofence_reminder_enabled: true,
    geofence_reminder_hours: 1.5,
    geofence_reminder_cooldown_hours: 6,
  },
  payroll: {
    nav_payroll_visible: true,
    tab_live: true,
    tab_maintenance: true,
    tab_period: true,
    tab_clock_ui: true,
    monitor_show_cycle_filter: true,
    monitor_show_user_filter: true,
    monitor_show_apply: true,
    monitor_col_id: true,
    monitor_col_user: true,
    monitor_col_cycle: true,
    monitor_col_clock_in: true,
    monitor_col_clock_out: true,
    monitor_col_net: true,
    monitor_col_status: true,
    monitor_col_geofence: true,
    monitor_col_gross: true,
    monitor_col_breaks: true,
    monitor_col_geofence_out: true,
    monitor_col_bags: true,
    monitor_col_period_adj: true,
    monitor_col_actions: true,
  },
};

/**
 * Clock / payroll UI visibility (saved to system_settings via PUT /api/ta/admin/clock-payroll-ui).
 */
export default function ClockPayrollUiSettingsPanel() {
  const [clockPayrollUi, setClockPayrollUi] = useState(DEFAULT_CLOCK_PAYROLL_UI);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  useEffect(() => {
    getClockPayrollUiSettings()
      .then((res) => {
        const d = res.data;
        if (!d?.clock || !d?.payroll) return;
        setClockPayrollUi({
          clock: { ...DEFAULT_CLOCK_PAYROLL_UI.clock, ...d.clock },
          payroll: { ...DEFAULT_CLOCK_PAYROLL_UI.payroll, ...d.payroll },
        });
      })
      .catch(() => {});
  }, []);

  const saveClockPayrollUi = async () => {
    try {
      setSaving(true);
      setMessage({ type: "", text: "" });
      await putClockPayrollUiSettings(clockPayrollUi);
      setMessage({ type: "success", text: "Clock / payroll UI settings saved." });
    } catch (e) {
      console.error(e);
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Save failed (need ta.settings permission).",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Paper sx={{ p: { xs: 1.5, md: 2 }, borderRadius: 2 }}>
      <Typography sx={{ fontSize: 20, mb: 1 }}>Clock (PWA) & payroll screens</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Control geofence warnings, optional banner, checkout prompts, clock-in gate, push reminders to
        clock in when inside the geofence, and which payroll management tabs and columns employees see.
      </Typography>
      {message.text ? (
        <Alert severity={message.type === "error" ? "error" : "success"} sx={{ mb: 2 }} onClose={() => setMessage({ type: "", text: "" })}>
          {message.text}
        </Alert>
      ) : null}

      <Typography fontWeight={600} sx={{ mb: 1 }}>
        Time clock (mobile)
      </Typography>
      <Stack spacing={1} sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.outside_geofence_label_enabled}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, outside_geofence_label_enabled: e.target.checked },
                }))
              }
            />
          }
          label="Show red alert when outside geofence (while clocked in)"
        />
        <TextField
          fullWidth
          label="Outside geofence message"
          value={clockPayrollUi.clock.outside_geofence_label_text}
          onChange={(e) =>
            setClockPayrollUi((p) => ({
              ...p,
              clock: { ...p.clock, outside_geofence_label_text: e.target.value },
            }))
          }
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.clock_banner_enabled}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, clock_banner_enabled: e.target.checked },
                }))
              }
            />
          }
          label="Show info banner on clock screen"
        />
        <TextField
          fullWidth
          label="Banner message (all clock users; empty uses default)"
          value={clockPayrollUi.clock.clock_banner_text}
          onChange={(e) =>
            setClockPayrollUi((p) => ({
              ...p,
              clock: { ...p.clock, clock_banner_text: e.target.value },
            }))
          }
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.show_outside_geofence_on_clock}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, show_outside_geofence_on_clock: e.target.checked },
                }))
              }
            />
          }
          label="Show accumulated outside-geofence time on clock (while in session)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.show_outside_geofence_on_summary}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, show_outside_geofence_on_summary: e.target.checked },
                }))
              }
            />
          }
          label="Show outside-geofence time on clock-out confirmation & recap"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.ask_personal_laundry_bags}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, ask_personal_laundry_bags: e.target.checked },
                }))
              }
            />
          }
          label="Ask personal laundry bag count on first clock-in each day (Eastern; not asked on later same-day clock-ins)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.est_midnight_force_clock_out !== false}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, est_midnight_force_clock_out: e.target.checked },
                }))
              }
            />
          }
          label="Auto clock-out at Eastern midnight if still clocked in (disable to override for special cases)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.clock_in_gate_enabled}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, clock_in_gate_enabled: e.target.checked },
                }))
              }
            />
          }
          label="Require clock-in before using other app screens (non-admin, non-payroll-managers)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={!!clockPayrollUi.clock.clock_in_gate_strict}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, clock_in_gate_strict: e.target.checked },
                }))
              }
            />
          }
          label="Strict clock gate: no role bypass — anyone with time-clock permission must be clocked in to leave /clock"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={!!clockPayrollUi.clock.dim_app_until_clocked_in}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, dim_app_until_clocked_in: e.target.checked },
                }))
              }
            />
          }
          label="Dim the clock screen slightly until the user clocks in (visual emphasis on clock-in)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={!!clockPayrollUi.clock.sign_out_after_clock_out}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, sign_out_after_clock_out: e.target.checked },
                }))
              }
            />
          }
          label="After clock out, sign the user out of the app (return to login)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={!!clockPayrollUi.clock.shared_device_attendance}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, shared_device_attendance: e.target.checked },
                }))
              }
            />
          }
          label="Shared tablet / PC attendance: allow clock in/out without GPS; after each clock in or out, lock the app with the PIN lock screen so the next employee unlocks with their payroll attendance PIN (tenant admins stay signed in)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.kiosk_idle_lock_enabled !== false}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, kiosk_idle_lock_enabled: e.target.checked },
                }))
              }
            />
          }
          label="Auto-lock shared tablet after idle (no taps or keys); uses interval below when shared-tablet mode is on"
        />
        <TextField
          label="Idle lock timeout (seconds)"
          type="number"
          size="small"
          inputProps={{ min: 0, max: 3600, step: 5 }}
          value={Number(clockPayrollUi.clock.kiosk_idle_lock_seconds ?? 30)}
          onChange={(e) =>
            setClockPayrollUi((p) => ({
              ...p,
              clock: {
                ...p.clock,
                kiosk_idle_lock_seconds: Math.max(
                  0,
                  Math.min(3600, Math.floor(Number(e.target.value) || 0)),
                ),
              },
            }))
          }
          helperText="Default 30. Use 0 to disable auto-lock only (manual Lock button still works when shared-tablet mode is on)."
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={!!clockPayrollUi.clock.clock_out_require_inside_geofence}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, clock_out_require_inside_geofence: e.target.checked },
                }))
              }
            />
          }
          label="Require user to be inside the primary geofence to clock out (uses GPS from the device)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.clock.geofence_reminder_enabled}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, geofence_reminder_enabled: e.target.checked },
                }))
              }
            />
          }
          label="Send push reminder to clock in when inside geofence without clocking in (after delay)"
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Reminder after (hours)"
            type="number"
            inputProps={{ min: 0.25, max: 24, step: 0.25 }}
            value={clockPayrollUi.clock.geofence_reminder_hours}
            onChange={(e) => {
              const v = Number.parseFloat(e.target.value);
              setClockPayrollUi((p) => ({
                ...p,
                clock: {
                  ...p.clock,
                  geofence_reminder_hours: Number.isFinite(v) ? v : p.clock.geofence_reminder_hours,
                },
              }));
            }}
            sx={{ maxWidth: 220 }}
          />
          <TextField
            label="Cooldown between reminders (hours)"
            type="number"
            inputProps={{ min: 0.5, max: 72, step: 0.5 }}
            value={clockPayrollUi.clock.geofence_reminder_cooldown_hours}
            onChange={(e) => {
              const v = Number.parseFloat(e.target.value);
              setClockPayrollUi((p) => ({
                ...p,
                clock: {
                  ...p.clock,
                  geofence_reminder_cooldown_hours: Number.isFinite(v)
                    ? v
                    : p.clock.geofence_reminder_cooldown_hours,
                },
              }));
            }}
            sx={{ maxWidth: 280 }}
          />
        </Stack>
      </Stack>

      <Typography fontWeight={600} sx={{ mb: 1 }}>
        Payroll management screen
      </Typography>
      <Stack spacing={0.5} sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.nav_payroll_visible}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, nav_payroll_visible: e.target.checked },
                }))
              }
            />
          }
          label="Show Payroll management in sidebar"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.tab_clock_ui}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, tab_clock_ui: e.target.checked },
                }))
              }
            />
          }
          label="Tab: Clock & payroll UI settings"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.tab_live}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, tab_live: e.target.checked },
                }))
              }
            />
          }
          label="Tab: Live sessions"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.tab_maintenance}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, tab_maintenance: e.target.checked },
                }))
              }
            />
          }
          label="Tab: Attendance / setup"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.tab_period}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, tab_period: e.target.checked },
                }))
              }
            />
          }
          label="Tab: Pay period"
        />
        <Typography sx={{ mt: 1, fontWeight: 600 }}>Live monitor — filters</Typography>
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.monitor_show_cycle_filter}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, monitor_show_cycle_filter: e.target.checked },
                }))
              }
            />
          }
          label="Cycle filter"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.monitor_show_user_filter}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, monitor_show_user_filter: e.target.checked },
                }))
              }
            />
          }
          label="User filter"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={clockPayrollUi.payroll.monitor_show_apply}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  payroll: { ...p.payroll, monitor_show_apply: e.target.checked },
                }))
              }
            />
          }
          label="Apply button"
        />
        <Typography sx={{ mt: 1, fontWeight: 600 }}>Live monitor — table columns</Typography>
        {[
          ["monitor_col_id", "ID"],
          ["monitor_col_user", "User"],
          ["monitor_col_cycle", "Cycle"],
          ["monitor_col_clock_in", "Clock in"],
          ["monitor_col_clock_out", "Clock out"],
          ["monitor_col_gross", "Gross time"],
          ["monitor_col_breaks", "Breaks (total + detail)"],
          ["monitor_col_net", "Net seconds"],
          ["monitor_col_status", "Status"],
          ["monitor_col_geofence", "Geofence"],
          ["monitor_col_geofence_out", "Outside geofence"],
          ["monitor_col_bags", "Laundry bags / deduction"],
          ["monitor_col_period_adj", "Period bonus / deduction"],
          ["monitor_col_actions", "Actions"],
        ].map(([colKey, label]) => (
          <FormControlLabel
            key={colKey}
            control={
              <Checkbox
                checked={clockPayrollUi.payroll[colKey]}
                onChange={(e) =>
                  setClockPayrollUi((p) => ({
                    ...p,
                    payroll: { ...p.payroll, [colKey]: e.target.checked },
                  }))
                }
              />
            }
            label={label}
          />
        ))}
      </Stack>
      <Button variant="contained" onClick={saveClockPayrollUi} disabled={saving}>
        {saving ? "Saving…" : "Save clock / payroll UI"}
      </Button>
    </Paper>
  );
}
