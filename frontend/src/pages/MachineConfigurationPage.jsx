import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { getMachineConfiguration, updateMachineConfiguration } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

function RackTable({ title, rows, draft, onChange, onAdd }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        mb: 2,
      }}
    >
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1" fontWeight={800}>{title}</Typography>
        <Button size="small" variant="outlined" onClick={onAdd} sx={{ textTransform: "none" }}>
          Add rack
        </Button>
      </Stack>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
              <TableCell>Rack code</TableCell>
              <TableCell>Capacity (lb)</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((code) => (
              <TableRow key={code}>
                <TableCell sx={{ fontWeight: 600 }}>{code}</TableCell>
                <TableCell>
                  <TextField
                    size="small"
                    type="number"
                    value={draft[code] ?? ""}
                    onChange={(e) => onChange(code, e.target.value)}
                    inputProps={{ min: 0, step: 0.5 }}
                    sx={{ maxWidth: 120 }}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default function MachineConfigurationPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [washerDraft, setWasherDraft] = useState({});
  const [dryerDraft, setDryerDraft] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getMachineConfiguration();
      setWasherDraft(res.data?.washers || {});
      setDryerDraft(res.data?.dryers || {});
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load machine configuration");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const washerCodes = Object.keys(washerDraft).sort((a, b) => a.localeCompare(b));
  const dryerCodes = Object.keys(dryerDraft).sort((a, b) => a.localeCompare(b));

  const addWasher = () => {
    const code = prompt("Washer rack code (e.g. W24-30-VW)");
    if (!code?.trim()) return;
    const trimmed = code.trim();
    setWasherDraft((prev) => ({ ...prev, [trimmed]: prev[trimmed] ?? 30 }));
  };

  const addDryer = () => {
    const code = prompt("Dryer rack code (e.g. D4-50-VW)");
    if (!code?.trim()) return;
    const trimmed = code.trim();
    setDryerDraft((prev) => ({ ...prev, [trimmed]: prev[trimmed] ?? 35 }));
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const res = await updateMachineConfiguration({ washers: washerDraft, dryers: dryerDraft });
      setWasherDraft(res.data?.washers || {});
      setDryerDraft(res.data?.dryers || {});
      setMessage(t("machineConfig.saved"));
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 900, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <VeeWashLogo height={28} />
        <Typography variant="h5" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
          {t("machineConfig.title")}
        </Typography>
      </Stack>

      <Button
        size="small"
        component={RouterLink}
        to="/maintenance"
        sx={{ mb: 2, textTransform: "none", fontWeight: 600 }}
      >
        Maintenance
      </Button>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t("machineConfig.subtitle")}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {message ? (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <RackTable
            title={t("machineConfig.washers")}
            rows={washerCodes}
            draft={washerDraft}
            onChange={(code, val) => setWasherDraft((prev) => ({ ...prev, [code]: val }))}
            onAdd={addWasher}
          />
          <RackTable
            title={t("machineConfig.dryers")}
            rows={dryerCodes}
            draft={dryerDraft}
            onChange={(code, val) => setDryerDraft((prev) => ({ ...prev, [code]: val }))}
            onAdd={addDryer}
          />
          <Button
            variant="contained"
            disabled={saving}
            onClick={save}
            sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, textTransform: "none", fontWeight: 700 }}
          >
            {saving ? t("machineConfig.saving") : t("machineConfig.save")}
          </Button>
        </>
      )}
    </Box>
  );
}
