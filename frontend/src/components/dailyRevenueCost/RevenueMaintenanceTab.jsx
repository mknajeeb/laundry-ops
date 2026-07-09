import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import SaveIcon from "@mui/icons-material/Save";
import {
  createDrcCommercialAccount,
  getDrcCommercialAccounts,
  getDrcRinseWfTiers,
  updateDrcCommercialAccount,
  updateDrcRinseWfTiers,
} from "../../api";
import { CurrencyField, NumberField, SectionCard } from "./DrcShared";

function emptyAccount() {
  return {
    name: "",
    rate_per_pound: "",
    default_logistics_charge: "",
    default_additional_charge: "",
    active: true,
  };
}

export default function RevenueMaintenanceTab() {
  const [accounts, setAccounts] = useState([]);
  const [tiers, setTiers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingTiers, setSavingTiers] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyAccount());
  const [savingAccount, setSavingAccount] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [acctRes, tierRes] = await Promise.all([getDrcCommercialAccounts(), getDrcRinseWfTiers()]);
      setAccounts(acctRes.data || []);
      setTiers(tierRes.data || []);
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openNew = () => {
    setEditing(null);
    setForm(emptyAccount());
    setDialogOpen(true);
  };

  const openEdit = (acct) => {
    setEditing(acct);
    setForm({
      name: acct.name,
      rate_per_pound: acct.rate_per_pound,
      default_logistics_charge: acct.default_logistics_charge,
      default_additional_charge: acct.default_additional_charge,
      active: acct.active,
    });
    setDialogOpen(true);
  };

  const saveAccount = async () => {
    setSavingAccount(true);
    setError("");
    try {
      const body = {
        name: form.name,
        rate_per_pound: Number(form.rate_per_pound) || 0,
        default_logistics_charge: Number(form.default_logistics_charge) || 0,
        default_additional_charge: Number(form.default_additional_charge) || 0,
        active: form.active,
      };
      if (editing?.id) {
        await updateDrcCommercialAccount(editing.id, body);
      } else {
        await createDrcCommercialAccount(body);
      }
      setDialogOpen(false);
      setSuccess("Account saved");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to save account");
    } finally {
      setSavingAccount(false);
    }
  };

  const saveTiers = async () => {
    setSavingTiers(true);
    setError("");
    try {
      await updateDrcRinseWfTiers({
        tiers: tiers.map((t, i) => ({
          tier_number: t.tier_number || i + 1,
          max_lbs: t.max_lbs === "" || t.max_lbs === null ? null : Number(t.max_lbs),
          rate_per_lb: Number(t.rate_per_lb) || 0,
        })),
      });
      setSuccess("WF tiers saved");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to save tiers");
    } finally {
      setSavingTiers(false);
    }
  };

  const updateTier = (index, field, value) => {
    setTiers((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const addTier = () => {
    setTiers((prev) => [
      ...prev,
      { tier_number: prev.length + 1, max_lbs: "", rate_per_lb: "" },
    ]);
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
      {success ? <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess("")}>{success}</Alert> : null}

      <SectionCard title="Commercial Accounts">
        <Stack spacing={2}>
          {accounts.map((acct) => (
            <Box
              key={acct.id}
              sx={{
                p: 2,
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 2,
                opacity: acct.active ? 1 : 0.6,
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography fontWeight={700}>{acct.name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    ${acct.rate_per_pound}/lb · Logistics ${acct.default_logistics_charge} · Additional ${acct.default_additional_charge}
                  </Typography>
                  <Typography variant="caption" color={acct.active ? "success.main" : "text.disabled"}>
                    {acct.active ? "Active" : "Inactive"}
                  </Typography>
                </Box>
                <Button size="small" onClick={() => openEdit(acct)}>Edit</Button>
              </Stack>
            </Box>
          ))}
          <Button startIcon={<AddIcon />} variant="outlined" onClick={openNew}>
            Add Customer
          </Button>
        </Stack>
      </SectionCard>

      <SectionCard title="Rinse WF Tier Maintenance" subtitle="Saves as a new effective-dated schedule. Revenue uses tiers active on each entry date.">
        <Stack spacing={2}>
          {tiers.map((tier, idx) => (
            <Box key={tier.id || idx} sx={{ p: 2, border: "1px solid", borderColor: "divider", borderRadius: 2 }}>
              <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                Tier {tier.tier_number || idx + 1}
              </Typography>
              <Stack spacing={2}>
                <NumberField
                  label="Max lbs (blank = unlimited)"
                  value={tier.max_lbs ?? ""}
                  onChange={(e) => updateTier(idx, "max_lbs", e.target.value === "" ? null : e.target.value)}
                />
                <CurrencyField
                  label="Rate per lb"
                  value={tier.rate_per_lb}
                  onChange={(e) => updateTier(idx, "rate_per_lb", e.target.value)}
                />
              </Stack>
            </Box>
          ))}
          <Button startIcon={<AddIcon />} variant="outlined" onClick={addTier}>
            Add Tier
          </Button>
          <Button variant="contained" startIcon={<SaveIcon />} onClick={saveTiers} disabled={savingTiers}>
            {savingTiers ? "Saving…" : "Save Tiers"}
          </Button>
        </Stack>
      </SectionCard>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editing ? "Edit Customer" : "Add Customer"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Customer Name" value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} fullWidth />
            <CurrencyField label="Rate per Pound" value={form.rate_per_pound} onChange={(e) => setForm((p) => ({ ...p, rate_per_pound: e.target.value }))} />
            <CurrencyField label="Default Logistics Charge" value={form.default_logistics_charge} onChange={(e) => setForm((p) => ({ ...p, default_logistics_charge: e.target.value }))} />
            <CurrencyField label="Default Additional Charge" value={form.default_additional_charge} onChange={(e) => setForm((p) => ({ ...p, default_additional_charge: e.target.value }))} />
            <FormControlLabel
              control={<Switch checked={form.active} onChange={(e) => setForm((p) => ({ ...p, active: e.target.checked }))} />}
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveAccount} disabled={savingAccount}>
            {savingAccount ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
