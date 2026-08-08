import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Stack,
  Typography,
} from "@mui/material";
import { getTaUserMobilePinAccess, putTaUserMobilePinAccess } from "../api";

export const MOBILE_PIN_ACCESS_MODULES = [
  { key: "clock", label: "Clock" },
  { key: "switch_role", label: "Role" },
  { key: "checklist", label: "End-of-Day Checklist" },
  { key: "inventory", label: "Inventory" },
  { key: "revenue_cost", label: "Revenue & Cost" },
];

export function normalizeMobilePinAccess(data = {}) {
  return {
    clock: !!data.clock,
    switch_role: !!data.switch_role,
    checklist: !!data.checklist,
    inventory: !!data.inventory,
    revenue_cost: !!data.revenue_cost,
  };
}

export function mobilePinAccessSaveBody(values = {}) {
  return normalizeMobilePinAccess(values);
}

const EMPTY = normalizeMobilePinAccess({});

/**
 * People → Employee → Mobile PIN Access
 * Five checkboxes only. Separate from Allowed Work Assignments.
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
        Assignments.
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
