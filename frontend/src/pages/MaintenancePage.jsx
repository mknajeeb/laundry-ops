import { useEffect, useState } from "react";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { getGeofenceConfig, saveGeofenceConfig } from "../api";

const HOME_TEST = {
  label: "Home Test",
  latitude: 40.77529131611636,
  longitude: -73.78703142952348,
  radius_m: 35,
};

const WORK_TEST = {
  label: "Work",
  latitude: 40.916371220597775,
  longitude: -73.90139465900863,
  radius_m: 35,
};

function MaintenancePage() {
  const [form, setForm] = useState({
    label: "Work",
    latitude: "",
    longitude: "",
    radius_m: "35",
    updated_by: "admin",
  });
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await getGeofenceConfig();
        const g = res?.data?.geofence;
        if (!g) return;

        setForm({
          label: g.label || "Work",
          latitude: String(g.latitude ?? ""),
          longitude: String(g.longitude ?? ""),
          radius_m: String(g.radius_m ?? "35"),
          updated_by: "admin",
        });
      } catch (error) {
        console.error(error);
        setMessage({ type: "warning", text: "No geofence yet or failed to load." });
      }
    }

    loadConfig();
  }, []);

  const setPreset = (preset) => {
    setForm((prev) => ({
      ...prev,
      label: preset.label,
      latitude: String(preset.latitude),
      longitude: String(preset.longitude),
      radius_m: String(preset.radius_m),
    }));
  };

  const save = async () => {
    try {
      setSaving(true);
      await saveGeofenceConfig({
        label: form.label,
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        radius_m: Number(form.radius_m),
        active: true,
        updated_by: form.updated_by || "admin",
      });

      setMessage({ type: "success", text: "Geofence saved and activated." });
    } catch (error) {
      console.error(error);
      setMessage({ type: "error", text: error?.response?.data?.error || "Save failed." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#ffffff", px: { xs: 1.2, md: 2 }, py: 1.2 }}>
      <Typography sx={{ fontSize: 26, fontWeight: 900 }}>Maintenance</Typography>
      <Typography sx={{ color: "#6b7280", mt: 0.3 }}>Geofence configuration</Typography>

      {message.text && (
        <Alert severity={message.type} sx={{ mt: 1.1 }}>
          {message.text}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 1.2, borderRadius: 2, border: "1px solid #e5e7eb", boxShadow: "none" }}>
        <Stack spacing={0.9}>
          <Stack direction="row" spacing={0.7}>
            <Button variant="outlined" onClick={() => setPreset(HOME_TEST)}>Use Home Test</Button>
            <Button variant="outlined" onClick={() => setPreset(WORK_TEST)}>Use Work</Button>
          </Stack>

          <TextField
            label="Label"
            size="small"
            value={form.label}
            onChange={(e) => setForm((prev) => ({ ...prev, label: e.target.value }))}
          />
          <TextField
            label="Latitude"
            size="small"
            value={form.latitude}
            onChange={(e) => setForm((prev) => ({ ...prev, latitude: e.target.value }))}
          />
          <TextField
            label="Longitude"
            size="small"
            value={form.longitude}
            onChange={(e) => setForm((prev) => ({ ...prev, longitude: e.target.value }))}
          />
          <TextField
            label="Radius (meters)"
            size="small"
            value={form.radius_m}
            onChange={(e) => setForm((prev) => ({ ...prev, radius_m: e.target.value }))}
          />

          <Button variant="contained" disabled={saving} onClick={save}>
            Save Geofence
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default MaintenancePage;
