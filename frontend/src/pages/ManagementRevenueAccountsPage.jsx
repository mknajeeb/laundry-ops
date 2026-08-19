import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RefreshIcon from "@mui/icons-material/Refresh";
import SettingsIcon from "@mui/icons-material/Settings";
import { Link as RouterLink } from "react-router-dom";
import {
  getManagementRevenueAccounts,
  saveManagementRevenueAccount,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const REVENUE_GROUPS = [
  { value: "rinse_wf", label: "Rinse WF" },
  { value: "rinse_hd", label: "Rinse HD" },
  { value: "non_rinse", label: "Non-Rinse" },
  { value: "dhs", label: "DHS" },
];

const PRICING_METHODS = [
  { value: "flat_lb", label: "Flat $/lb" },
  { value: "tiered_lb", label: "Tiered $/lb" },
  { value: "flat_amount", label: "Absolute amount" },
  { value: "per_order", label: "Per order" },
];

function emptyForm() {
  return {
    name: "",
    revenue_group: "dhs",
    service_type: "",
    revenue_mode: "calculated",
    active: true,
    notes: "",
    pricing_method: "flat_lb",
    rate_per_unit: "",
    tiers: [{ tier_number: 1, max_lbs: 5000, rate_per_lb: 1.0 }, { tier_number: 2, max_lbs: "", rate_per_lb: 0.95 }],
  };
}

export default function ManagementRevenueAccountsPage() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(emptyForm());
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRevenueAccounts();
      setAccounts(res.data?.accounts || []);
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Unable to load accounts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const grouped = useMemo(() => {
    const map = {};
    for (const a of accounts) {
      const g = a.revenue_group || "other";
      if (!map[g]) map[g] = [];
      map[g].push(a);
    }
    return map;
  }, [accounts]);

  const visibleGroups = useMemo(() => {
    if (filter === "all") return REVENUE_GROUPS;
    return REVENUE_GROUPS.filter((g) => g.value === filter);
  }, [filter]);

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setDialogOpen(true);
  };

  const openEdit = (acct) => {
    setEditing(acct);
    const pr = acct.pricing || {};
    setForm({
      name: acct.name || "",
      revenue_group: acct.revenue_group || "dhs",
      service_type: acct.service_type || "",
      revenue_mode: acct.revenue_mode || "calculated",
      active: acct.active !== false,
      notes: acct.notes || "",
      pricing_method: pr.pricing_method || "flat_lb",
      rate_per_unit: pr.rate_per_unit ?? "",
      tiers: pr.tiers?.length ? pr.tiers : emptyForm().tiers,
    });
    setDialogOpen(true);
  };

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      const body = {
        id: editing?.id,
        name: form.name.trim(),
        revenue_group: form.revenue_group,
        service_type: form.service_type || null,
        revenue_mode: form.revenue_mode,
        active: form.active,
        notes: form.notes || null,
        parent_id: form.revenue_group === "dhs" ? accounts.find((a) => a.account_code === "dhs")?.id : null,
        pricing: {
          effective_from: new Date().toISOString().slice(0, 10),
          pricing_method: form.pricing_method,
          pricing_unit: form.pricing_method.includes("order") ? "orders" : "lbs",
          rate_per_unit: form.rate_per_unit !== "" ? Number(form.rate_per_unit) : null,
          tiers:
            form.pricing_method === "tiered_lb"
              ? form.tiers.map((t, i) => ({
                  tier_number: i + 1,
                  max_lbs: t.max_lbs === "" || t.max_lbs == null ? null : Number(t.max_lbs),
                  rate_per_lb: Number(t.rate_per_lb) || 0,
                }))
              : null,
        },
      };
      await saveManagementRevenueAccount(body);
      setSuccess("Account saved");
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ maxWidth: 960, mx: "auto", px: { xs: 1.5, sm: 2 }, pb: 4 }}>
      <ManagementHubNav activeId="revenue" />
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 1.5 }}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800 }}>Accounts & Pricing</Typography>
          <Typography sx={{ fontSize: 13, color: "#64748b" }}>
            Configure accounts, revenue mode, and effective-dated pricing rules.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button component={RouterLink} to="/management/revenue" variant="outlined" size="small">
            Revenue Entry
          </Button>
          <IconButton onClick={load} aria-label="Refresh">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>{error}</Alert> : null}
      {success ? <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setSuccess("")}>{success}</Alert> : null}

      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <Tabs value={filter} onChange={(_, v) => setFilter(v)} variant="scrollable">
          <Tab value="all" label="All" />
          {REVENUE_GROUPS.map((g) => (
            <Tab key={g.value} value={g.value} label={g.label} />
          ))}
        </Tabs>
        <Button variant="contained" size="small" onClick={openNew} sx={{ ml: "auto", alignSelf: "center" }}>
          Add account
        </Button>
      </Stack>

      {loading ? (
        <CircularProgress />
      ) : (
        <Stack spacing={1.5}>
          {visibleGroups.map((g) => {
            const rows = grouped[g.value] || [];
            if (!rows.length && filter !== "all" && filter !== g.value) return null;
            return (
              <Accordion key={g.value} defaultExpanded disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography sx={{ fontWeight: 800 }}>{g.label}</Typography>
                  <Chip label={rows.length} size="small" sx={{ ml: 1 }} />
                </AccordionSummary>
                <AccordionDetails>
                  {!rows.length ? (
                    <Typography sx={{ fontSize: 13, color: "#64748b" }}>No accounts in this group.</Typography>
                  ) : (
                    <Stack spacing={1}>
                      {rows.map((a) => (
                        <Box
                          key={a.id}
                          sx={{
                            p: 1.25,
                            border: "1px solid #e5e7eb",
                            borderRadius: 1.5,
                            display: "flex",
                            justifyContent: "space-between",
                            gap: 1,
                          }}
                        >
                          <Box>
                            <Typography sx={{ fontWeight: 700 }}>{a.name}</Typography>
                            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                              {a.revenue_mode} · {a.pricing?.pricing_method || "no pricing"}
                              {a.pricing?.rate_per_unit != null ? ` · $${a.pricing.rate_per_unit}/unit` : ""}
                            </Typography>
                          </Box>
                          <Button size="small" onClick={() => openEdit(a)}>
                            Edit
                          </Button>
                        </Box>
                      ))}
                    </Stack>
                  )}
                </AccordionDetails>
              </Accordion>
            );
          })}
        </Stack>
      )}

      <Dialog open={dialogOpen} onClose={() => !saving && setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 800 }}>{editing ? "Edit account" : "New account"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <TextField label="Account name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} fullWidth required />
            <FormControl fullWidth size="small">
              <InputLabel>Revenue group</InputLabel>
              <Select label="Revenue group" value={form.revenue_group} onChange={(e) => setForm({ ...form, revenue_group: e.target.value })}>
                {REVENUE_GROUPS.map((g) => (
                  <MenuItem key={g.value} value={g.value}>{g.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Revenue mode</InputLabel>
              <Select label="Revenue mode" value={form.revenue_mode} onChange={(e) => setForm({ ...form, revenue_mode: e.target.value })}>
                <MenuItem value="calculated">Calculated from volume</MenuItem>
                <MenuItem value="absolute">Absolute entry</MenuItem>
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Pricing method</InputLabel>
              <Select label="Pricing method" value={form.pricing_method} onChange={(e) => setForm({ ...form, pricing_method: e.target.value })}>
                {PRICING_METHODS.map((m) => (
                  <MenuItem key={m.value} value={m.value}>{m.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            {form.pricing_method === "flat_lb" ? (
              <TextField label="Rate per lb" value={form.rate_per_unit} onChange={(e) => setForm({ ...form, rate_per_unit: e.target.value })} inputMode="decimal" fullWidth />
            ) : null}
            {form.pricing_method === "tiered_lb" ? (
              <Stack spacing={1}>
                {form.tiers.map((t, idx) => (
                  <Stack key={idx} direction="row" spacing={1}>
                    <TextField
                      label={`Tier ${idx + 1} max lbs`}
                      value={t.max_lbs ?? ""}
                      onChange={(e) => {
                        const tiers = [...form.tiers];
                        tiers[idx] = { ...tiers[idx], max_lbs: e.target.value };
                        setForm({ ...form, tiers });
                      }}
                      size="small"
                      fullWidth
                    />
                    <TextField
                      label="$/lb"
                      value={t.rate_per_lb ?? ""}
                      onChange={(e) => {
                        const tiers = [...form.tiers];
                        tiers[idx] = { ...tiers[idx], rate_per_lb: e.target.value };
                        setForm({ ...form, tiers });
                      }}
                      size="small"
                      fullWidth
                    />
                  </Stack>
                ))}
              </Stack>
            ) : null}
            <TextField label="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} fullWidth multiline minRows={2} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={saving}>Cancel</Button>
          <Button variant="contained" onClick={submit} disabled={saving || !form.name.trim()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
