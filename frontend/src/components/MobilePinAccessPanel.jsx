import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { getTaUserMobilePinAccess, putTaUserMobilePinAccess } from "../api";

/** Configurable Mobile PIN apps — Clock In/Out is org hub policy, not listed here. */
export const MOBILE_PIN_ACCESS_MODULES = [
  { key: "switch_role", label: "Role" },
  { key: "take_break", label: "Take a Break" },
  { key: "cleaning_tasks", label: "Tasks" },
  { key: "cleaning_task_review", label: "Task Review (supervisor)" },
  { key: "checklist", label: "End-of-Day Checklist" },
  { key: "inventory", label: "Inventory" },
  { key: "revenue_cost", label: "Revenue / Cash" },
  { key: "team_status", label: "Team Status" },
];

export const ISSUES_ACCESS_CHOICES = [
  { value: "inherited", label: "Inherited — role or Task Review" },
  { value: "allow", label: "Allow" },
  { value: "deny", label: "Deny" },
];

export function issuesAccessFromPayload(data = {}) {
  const mode = data.issues_access;
  if (mode === "inherited" || mode === "allow" || mode === "deny") return mode;
  return "inherited";
}

export function issuesAccessHelp(mode, effective) {
  if (mode === "allow") return "Explicit allow. This employee can open Issues.";
  if (mode === "deny") return "Explicit deny. The Issues tile stays hidden.";
  if (effective === true) {
    return "Inherited. Role or Task Review currently allows Issues. Saving other tiles keeps this inherited.";
  }
  if (effective === false) {
    return "Inherited. Role or Task Review currently hides Issues. Saving other tiles keeps this inherited.";
  }
  return "Inherited until an administrator chooses Allow or Deny.";
}

export function normalizeMobilePinAccess(data = {}) {
  return {
    switch_role: !!data.switch_role,
    take_break: !!data.take_break,
    cleaning_tasks: !!data.cleaning_tasks,
    cleaning_task_review: !!data.cleaning_task_review,
    checklist: !!data.checklist,
    inventory: !!data.inventory,
    revenue_cost: !!data.revenue_cost,
    team_status: !!data.team_status,
    issues_access: issuesAccessFromPayload(data),
    issues_effective:
      data.issues_effective === undefined || data.issues_effective === null
        ? null
        : !!data.issues_effective,
  };
}

export function mobilePinAccessSaveBody(values = {}) {
  const body = {
    switch_role: !!values.switch_role,
    take_break: !!values.take_break,
    cleaning_tasks: !!values.cleaning_tasks,
    cleaning_task_review: !!values.cleaning_task_review,
    checklist: !!values.checklist,
    inventory: !!values.inventory,
    revenue_cost: !!values.revenue_cost,
    team_status: !!values.team_status,
  };
  if (values.issues_access === "allow") body.issues = true;
  else if (values.issues_access === "deny") body.issues = false;
  else if (values.issues_access === "inherited") body.issues = null;
  return body;
}

const EMPTY = normalizeMobilePinAccess({});

/**
 * People → Employee → Mobile PIN Access
 * Module checkboxes only. Separate from Allowed Work Assignments.
 * Defaults: Role + Take a Break ON; other apps OFF.
 */
export default function MobilePinAccessPanel({ userId, canEdit = false }) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [values, setValues] = useState({ ...EMPTY });
  const [saved, setSaved] = useState({ ...EMPTY });
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const res = await getTaUserMobilePinAccess(userId);
      const next = normalizeMobilePinAccess(res.data || {});
      setValues(next);
      setSaved(next);
      setDirty(false);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load Mobile PIN Access");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (key, checked) => {
    setDirty(true);
    setMessage("");
    setValues((prev) => ({ ...prev, [key]: checked }));
  };

  const discard = () => {
    setValues({ ...saved });
    setDirty(false);
    setError("");
    setMessage("");
  };

  const save = async () => {
    if (!canEdit || !userId) return;
    setSaving(true);
    setError("");
    setMessage("");
    const body = mobilePinAccessSaveBody(values);
    try {
      const res = await putTaUserMobilePinAccess(userId, body);
      const next = normalizeMobilePinAccess(res.data || body);
      setValues(next);
      setSaved(next);
      setDirty(false);
      setMessage("Mobile PIN Access saved.");
    } catch (e) {
      // Keep local selections on failure.
      setError(e?.response?.data?.error || "Failed to save Mobile PIN Access");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ mt: 2, pt: 2, borderTop: "1px solid", borderColor: "divider" }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
        Mobile PIN Access
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Controls which apps appear on the mobile PIN launcher. Separate from Allowed Work
        Assignments and from Notifications → Assignments. Issues Module Access is its own
        choice: Inherited, Allow, or Deny. Saving the other tiles does not turn an inherited
        setting into an explicit denial. Clock In/Out follows shared attendance settings, not
        this list.
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}
      {message ? (
        <Alert severity="success" sx={{ mb: 1.5 }}>
          {message}
        </Alert>
      ) : null}

      {loading ? (
        <Typography variant="body2" color="text.secondary">
          Loading…
        </Typography>
      ) : (
        <Stack spacing={0.25}>
          {MOBILE_PIN_ACCESS_MODULES.map((m) => (
            <FormControlLabel
              key={m.key}
              control={
                <Checkbox
                  checked={!!values[m.key]}
                  onChange={(e) => toggle(m.key, e.target.checked)}
                  disabled={!canEdit || saving}
                  size="small"
                />
              }
              label={m.label}
            />
          ))}
          <FormControl size="small" sx={{ mt: 1, maxWidth: 420 }} disabled={!canEdit || saving}>
            <InputLabel id="issues-module-access-label">Issues Module Access</InputLabel>
            <Select
              labelId="issues-module-access-label"
              label="Issues Module Access"
              value={values.issues_access || "inherited"}
              onChange={(e) => toggle("issues_access", e.target.value)}
            >
              {ISSUES_ACCESS_CHOICES.map((choice) => (
                <MenuItem key={choice.value} value={choice.value}>
                  {choice.label}
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>
              {issuesAccessHelp(values.issues_access, values.issues_effective)}
            </FormHelperText>
          </FormControl>
        </Stack>
      )}

      {canEdit ? (
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
          <Button
            variant="contained"
            size="small"
            onClick={save}
            disabled={!dirty || saving || loading}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="outlined"
            size="small"
            onClick={discard}
            disabled={!dirty || saving || loading}
          >
            Cancel
          </Button>
        </Stack>
      ) : null}
    </Box>
  );
}
