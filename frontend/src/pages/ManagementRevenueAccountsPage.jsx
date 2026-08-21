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
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RefreshIcon from "@mui/icons-material/Refresh";
import { Link as RouterLink } from "react-router-dom";
import {
  getManagementRevenueAccounts,
  saveManagementRevenueAccount,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import { todayEtIso } from "../components/management/revenue/revenueFormat";
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
    parent_id: "",
    service_type: "",
    revenue_mode: "calculated",
    active: true,
    allow_override: true,
    use_pickup_date: false,
    use_processing_date: true,
    use_delivery_date: false,
    entry_cadence: "scheduled",
    pickup_weekdays: [],
    delivery_weekdays: [],
    pickup_pairs: [],
    pickups_per_week: 0,
    needs_schedule_confirm: false,
    notes: "",
    pricing_method: "flat_lb",
    rate_per_unit: "",
    effective_from: todayEtIso(),
    tiers: [
      { tier_number: 1, max_lbs: 5000, rate_per_lb: 1.0 },
      { tier_number: 2, max_lbs: "", rate_per_lb: 0.95 },
    ],
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

  const parentOptions = useMemo(() => {
    return accounts
      .filter((a) => a.active !== false)
      .filter((a) => !editing || a.id !== editing.id)
      .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0) || String(a.name).localeCompare(b.name));
  }, [accounts, editing]);

  const dhsParentId = useMemo(
    () => accounts.find((a) => a.account_code === "dhs")?.id || "",
    [accounts],
  );

  const visibleGroups = useMemo(() => {
    if (filter === "all") return REVENUE_GROUPS;
    return REVENUE_GROUPS.filter((g) => g.value === filter);
  }, [filter]);

  const openNew = () => {
    setEditing(null);
    setForm({ ...emptyForm(), parent_id: dhsParentId || "" });
    setDialogOpen(true);
  };

  const openEdit = (acct) => {
    setEditing(acct);
    const pr = acct.pricing || {};
    setForm({
      name: acct.name || "",
      revenue_group: acct.revenue_group || "dhs",
      parent_id: acct.parent_id || "",
      service_type: acct.service_type || "",
      revenue_mode: acct.revenue_mode || "calculated",
      active: acct.active !== false,
      allow_override: acct.allow_override !== false,
      use_pickup_date: Boolean(acct.use_pickup_date),
      use_processing_date: acct.use_processing_date !== false,
      use_delivery_date: Boolean(acct.use_delivery_date),
      entry_cadence: acct.entry_cadence || "scheduled",
      pickup_weekdays: acct.schedule?.pickup_weekdays || [],
      delivery_weekdays: acct.schedule?.delivery_weekdays || [],
      pickup_pairs: acct.schedule?.pickup_pairs || [],
      pickups_per_week: acct.schedule?.pickups_per_week || (acct.schedule?.pickup_pairs || []).length || 0,
      needs_schedule_confirm: Boolean(acct.schedule?.needs_schedule_confirm),
      notes: acct.notes || "",
      pricing_method: pr.pricing_method || "flat_lb",
      rate_per_unit: pr.rate_per_unit ?? "",
      effective_from: pr.effective_from || todayEtIso(),
      tiers: pr.tiers?.length ? pr.tiers : emptyForm().tiers,
    });
    setDialogOpen(true);
  };

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      const parentId =
        form.parent_id === "" || form.parent_id == null
          ? form.revenue_group === "dhs"
            ? dhsParentId || null
            : null
          : Number(form.parent_id);

      const body = {
        id: editing?.id,
        name: form.name.trim(),
        revenue_group: form.revenue_group,
        service_type: form.service_type || null,
        revenue_mode: form.revenue_mode,
        active: form.active,
        allow_override: form.allow_override,
        use_pickup_date: form.use_pickup_date,
        use_processing_date: form.use_processing_date,
        use_delivery_date: form.use_delivery_date,
        entry_cadence: form.entry_cadence,
        pickup_pairs: form.pickup_pairs,
        pickup_weekdays: (form.pickup_pairs || []).map((p) => p.pickup_weekday),
        delivery_weekdays: (form.pickup_pairs || []).map((p) => p.delivery_weekday),
        notes: form.notes || null,
        parent_id: parentId,
        pricing: {
          effective_from: form.effective_from || todayEtIso(),
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
      const res = await saveManagementRevenueAccount(body);
      const saved = res.data?.account || res.data || {};
      const pickup = (saved.schedule?.pickup_weekdays || []).map(String).join("/") || "—";
      const delivery = (saved.schedule?.delivery_weekdays || []).map(String).join("/") || "—";
      setSuccess(`Saved · Pickup days ${pickup} · Delivery days ${delivery}`);
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 2 }, pb: 4, bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100%" }}>
      <ManagementHubNav activeId="revenue" />
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
        sx={{ py: 1.5 }}
      >
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800 }}>Accounts & Pricing</Typography>
          <Typography sx={{ fontSize: 13, color: "#64748b" }}>
            Revenue group → account → sub-account. Date basis and pricing are per account.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button component={RouterLink} to="/management/revenue" variant="outlined" size="small" sx={{ textTransform: "none" }}>
            Entry
          </Button>
          <IconButton onClick={load} aria-label="Refresh">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {success ? (
        <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setSuccess("")}>
          {success}
        </Alert>
      ) : null}

      <Stack direction="row" spacing={1} sx={{ mb: 2 }} alignItems="center">
        <Tabs value={filter} onChange={(_, v) => setFilter(v)} variant="scrollable" sx={{ flex: 1 }}>
          <Tab value="all" label="All" />
          {REVENUE_GROUPS.map((g) => (
            <Tab key={g.value} value={g.value} label={g.label} />
          ))}
        </Tabs>
        <Button
          variant="contained"
          size="small"
          onClick={openNew}
          sx={{
            textTransform: "none",
            fontWeight: 800,
            bgcolor: VEEWASH_DASHBOARD.primaryBlue,
            "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
          }}
        >
          Add account
        </Button>
      </Stack>

      {loading ? (
        <CircularProgress />
      ) : (
        <Stack spacing={1.5}>
          {visibleGroups.map((g) => {
            const rows = (grouped[g.value] || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
            return (
              <Accordion key={g.value} defaultExpanded disableGutters sx={{ bgcolor: "#fff", border: "1px solid #e5e7eb", borderRadius: 2, "&:before": { display: "none" } }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography sx={{ fontWeight: 800 }}>{g.label}</Typography>
                  <Chip label={rows.length} size="small" sx={{ ml: 1 }} />
                </AccordionSummary>
                <AccordionDetails>
                  {!rows.length ? (
                    <Typography sx={{ fontSize: 13, color: "#64748b" }}>No accounts in this group.</Typography>
                  ) : (
                    <Stack spacing={1}>
                      {rows.map((a) => {
                        const parent = accounts.find((p) => p.id === a.parent_id);
                        const dates = [
                          a.use_pickup_date ? "Pickup" : null,
                          a.use_processing_date !== false ? "Processing" : null,
                          a.use_delivery_date ? "Delivery" : null,
                        ].filter(Boolean);
                        return (
                          <Box
                            key={a.id}
                            sx={{
                              p: 1.25,
                              border: "1px solid #e5e7eb",
                              borderRadius: 1.5,
                              display: "flex",
                              justifyContent: "space-between",
                              gap: 1,
                              bgcolor: a.active === false ? "#f8fafc" : "#fff",
                            }}
                          >
                            <Box>
                              <Typography sx={{ fontWeight: 700 }}>
                                {parent && parent.account_code !== a.account_code ? `${parent.name} → ` : ""}
                                {a.name}
                              </Typography>
                              <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                                {a.revenue_mode}
                                {a.allow_override === false ? " · no override" : " · override OK"}
                                {" · "}
                                {a.pricing?.pricing_method || "no pricing"}
                                {a.pricing?.rate_per_unit != null ? ` · $${a.pricing.rate_per_unit}/unit` : ""}
                                {dates.length ? ` · dates: ${dates.join(", ")}` : ""}
                                {a.active === false ? " · inactive" : ""}
                              </Typography>
                            </Box>
                            <Button size="small" onClick={() => openEdit(a)} sx={{ textTransform: "none" }}>
                              Edit
                            </Button>
                          </Box>
                        );
                      })}
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
            <TextField
              label="Account name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              fullWidth
              required
            />
            <FormControl fullWidth size="small">
              <InputLabel>Revenue group</InputLabel>
              <Select
                label="Revenue group"
                value={form.revenue_group}
                onChange={(e) => setForm({ ...form, revenue_group: e.target.value })}
              >
                {REVENUE_GROUPS.map((g) => (
                  <MenuItem key={g.value} value={g.value}>
                    {g.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Parent account</InputLabel>
              <Select
                label="Parent account"
                value={form.parent_id || ""}
                onChange={(e) => setForm({ ...form, parent_id: e.target.value })}
              >
                <MenuItem value="">None (top-level)</MenuItem>
                {parentOptions.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name} ({p.revenue_group})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth size="small">
              <InputLabel>Revenue mode</InputLabel>
              <Select
                label="Revenue mode"
                value={form.revenue_mode}
                onChange={(e) => setForm({ ...form, revenue_mode: e.target.value })}
              >
                <MenuItem value="calculated">Calculated from volume</MenuItem>
                <MenuItem value="absolute">Absolute entry</MenuItem>
              </Select>
            </FormControl>

            <Typography sx={{ fontWeight: 800, fontSize: 13, pt: 0.5 }}>Date basis (entry form)</Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={form.use_pickup_date}
                  onChange={(e) => setForm({ ...form, use_pickup_date: e.target.checked })}
                />
              }
              label="Use Pickup Date"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.use_processing_date}
                  onChange={(e) => setForm({ ...form, use_processing_date: e.target.checked })}
                />
              }
              label="Use Processing Date"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={form.use_delivery_date}
                  onChange={(e) => setForm({ ...form, use_delivery_date: e.target.checked })}
                />
              }
              label="Use Delivery Date"
            />
            <FormControl fullWidth size="small">
              <InputLabel>Entry cadence</InputLabel>
              <Select
                label="Entry cadence"
                value={form.entry_cadence || "scheduled"}
                onChange={(e) => setForm({ ...form, entry_cadence: e.target.value })}
              >
                <MenuItem value="daily">Daily</MenuItem>
                <MenuItem value="scheduled">Scheduled</MenuItem>
                <MenuItem value="optional">Optional / ad hoc</MenuItem>
              </Select>
            </FormControl>
            {form.entry_cadence === "scheduled" ? (
              <Box>
                {form.needs_schedule_confirm ? (
                  <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#b45309", mb: 1 }}>
                    Prior weekday lists were ambiguous — set pickup→delivery pairs below.
                  </Typography>
                ) : null}
                <Typography sx={{ fontSize: 12, fontWeight: 700, mb: 0.75 }}>Pickups per week</Typography>
                <Stack direction="row" spacing={0.5} sx={{ mb: 1 }}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Button
                      key={n}
                      size="small"
                      variant={(form.pickup_pairs || []).length === n ? "contained" : "outlined"}
                      onClick={() => {
                        const cur = [...(form.pickup_pairs || [])];
                        while (cur.length < n) {
                          cur.push({ pickup_weekday: cur.length % 7, delivery_weekday: (cur.length + 1) % 7 });
                        }
                        setForm({
                          ...form,
                          pickup_pairs: cur.slice(0, n),
                          pickups_per_week: n,
                        });
                      }}
                      sx={{ textTransform: "none", minWidth: 40 }}
                    >
                      {n}
                    </Button>
                  ))}
                </Stack>
                {(form.pickup_pairs || []).map((pair, i) => (
                  <Box key={i} sx={{ mb: 1.25, p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb" }}>
                    <Typography sx={{ fontSize: 12, fontWeight: 800, mb: 0.75 }}>Pickup {i + 1}</Typography>
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                      <FormControl size="small" fullWidth>
                        <InputLabel>Pickup day</InputLabel>
                        <Select
                          label="Pickup day"
                          value={pair.pickup_weekday ?? 0}
                          onChange={(e) => {
                            const next = [...(form.pickup_pairs || [])];
                            next[i] = { ...next[i], pickup_weekday: Number(e.target.value) };
                            setForm({ ...form, pickup_pairs: next });
                          }}
                        >
                          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((lab, idx) => (
                            <MenuItem key={idx} value={idx}>{lab}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormControl size="small" fullWidth>
                        <InputLabel>Delivery day</InputLabel>
                        <Select
                          label="Delivery day"
                          value={pair.delivery_weekday ?? 1}
                          onChange={(e) => {
                            const next = [...(form.pickup_pairs || [])];
                            next[i] = { ...next[i], delivery_weekday: Number(e.target.value) };
                            setForm({ ...form, pickup_pairs: next });
                          }}
                        >
                          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((lab, idx) => (
                            <MenuItem key={idx} value={idx}>{lab}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </Stack>
                  </Box>
                ))}
              </Box>
            ) : null}
            <FormControlLabel
              control={
                <Switch
                  checked={form.allow_override}
                  onChange={(e) => setForm({ ...form, allow_override: e.target.checked })}
                />
              }
              label="Allow revenue override"
            />
            <FormControlLabel
              control={
                <Switch checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
              }
              label="Active"
            />

            <FormControl fullWidth size="small">
              <InputLabel>Pricing method</InputLabel>
              <Select
                label="Pricing method"
                value={form.pricing_method}
                onChange={(e) => setForm({ ...form, pricing_method: e.target.value })}
              >
                {PRICING_METHODS.map((m) => (
                  <MenuItem key={m.value} value={m.value}>
                    {m.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <PlanningDatePicker
              value={form.effective_from}
              onChange={(v) => setForm({ ...form, effective_from: v })}
              label="Pricing effective from"
            />
            {form.pricing_method === "flat_lb" || form.pricing_method === "flat_amount" || form.pricing_method === "per_order" ? (
              <TextField
                label={form.pricing_method === "flat_lb" ? "Rate per lb" : "Rate"}
                value={form.rate_per_unit}
                onChange={(e) => setForm({ ...form, rate_per_unit: e.target.value })}
                inputMode="decimal"
                fullWidth
              />
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
            <TextField
              label="Notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              fullWidth
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={saving} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={submit}
            disabled={saving || !form.name.trim()}
            sx={{
              textTransform: "none",
              fontWeight: 800,
              bgcolor: VEEWASH_DASHBOARD.primaryBlue,
              "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
