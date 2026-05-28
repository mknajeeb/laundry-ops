import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { getPayrollTaxSettings, putPayrollTaxSettings } from "../api";
import { ESTIMATE_DISCLAIMER, PAYROLL_ESTIMATE_PURPOSE } from "../payroll/payrollTaxMessages";

const TAX_FIELDS = [
  { key: "tax_year", label: "Tax year", type: "number" },
  { key: "employee_social_security_rate", label: "Employee SS rate" },
  { key: "employer_social_security_rate", label: "Employer SS rate" },
  { key: "social_security_wage_base", label: "SS wage base" },
  { key: "employee_medicare_rate", label: "Employee Medicare rate" },
  { key: "employer_medicare_rate", label: "Employer Medicare rate" },
  { key: "futa_rate", label: "FUTA rate" },
  { key: "futa_wage_base", label: "FUTA wage base" },
  { key: "ny_suta_rate", label: "NY SUTA rate (employer-assigned DOL UI rate)" },
  { key: "ny_suta_wage_base", label: "NY SUTA wage base (2026: 17600)" },
  { key: "ny_reemployment_service_fund_rate", label: "NY re-employment fund rate (RSF)" },
  { key: "ny_pfl_employee_rate", label: "NY PFL employee rate (2026: 0.00432)" },
  { key: "ny_pfl_employee_annual_cap", label: "NY PFL annual cap (2026: 411.91)" },
  { key: "ny_dbl_employee_rate", label: "NY DBL employee rate" },
  { key: "ny_dbl_employee_weekly_cap", label: "NY DBL weekly cap" },
  { key: "federal_standard_deduction_single", label: "Federal std deduction — single (2026: 16100)" },
  { key: "federal_standard_deduction_mfj", label: "Federal std deduction — MFJ (2026: 32200)" },
  { key: "federal_standard_deduction_hoh", label: "Federal std deduction — HoH (2026: 24150)" },
  { key: "ny_withholding_estimate_rate", label: "NY withholding estimate rate" },
  { key: "nyc_resident_estimate_rate", label: "NYC resident estimate rate" },
  { key: "nyc_mctmt_quarterly_payroll_threshold", label: "MCTMT quarterly threshold (312500)" },
  { key: "nyc_mctmt_tier1_cap", label: "MCTMT tier 1 cap (375000)" },
  { key: "nyc_mctmt_tier1_rate", label: "MCTMT tier 1 rate (0.00055)" },
  { key: "nyc_mctmt_tier2_cap", label: "MCTMT tier 2 cap (437500)" },
  { key: "nyc_mctmt_tier2_rate", label: "MCTMT tier 2 rate (0.00115)" },
  { key: "nyc_mctmt_tier3_cap", label: "MCTMT tier 3 cap (2500000)" },
  { key: "nyc_mctmt_tier3_rate", label: "MCTMT tier 3 rate (0.006)" },
  { key: "nyc_mctmt_tier4_rate", label: "MCTMT tier 4 rate (0.00895)" },
  { key: "workers_comp_rate", label: "Workers comp rate" },
];

const SICK_FIELDS = [
  { key: "sick_leave_annual_cap_hours", label: "Sick leave annual cap (hours)", type: "number" },
  { key: "sick_leave_annual_cap_hours_large_employer", label: "Sick cap — 100+ employees", type: "number" },
  { key: "sick_leave_large_employer_threshold", label: "Large employer threshold", type: "number" },
];

const HEALTH_CREDIT_FIELDS = [
  { key: "health_credit_rate_per_hour", label: "Health credit $/hour (when per_hour)" },
  { key: "health_credit_flat_amount_per_period", label: "Health credit flat $/period" },
  { key: "health_credit_cap_per_period", label: "Health credit cap per period" },
  { key: "health_credit_cap_per_year", label: "Health credit cap per year" },
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
      setInfo("Payroll settings saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const field = (f) => (
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
  );

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        {PAYROLL_ESTIMATE_PURPOSE} {ESTIMATE_DISCLAIMER}
      </Alert>
      <Alert severity="warning">
        Estimated/internal payroll tracking — verify with accountant/payroll provider. NY SUTA rate
        must be set manually from your NY DOL UI notice (new employer 2026 total ≈ 0.041 including RSF).
      </Alert>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {info ? (
        <Alert severity="success" onClose={() => setInfo("")}>
          {info}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Payroll tax settings (2026 defaults)
        </Typography>
        <Stack spacing={1.5} sx={{ maxWidth: 520 }}>
          {TAX_FIELDS.map(field)}
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(settings.nyc_mctmt_enabled)}
                onChange={(e) => setSettings((s) => ({ ...s, nyc_mctmt_enabled: e.target.checked }))}
              />
            }
            label="Enable NYC MCTMT estimate (Zone 1 tiers; $0 if quarterly payroll below threshold)"
          />
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(settings.ny_dbl_employee_enabled)}
                onChange={(e) => setSettings((s) => ({ ...s, ny_dbl_employee_enabled: e.target.checked }))}
              />
            }
            label="Include NY DBL employee deduction estimate"
          />
          <TextField
            size="small"
            label="NY SUTA note"
            multiline
            minRows={2}
            value={settings.ny_suta_rate_note || ""}
            onChange={(e) => setSettings((s) => ({ ...s, ny_suta_rate_note: e.target.value }))}
          />
        </Stack>
      </Paper>
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          W-2 sick leave (NYC/NY)
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Accrual: 1 hour per 30 hours worked. W-2 employees only.
        </Typography>
        <Stack spacing={1.5} sx={{ maxWidth: 520 }}>
          {SICK_FIELDS.map(field)}
          <FormControlLabel
            control={
              <Switch
                checked={settings.sick_leave_carryover_enabled !== false}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, sick_leave_carryover_enabled: e.target.checked }))
                }
              />
            }
            label="Carry over unused sick leave"
          />
        </Stack>
      </Paper>
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          1099 / Temp health credit
        </Typography>
        <Alert severity="info" sx={{ mb: 1 }}>
          Health / attendance credit is internal discretionary tracking — not W-2 sick leave. Verify
          with accountant/legal advisor.
        </Alert>
        <Stack spacing={1.5} sx={{ maxWidth: 520 }}>
          <FormControl size="small">
            <InputLabel>Accrual method</InputLabel>
            <Select
              label="Accrual method"
              value={settings.health_credit_accrual_method || "manual_only"}
              onChange={(e) =>
                setSettings((s) => ({ ...s, health_credit_accrual_method: e.target.value }))
              }
            >
              <MenuItem value="manual_only">Manual only (default)</MenuItem>
              <MenuItem value="per_hour">Per hour</MenuItem>
              <MenuItem value="flat_per_period">Flat per period</MenuItem>
            </Select>
          </FormControl>
          {HEALTH_CREDIT_FIELDS.map(field)}
          <FormControlLabel
            control={
              <Switch
                checked={settings.health_credit_enabled_for_1099 !== false}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, health_credit_enabled_for_1099: e.target.checked }))
                }
              />
            }
            label="Enabled for 1099"
          />
          <FormControlLabel
            control={
              <Switch
                checked={settings.health_credit_enabled_for_temp !== false}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, health_credit_enabled_for_temp: e.target.checked }))
                }
              />
            }
            label="Enabled for Temp"
          />
        </Stack>
      </Paper>
      <Paper sx={{ p: 2 }}>
        <Stack spacing={1.5} sx={{ maxWidth: 520 }}>
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
