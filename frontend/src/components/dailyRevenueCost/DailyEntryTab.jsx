import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import SaveIcon from "@mui/icons-material/Save";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import { getDailyRevenueEntry, previewDailyRevenueEntry, saveDailyRevenueEntry } from "../../api";
import {
  DRC_STICKY_SAVE_SX,
  entryToForm,
  formToPayload,
  formatCurrency,
} from "../../utils/dailyRevenueCostHelpers";
import { CurrencyField, DailySummaryCard, NumberField, SectionCard } from "./DrcShared";

function commercialRevenue(line) {
  const pounds = Number(line.pounds) || 0;
  const rate = Number(line.rate_per_pound) || 0;
  const logistics = Number(line.logistics_charge) || 0;
  const additional = Number(line.additional_charge) || 0;
  return pounds * rate + logistics + additional;
}

export default function DailyEntryTab() {
  const [entryDate, setEntryDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [form, setForm] = useState(entryToForm(null));
  const [summary, setSummary] = useState(null);
  const [wfMeta, setWfMeta] = useState({});
  const [entryId, setEntryId] = useState(null);
  const [entryStatus, setEntryStatus] = useState("open");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadEntry = useCallback(async () => {
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const res = await getDailyRevenueEntry(entryDate);
      const data = res.data || {};
      const entry = data.entry || {};
      setForm(entryToForm(entry));
      setSummary(entry.summary || null);
      setWfMeta(entry.rinse_wf_meta || {});
      setEntryId(entry.id || null);
      setEntryStatus(entry.status || "open");
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load entry");
    } finally {
      setLoading(false);
    }
  }, [entryDate]);

  useEffect(() => {
    loadEntry();
  }, [loadEntry]);

  const refreshPreview = useCallback(
    async (nextForm) => {
      try {
        const payload = formToPayload(nextForm);
        const res = await previewDailyRevenueEntry(entryDate, {
          ...payload,
          exclude_entry_id: entryId,
        });
        const data = res.data || {};
        setSummary(data.summary || null);
        setWfMeta(data.rinse_wf_meta || {});
      } catch {
        // preview is best-effort
      }
    },
    [entryDate, entryId],
  );

  const updateField = (field, value) => {
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      refreshPreview(next);
      return next;
    });
  };

  const updateCommercialLine = (index, field, value) => {
    setForm((prev) => {
      const lines = [...(prev.commercial_lines || [])];
      lines[index] = { ...lines[index], [field]: value, revenue: 0 };
      lines[index].revenue = commercialRevenue(lines[index]);
      const next = { ...prev, commercial_lines: lines };
      refreshPreview(next);
      return next;
    });
  };

  const isLocked = entryStatus === "locked";

  const handleSave = async () => {
    if (isLocked) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const payload = formToPayload(form);
      const res = await saveDailyRevenueEntry(entryDate, payload);
      const data = res.data || {};
      setSummary(data.summary || data.entry?.summary || null);
      setEntryId(data.entry?.id || entryId);
      setSuccess("Saved successfully");
      await loadEntry();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const wfRevenue = summary?.rinse_wf_revenue ?? 0;

  const tierChips = useMemo(() => {
    const tiers = wfMeta?.applied_tiers || [];
    return tiers.map((t) => (
      <Chip
        key={t.tier_number}
        size="small"
        label={`Tier ${t.tier_number}: ${t.pounds_applied} lbs @ ${formatCurrency(t.rate_per_lb)}/lb`}
        sx={{ mr: 0.5, mb: 0.5 }}
      />
    ));
  }, [wfMeta]);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ pb: { xs: 10, md: 2 } }}>
      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {success ? <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert> : null}

      <SectionCard title="Date" subtitle="Select today or a previous date to enter or edit.">
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <PlanningDatePicker value={entryDate} onChange={setEntryDate} />
          </Box>
          {entryStatus && entryStatus !== "open" ? (
            <Chip label={entryStatus.toUpperCase()} color={entryStatus === "locked" ? "warning" : "default"} size="small" />
          ) : null}
        </Stack>
      </SectionCard>

      <SectionCard title="Self Service">
        <Stack spacing={2}>
          <CurrencyField label="Cash Revenue" value={form.self_service_cash} onChange={(e) => updateField("self_service_cash", e.target.value)} />
          <CurrencyField label="Card Revenue" value={form.self_service_card} onChange={(e) => updateField("self_service_card", e.target.value)} />
        </Stack>
      </SectionCard>

      <SectionCard title="Drop Off">
        <Stack spacing={2}>
          <CurrencyField label="Cash Revenue" value={form.drop_off_cash} onChange={(e) => updateField("drop_off_cash", e.target.value)} />
          <CurrencyField label="Card Revenue" value={form.drop_off_card} onChange={(e) => updateField("drop_off_card", e.target.value)} />
        </Stack>
      </SectionCard>

      <SectionCard title="Rinse WF" subtitle="Revenue auto-calculates from monthly tier pricing.">
        <Stack spacing={2}>
          <NumberField
            label="Pounds Processed"
            value={form.rinse_wf_pounds}
            onChange={(e) => updateField("rinse_wf_pounds", e.target.value)}
          />
          <Box sx={{ p: 1.5, bgcolor: "grey.50", borderRadius: 1 }}>
            <Typography variant="body2" color="text.secondary">
              MTD before today: {wfMeta.mtd_pounds_before ?? 0} lbs · After today: {wfMeta.mtd_pounds_after ?? 0} lbs
            </Typography>
            <Typography variant="subtitle1" fontWeight={700} sx={{ mt: 0.5 }}>
              Revenue: {formatCurrency(wfRevenue)}
            </Typography>
            <Box sx={{ mt: 1 }}>{tierChips}</Box>
          </Box>
        </Stack>
      </SectionCard>

      <SectionCard title="Rinse HD">
        <Stack spacing={2}>
          <TextField
            label="Number of Orders"
            type="number"
            value={form.rinse_hd_orders}
            onChange={(e) => updateField("rinse_hd_orders", e.target.value)}
            fullWidth
          />
          <CurrencyField label="Revenue" value={form.rinse_hd_revenue} onChange={(e) => updateField("rinse_hd_revenue", e.target.value)} />
        </Stack>
      </SectionCard>

      <SectionCard title="Rinse WI">
        <Stack spacing={2}>
          <TextField
            label="Number of Orders"
            type="number"
            value={form.rinse_wi_orders}
            onChange={(e) => updateField("rinse_wi_orders", e.target.value)}
            fullWidth
          />
          <CurrencyField label="Revenue" value={form.rinse_wi_revenue} onChange={(e) => updateField("rinse_wi_revenue", e.target.value)} />
        </Stack>
      </SectionCard>

      <SectionCard title="Commercial Accounts" subtitle="Accounts from Revenue Maintenance.">
        <Stack spacing={3}>
          {(form.commercial_lines || []).map((line, idx) => (
            <Box key={line.commercial_account_id || idx} sx={{ p: 2, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                {line.account_name}
              </Typography>
              <Stack spacing={2}>
                <NumberField label="Pounds / Volume" value={line.pounds} onChange={(e) => updateCommercialLine(idx, "pounds", e.target.value)} />
                <CurrencyField label="Rate per Pound" value={line.rate_per_pound} onChange={(e) => updateCommercialLine(idx, "rate_per_pound", e.target.value)} />
                <CurrencyField label="Logistics Charge" value={line.logistics_charge} onChange={(e) => updateCommercialLine(idx, "logistics_charge", e.target.value)} />
                <CurrencyField label="Additional Charge" value={line.additional_charge} onChange={(e) => updateCommercialLine(idx, "additional_charge", e.target.value)} />
                <Typography variant="body2" fontWeight={600}>
                  Revenue: {formatCurrency(line.revenue || commercialRevenue(line))}
                </Typography>
              </Stack>
            </Box>
          ))}
        </Stack>
      </SectionCard>

      <SectionCard title="Daily Payroll">
        <Stack spacing={2}>
          <CurrencyField label="Total Payroll" value={form.payroll_total} onChange={(e) => updateField("payroll_total", e.target.value)} />
          <Box sx={{ p: 1.5, bgcolor: "grey.50", borderRadius: 1 }}>
            <Typography variant="body2" color="text.secondary">Estimated Payroll Tax</Typography>
            <Typography variant="subtitle1" fontWeight={700}>{formatCurrency(summary?.payroll_tax_amount ?? 0)}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>Total Labor Cost</Typography>
            <Typography variant="subtitle1" fontWeight={700}>{formatCurrency(summary?.labor_cost ?? 0)}</Typography>
          </Box>
        </Stack>
      </SectionCard>

      <SectionCard title="Cost Estimate" subtitle="Daily values from Cost Maintenance.">
        <Typography variant="body2" color="text.secondary">
          Operating costs are applied automatically from maintenance settings when you save.
        </Typography>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mt: 1 }}>
          Est. Operating Cost: {formatCurrency(summary?.operating_cost ?? 0)}
        </Typography>
      </SectionCard>

      <DailySummaryCard summary={summary} />

      <Box sx={{ display: { xs: "none", md: "block" }, mt: 2 }}>
        <Button variant="contained" size="large" startIcon={<SaveIcon />} onClick={handleSave} disabled={saving || isLocked} fullWidth>
          {isLocked ? "Entry Locked" : saving ? "Saving…" : "Save Entry"}
        </Button>
      </Box>

      <Box sx={DRC_STICKY_SAVE_SX}>
        <Button variant="contained" size="large" startIcon={<SaveIcon />} onClick={handleSave} disabled={saving || isLocked} fullWidth>
          {isLocked ? "Entry Locked" : saving ? "Saving…" : "Save Entry"}
        </Button>
      </Box>
    </Box>
  );
}
