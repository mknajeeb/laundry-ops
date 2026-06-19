import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { getMachineConfiguration, updateMachineConfiguration } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

function configToRows(map) {
  return Object.entries(map || {})
    .map(([code, capacity]) => ({ code, capacity }))
    .sort((a, b) => a.code.localeCompare(b.code));
}

function rowsToConfig(rows) {
  const out = {};
  for (const row of rows) {
    const code = String(row.code || "").trim();
    if (!code) continue;
    const cap = parseFloat(row.capacity);
    out[code] = Number.isFinite(cap) && cap > 0 ? cap : 1;
  }
  return out;
}

function RackTable({ title, rows, onChange, onAdd, onDelete, t }) {
  const updateRow = (index, patch) => {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const confirmDelete = (index) => {
    const code = rows[index]?.code || "";
    const msg = code
      ? t("machineConfig.deleteConfirm").replace("{code}", code)
      : t("machineConfig.deleteConfirmGeneric");
    if (window.confirm(msg)) {
      onDelete(index);
    }
  };

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
          {t("machineConfig.addRack")}
        </Button>
      </Stack>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
              <TableCell>{t("machineConfig.rackCode")}</TableCell>
              <TableCell>{t("machineConfig.capacityLb")}</TableCell>
              <TableCell align="right" sx={{ width: 56 }}>{t("common.actions")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={3} sx={{ color: "text.secondary", fontStyle: "italic" }}>
                  {t("machineConfig.noRacks")}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row, index) => (
                <TableRow key={`${index}-${row.code}`}>
                  <TableCell>
                    <TextField
                      size="small"
                      value={row.code}
                      onChange={(e) => updateRow(index, { code: e.target.value })}
                      placeholder="W24-30-VW"
                      sx={{ minWidth: 140 }}
                    />
                  </TableCell>
                  <TableCell>
                    <TextField
                      size="small"
                      type="number"
                      value={row.capacity ?? ""}
                      onChange={(e) => updateRow(index, { capacity: e.target.value })}
                      inputProps={{ min: 0, step: 0.5 }}
                      sx={{ maxWidth: 120 }}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={t("machineConfig.deleteRack")}>
                      <IconButton
                        size="small"
                        color="error"
                        aria-label={t("machineConfig.deleteRack")}
                        onClick={() => confirmDelete(index)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))
            )}
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
  const [washerRows, setWasherRows] = useState([]);
  const [dryerRows, setDryerRows] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getMachineConfiguration();
      setWasherRows(configToRows(res.data?.washers));
      setDryerRows(configToRows(res.data?.dryers));
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load machine configuration");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const addWasher = () => {
    setWasherRows((prev) => [...prev, { code: "", capacity: 30 }]);
  };

  const addDryer = () => {
    setDryerRows((prev) => [...prev, { code: "", capacity: 35 }]);
  };

  const save = async () => {
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const payload = {
        washers: rowsToConfig(washerRows),
        dryers: rowsToConfig(dryerRows),
      };
      const res = await updateMachineConfiguration(payload);
      setWasherRows(configToRows(res.data?.washers));
      setDryerRows(configToRows(res.data?.dryers));
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
            rows={washerRows}
            onChange={setWasherRows}
            onAdd={addWasher}
            onDelete={(index) => setWasherRows((prev) => prev.filter((_, i) => i !== index))}
            t={t}
          />
          <RackTable
            title={t("machineConfig.dryers")}
            rows={dryerRows}
            onChange={setDryerRows}
            onAdd={addDryer}
            onDelete={(index) => setDryerRows((prev) => prev.filter((_, i) => i !== index))}
            t={t}
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
