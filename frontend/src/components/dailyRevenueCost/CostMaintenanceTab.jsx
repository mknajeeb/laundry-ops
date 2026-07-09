import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  Radio,
  RadioGroup,
  Stack,
  Typography,
} from "@mui/material";
import SaveIcon from "@mui/icons-material/Save";
import { getDrcCostSettings, updateDrcCostSettings } from "../../api";
import { CurrencyField, NumberField, SectionCard } from "./DrcShared";

const COST_FIELDS = [
  { key: "electricity_daily", label: "Electricity (daily)" },
  { key: "water_daily", label: "Water (daily)" },
  { key: "gas_daily", label: "Gas (daily)" },
  { key: "supplies_daily", label: "Supplies (daily)" },
  { key: "insurance_daily", label: "Insurance (daily)" },
  { key: "maintenance_daily", label: "Maintenance (daily)" },
  { key: "rent_daily", label: "Rent (daily)" },
  { key: "property_tax_daily", label: "Property Tax (daily)" },
  { key: "adjustments_daily", label: "Adjustments (daily)" },
];

export default function CostMaintenanceTab() {
  const [settings, setSettings] = useState({});
  const [taxMode, setTaxMode] = useState("percent");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getDrcCostSettings();
      const data = res.data || {};
      setSettings(data);
      setTaxMode(data.payroll_tax_daily_fixed != null && data.payroll_tax_daily_fixed > 0 ? "fixed" : "percent");
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updateField = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const body = {
        ...settings,
        payroll_tax_pct: taxMode === "percent" ? Number(settings.payroll_tax_pct) || 0 : null,
        payroll_tax_daily_fixed: taxMode === "fixed" ? Number(settings.payroll_tax_daily_fixed) || 0 : null,
      };
      COST_FIELDS.forEach(({ key }) => {
        body[key] = Number(settings[key]) || 0;
      });
      await updateDrcCostSettings(body);
      setSuccess("Cost settings saved");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {success ? <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert> : null}

      <SectionCard title="Payroll Tax Estimate">
        <RadioGroup value={taxMode} onChange={(e) => setTaxMode(e.target.value)} sx={{ mb: 2 }}>
          <FormControlLabel value="percent" control={<Radio />} label="Percentage of daily payroll" />
          <FormControlLabel value="fixed" control={<Radio />} label="Fixed daily payroll tax amount" />
        </RadioGroup>
        {taxMode === "percent" ? (
          <NumberField
            label="Payroll Tax %"
            value={settings.payroll_tax_pct ?? ""}
            onChange={(e) => updateField("payroll_tax_pct", e.target.value)}
          />
        ) : (
          <CurrencyField
            label="Daily Payroll Tax (fixed)"
            value={settings.payroll_tax_daily_fixed ?? ""}
            onChange={(e) => updateField("payroll_tax_daily_fixed", e.target.value)}
          />
        )}
      </SectionCard>

      <SectionCard title="Daily Operating Cost Estimates" subtitle="Saves as a new effective-dated schedule — history is preserved.">
        <Stack spacing={2}>
          {COST_FIELDS.map(({ key, label }) => (
            <CurrencyField
              key={key}
              label={label}
              value={settings[key] ?? ""}
              onChange={(e) => updateField(key, e.target.value)}
            />
          ))}
        </Stack>
      </SectionCard>

      <Button variant="contained" size="large" startIcon={<SaveIcon />} onClick={handleSave} disabled={saving} fullWidth>
        {saving ? "Saving…" : "Save Cost Settings"}
      </Button>
    </Box>
  );
}
