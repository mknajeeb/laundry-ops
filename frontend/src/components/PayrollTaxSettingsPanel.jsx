import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getPayrollTaxSettings, putPayrollTaxSettings } from "../api";
import { ESTIMATE_DISCLAIMER, PAYROLL_ESTIMATE_PURPOSE } from "../payroll/payrollTaxMessages";

const FIELDS = [
  { key: "tax_year", label: "Tax year", type: "number" },
  { key: "employee_social_security_rate", label: "Employee SS rate (e.g. 0.062)" },
  { key: "employer_social_security_rate", label: "Employer SS rate" },
  { key: "social_security_wage_base", label: "SS wage base" },
  { key: "employee_medicare_rate", label: "Employee Medicare rate" },
  { key: "employer_medicare_rate", label: "Employer Medicare rate" },
  { key: "additional_medicare_rate", label: "Additional Medicare rate" },
  { key: "additional_medicare_threshold", label: "Additional Medicare threshold" },
  { key: "futa_rate", label: "FUTA rate" },
  { key: "futa_wage_base", label: "FUTA wage base" },
  { key: "ny_suta_rate", label: "NY SUTA rate" },
  { key: "ny_suta_wage_base", label: "NY SUTA wage base" },
  { key: "ny_reemployment_service_fund_rate", label: "NY re-employment fund rate" },
  { key: "nyc_mctmt_rate", label: "NYC MCTMT rate" },
  { key: "workers_comp_rate", label: "Workers comp rate (fraction of gross)" },
  { key: "federal_standard_deduction_single", label: "Federal std deduction — single" },
  { key: "federal_standard_deduction_mfj", label: "Federal std deduction — MFJ" },
  { key: "federal_standard_deduction_hoh", label: "Federal std deduction — HoH" },
  { key: "ny_withholding_estimate_rate", label: "NY withholding estimate rate" },
  { key: "nyc_resident_estimate_rate", label: "NYC resident estimate rate" },
  { key: "nyc_nonresident_estimate_rate", label: "NYC non-resident estimate rate" },
];

export default function PayrollTaxSettingsPanel() {
  const [settings, setSettings] = useState({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await getPayrollTaxSettings();
      setSettings(res.data || {});
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const res = await putPayrollTaxSettings(settings);
      setSettings(res.data || {});
      setInfo("Payroll tax settings saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        {PAYROLL_ESTIMATE_PURPOSE} {ESTIMATE_DISCLAIMER} Rates apply to W-2 batch calculations only.
      </Alert>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>
          {info}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Payroll tax settings
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Configure employer FICA, FUTA, NY SUTA, and estimate rates used for internal W-2 payroll
          reporting.
        </Typography>
        <Stack spacing={1.5} sx={{ maxWidth: 480 }}>
          {FIELDS.map((f) => (
            <TextField
              key={f.key}
              size="small"
              label={f.label}
              type={f.type || "text"}
              value={settings[f.key] ?? ""}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value,
                }))
              }
            />
          ))}
          <TextField
            size="small"
            label="Notes"
            multiline
            minRows={2}
            value={settings.notes || ""}
            onChange={(e) => setSettings((s) => ({ ...s, notes: e.target.value }))}
          />
          <Button variant="contained" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </Button>
        </Stack>
      </Paper>
    </Stack>
  );
}
