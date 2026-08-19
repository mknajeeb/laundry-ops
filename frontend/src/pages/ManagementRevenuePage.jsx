import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import RefreshIcon from "@mui/icons-material/Refresh";
import SettingsIcon from "@mui/icons-material/Settings";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { Link as RouterLink } from "react-router-dom";
import {
  createManagementCashPayout,
  deleteManagementCashPayout,
  getManagementCashActivity,
  getManagementRevenue,
  getManagementRevenueDashboard,
  saveManagementRevenueDhs,
  saveManagementRevenueNonRinse,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

function todayEtIso() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function parseMoneyInput(v) {
  const n = Number(String(v ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function SectionCard({ title, subtitle, children, action }) {
  return (
    <Box
      sx={{
        border: "1px solid #e5e7eb",
        borderRadius: 2,
        bgcolor: "#fff",
        p: { xs: 1.5, sm: 2 },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1.25 }}>
        <Box>
          <Typography sx={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>{title}</Typography>
          {subtitle ? (
            <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.25 }}>{subtitle}</Typography>
          ) : null}
        </Box>
        {action}
      </Stack>
      {children}
    </Box>
  );
}

function MoneyField({ label, value, onChange, disabled }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      size="small"
      fullWidth
      inputMode="decimal"
      sx={{ "& .MuiInputBase-root": { fontWeight: 700 } }}
    />
  );
}

const CASH_PERIODS = [
  { id: "today", label: "Today" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
  { id: "custom", label: "Custom" },
];

const DASH_PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "Week" },
  { id: "previous_week", label: "Prev Week" },
  { id: "month", label: "Month" },
  { id: "previous_month", label: "Prev Month" },
  { id: "custom", label: "Custom" },
];

export default function ManagementRevenuePage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [data, setData] = useState(null);

  const [ssCash, setSsCash] = useState("");
  const [ssCard, setSsCard] = useState("");
  const [doCash, setDoCash] = useState("");
  const [doCard, setDoCard] = useState("");

  const [cashPeriod, setCashPeriod] = useState("today");
  const [cashActivity, setCashActivity] = useState(null);
  const [cashLoading, setCashLoading] = useState(false);
  const [customStart, setCustomStart] = useState(todayEtIso);
  const [customEnd, setCustomEnd] = useState(todayEtIso);

  const [payoutOpen, setPayoutOpen] = useState(false);
  const [payoutPurpose, setPayoutPurpose] = useState("");
  const [payoutAmount, setPayoutAmount] = useState("");
  const [payoutNote, setPayoutNote] = useState("");
  const [payoutBusy, setPayoutBusy] = useState(false);
  const [view, setView] = useState("entry");
  const [dashPeriod, setDashPeriod] = useState("today");
  const [dashboard, setDashboard] = useState(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [dhsDraft, setDhsDraft] = useState({});

  const nonRinseTotals = useMemo(() => {
    const ss = parseMoneyInput(ssCash) + parseMoneyInput(ssCard);
    const dO = parseMoneyInput(doCash) + parseMoneyInput(doCard);
    return { ss, do: dO, total: ss + dO };
  }, [ssCash, ssCard, doCash, doCard]);

  const applyPayload = useCallback((payload) => {
    setData(payload);
    const nr = payload?.non_rinse_revenue || payload?.non_rinse || {};
    setSsCash(String(nr.self_service?.cash ?? ""));
    setSsCard(String(nr.self_service?.card ?? ""));
    setDoCash(String(nr.drop_off?.cash ?? ""));
    setDoCard(String(nr.drop_off?.card ?? ""));
    const dhsDraftMap = {};
    for (const row of payload?.dhs?.accounts || []) {
      dhsDraftMap[row.account_id] = {
        volume: row.volume ?? "",
        revenue: row.revenue ?? "",
        revenue_mode: row.revenue_mode,
        dr_commercial_account_id: row.dr_commercial_account_id,
      };
    }
    setDhsDraft(dhsDraftMap);
  }, []);

  const loadDay = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRevenue(dateEt);
      applyPayload(res.data || {});
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Unable to load revenue");
    } finally {
      setLoading(false);
    }
  }, [applyPayload, dateEt]);

  const loadCashActivity = useCallback(async () => {
    setCashLoading(true);
    try {
      const params = { period: cashPeriod, date: dateEt };
      if (cashPeriod === "custom") {
        params.start = customStart;
        params.end = customEnd;
      }
      const res = await getManagementCashActivity(params);
      setCashActivity(res.data || null);
    } catch {
      setCashActivity(null);
    } finally {
      setCashLoading(false);
    }
  }, [cashPeriod, customEnd, customStart, dateEt]);

  useEffect(() => {
    loadDay();
  }, [loadDay]);

  useEffect(() => {
    loadCashActivity();
  }, [loadCashActivity]);

  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const params = { period: dashPeriod, date: dateEt };
      if (dashPeriod === "custom") {
        params.start = customStart;
        params.end = customEnd;
      }
      const res = await getManagementRevenueDashboard(params);
      setDashboard(res.data || null);
    } catch {
      setDashboard(null);
    } finally {
      setDashLoading(false);
    }
  }, [customEnd, customStart, dashPeriod, dateEt]);

  useEffect(() => {
    if (view === "dashboard") loadDashboard();
  }, [view, loadDashboard]);

  const saveDhs = async () => {
    setSaving(true);
    setError("");
    try {
      const accounts = (data?.dhs?.accounts || []).map((row) => ({
        account_id: row.account_id,
        dr_commercial_account_id: row.dr_commercial_account_id,
        revenue_mode: row.revenue_mode,
        volume: parseMoneyInput(dhsDraft[row.account_id]?.volume),
        revenue: parseMoneyInput(dhsDraft[row.account_id]?.revenue),
      }));
      const res = await saveManagementRevenueDhs({ date_et: dateEt, accounts });
      applyPayload(res.data || {});
      setSuccess("DHS revenue saved");
      if (view === "dashboard") loadDashboard();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveNonRinse = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await saveManagementRevenueNonRinse({
        date_et: dateEt,
        self_service_cash: parseMoneyInput(ssCash),
        self_service_card: parseMoneyInput(ssCard),
        drop_off_cash: parseMoneyInput(doCash),
        drop_off_card: parseMoneyInput(doCard),
      });
      applyPayload(res.data || {});
      setSuccess("Revenue saved");
      loadCashActivity();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const submitPayout = async () => {
    setPayoutBusy(true);
    setError("");
    try {
      await createManagementCashPayout({
        date_et: dateEt,
        purpose: payoutPurpose.trim(),
        amount: parseMoneyInput(payoutAmount),
        note: payoutNote.trim() || null,
      });
      setPayoutOpen(false);
      setPayoutPurpose("");
      setPayoutAmount("");
      setPayoutNote("");
      await loadDay();
      await loadCashActivity();
      setSuccess("Cash payout recorded");
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Could not save payout");
    } finally {
      setPayoutBusy(false);
    }
  };

  const removePayout = async (id) => {
    setError("");
    try {
      await deleteManagementCashPayout(id);
      await loadDay();
      await loadCashActivity();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Could not delete payout");
    }
  };

  const hd = data?.rinse?.hd || {};
  const wf = data?.rinse?.wf || {};
  const cashDay = data?.cash_activity || {};
  const payouts = data?.cash_payouts || [];
  const dhsAccounts = data?.dhs?.accounts || [];

  return (
    <Box sx={{ maxWidth: 960, mx: "auto", px: { xs: 1.5, sm: 2 }, pb: 4 }}>
      <ManagementHubNav activeId="revenue" />

      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
        sx={{ py: 1.5 }}
      >
        <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>Revenue & Cash</Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          <Button component={RouterLink} to="/management/revenue-accounts" size="small" startIcon={<SettingsIcon />} variant="outlined">
            Accounts
          </Button>
          <PlanningDatePicker value={dateEt} onChange={setDateEt} label="Date (ET)" />
          <IconButton onClick={loadDay} disabled={loading} aria-label="Refresh">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      <Tabs value={view} onChange={(_, v) => setView(v)} sx={{ mb: 2 }}>
        <Tab value="entry" label="Daily Entry" />
        <Tab value="dashboard" label="Revenue Dashboard" />
      </Tabs>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>{error}</Alert> : null}
      {success ? <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setSuccess("")}>{success}</Alert> : null}

      {loading && view === "entry" ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : null}

      {view === "dashboard" ? (
        <Stack spacing={2} sx={{ maxWidth: 480 }}>
          <Tabs value={dashPeriod} onChange={(_, v) => setDashPeriod(v)} variant="scrollable">
            {DASH_PERIODS.map((p) => (
              <Tab key={p.id} value={p.id} label={p.label} />
            ))}
          </Tabs>
          {dashLoading ? <CircularProgress size={24} /> : (
            <SectionCard title="Total Revenue" subtitle={dashboard ? `${dashboard.start_date} → ${dashboard.end_date}` : ""}>
              <Typography sx={{ fontWeight: 900, fontSize: 28 }}>{fmtMoney(dashboard?.total_revenue)}</Typography>
              <Stack spacing={0.5} sx={{ mt: 1.5 }}>
                <Row label="Rinse WF" value={fmtMoney(dashboard?.rinse?.wf)} />
                <Row label="Rinse HD" value={fmtMoney(dashboard?.rinse?.hd)} />
                <Row label="Self Service" value={fmtMoney(dashboard?.non_rinse?.self_service)} />
                <Row label="Drop Off" value={fmtMoney(dashboard?.non_rinse?.drop_off)} />
                <Row label="DHS total" value={fmtMoney(dashboard?.dhs?.total)} bold />
                {Object.entries(dashboard?.dhs?.accounts || {}).map(([name, amt]) => (
                  <Row key={name} label={`  ${name}`} value={fmtMoney(amt)} />
                ))}
              </Stack>
            </SectionCard>
          )}
        </Stack>
      ) : null}

      {!loading && view === "entry" ? (
        <Stack spacing={1.5} sx={{ maxWidth: 390, width: "100%" }}>
          <Accordion defaultExpanded disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography sx={{ fontWeight: 800 }}>RINSE</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.5}>
                <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f8fafc", border: "1px solid #e5e7eb" }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>Rinse WF</Typography>
                  {wf.enabled ? (
                    <>
                      <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                        Monthly MTD tier · {wf.volume_lbs ?? 0} lb today
                      </Typography>
                      <Typography sx={{ fontWeight: 800, fontSize: 20, mt: 0.5 }}>{fmtMoney(wf.revenue)}</Typography>
                    </>
                  ) : (
                    <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.5 }}>
                      Enable tier pricing in Accounts & Pricing to calculate WF revenue.
                    </Typography>
                  )}
                </Box>
                <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f0f9ff", border: "1px solid #bae6fd" }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>Rinse HD</Typography>
                  <Typography sx={{ fontWeight: 800, fontSize: 20, mt: 0.5 }}>{fmtMoney(hd.revenue)}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    {hd.orders ?? 0} complete orders · from Management HD
                  </Typography>
                </Box>
              </Stack>
            </AccordionDetails>
          </Accordion>

          <Accordion defaultExpanded disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography sx={{ fontWeight: 800 }}>NON-RINSE REVENUE</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.5}>
                <Typography sx={{ fontWeight: 800, fontSize: 13 }}>Self Service</Typography>
                <MoneyField label="Cash" value={ssCash} onChange={setSsCash} />
                <MoneyField label="Card" value={ssCard} onChange={setSsCard} />
                <Typography sx={{ fontSize: 13, fontWeight: 700, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                  Total: {fmtMoney(nonRinseTotals.ss)}
                </Typography>
                <Typography sx={{ fontWeight: 800, fontSize: 13, pt: 0.5 }}>Drop Off</Typography>
                <MoneyField label="Cash" value={doCash} onChange={setDoCash} />
                <MoneyField label="Card" value={doCard} onChange={setDoCard} />
                <Typography sx={{ fontSize: 13, fontWeight: 700, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                  Total: {fmtMoney(nonRinseTotals.do)}
                </Typography>
                <Button variant="contained" onClick={saveNonRinse} disabled={saving} sx={{ fontWeight: 800, textTransform: "none" }}>
                  {saving ? "Saving…" : "Save Non-Rinse"}
                </Button>
              </Stack>
            </AccordionDetails>
          </Accordion>

          <Accordion defaultExpanded disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography sx={{ fontWeight: 800 }}>DHS</Typography>
            </AccordionSummary>
            <AccordionDetails>
              {!dhsAccounts.length ? (
                <Typography sx={{ fontSize: 13, color: "#64748b" }}>No DHS accounts configured.</Typography>
              ) : (
                <Stack spacing={1.25}>
                  {dhsAccounts.map((row) => {
                    const draft = dhsDraft[row.account_id] || {};
                    const isAbsolute = row.revenue_mode === "absolute";
                    return (
                      <Box key={row.account_id} sx={{ p: 1, borderRadius: 1, bgcolor: "#f8fafc" }}>
                        <Typography sx={{ fontWeight: 700 }}>{row.name}</Typography>
                        {!isAbsolute ? (
                          <MoneyField
                            label="Volume (lb)"
                            value={draft.volume ?? row.volume ?? ""}
                            onChange={(v) => setDhsDraft((p) => ({ ...p, [row.account_id]: { ...draft, volume: v } }))}
                          />
                        ) : null}
                        <MoneyField
                          label={isAbsolute ? "Revenue" : "Revenue override"}
                          value={draft.revenue ?? row.revenue ?? ""}
                          onChange={(v) => setDhsDraft((p) => ({ ...p, [row.account_id]: { ...draft, revenue: v } }))}
                        />
                        {!isAbsolute && row.pricing?.rate_per_unit != null ? (
                          <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                            Rate: ${row.pricing.rate_per_unit}/lb
                          </Typography>
                        ) : null}
                      </Box>
                    );
                  })}
                  <Button variant="contained" onClick={saveDhs} disabled={saving} sx={{ fontWeight: 800, textTransform: "none" }}>
                    {saving ? "Saving…" : "Save DHS"}
                  </Button>
                </Stack>
              )}
            </AccordionDetails>
          </Accordion>
          <Accordion disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ width: "100%" }}>
                <Typography sx={{ fontWeight: 800 }}>Cash Paid Out</Typography>
                <IconButton size="small" onClick={(e) => { e.stopPropagation(); setPayoutOpen(true); }} aria-label="Add payout">
                  <AddIcon fontSize="small" />
                </IconButton>
              </Stack>
            </AccordionSummary>
            <AccordionDetails>
            {!payouts.length ? (
              <Typography sx={{ fontSize: 13, color: "#64748b" }}>No payouts for this day.</Typography>
            ) : (
              <Stack spacing={1}>
                {payouts.map((p) => (
                  <Stack
                    key={p.id}
                    direction="row"
                    justifyContent="space-between"
                    alignItems="flex-start"
                    sx={{ p: 1, borderRadius: 1, bgcolor: "#f8fafc" }}
                  >
                    <Box sx={{ minWidth: 0, pr: 1 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{p.purpose}</Typography>
                      <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                        {fmtMoney(p.amount)}
                        {p.entered_by ? ` · ${p.entered_by}` : ""}
                      </Typography>
                      {p.note ? (
                        <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.25 }}>{p.note}</Typography>
                      ) : null}
                    </Box>
                    <IconButton size="small" onClick={() => removePayout(p.id)} aria-label="Delete payout">
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Stack>
                ))}
              </Stack>
            )}
            </AccordionDetails>
          </Accordion>

          <Accordion disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography sx={{ fontWeight: 800 }}>Cash Activity</Typography>
            </AccordionSummary>
            <AccordionDetails>
            <Tabs
              value={cashPeriod}
              onChange={(_, v) => setCashPeriod(v)}
              variant="scrollable"
              scrollButtons="auto"
              sx={{ mb: 1.5, minHeight: 36, "& .MuiTab-root": { minHeight: 36, fontWeight: 700, fontSize: 13 } }}
            >
              {CASH_PERIODS.map((p) => (
                <Tab key={p.id} value={p.id} label={p.label} />
              ))}
            </Tabs>
            {cashPeriod === "custom" ? (
              <Stack spacing={1} sx={{ mb: 1.5 }}>
                <PlanningDatePicker value={customStart} onChange={setCustomStart} label="Start (ET)" />
                <PlanningDatePicker value={customEnd} onChange={setCustomEnd} label="End (ET)" />
              </Stack>
            ) : null}
            {cashLoading ? (
              <CircularProgress size={24} />
            ) : (
              <Stack spacing={0.75}>
                <Row label="Self Service Cash" value={fmtMoney(cashActivity?.self_service_cash ?? cashDay.self_service_cash)} />
                <Row label="Drop Off Cash" value={fmtMoney(cashActivity?.drop_off_cash ?? cashDay.drop_off_cash)} />
                <Row label="Total Cash Revenue" value={fmtMoney(cashActivity?.total_cash_revenue ?? cashDay.total_cash_revenue)} bold />
                <Row label="Cash Paid Out" value={fmtMoney(cashActivity?.cash_paid_out ?? cashDay.cash_paid_out)} />
                <Row label="Net Cash Movement" value={fmtMoney(cashActivity?.net_cash_movement ?? cashDay.net_cash_movement)} bold accent />
              </Stack>
            )}
            </AccordionDetails>
          </Accordion>
        </Stack>
      ) : null}

      <Dialog open={payoutOpen} onClose={() => !payoutBusy && setPayoutOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Cash Paid Out</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <TextField
              label="Purpose"
              value={payoutPurpose}
              onChange={(e) => setPayoutPurpose(e.target.value)}
              fullWidth
              required
            />
            <TextField
              label="Amount"
              value={payoutAmount}
              onChange={(e) => setPayoutAmount(e.target.value)}
              fullWidth
              inputMode="decimal"
              required
            />
            <TextField
              label="Note (optional)"
              value={payoutNote}
              onChange={(e) => setPayoutNote(e.target.value)}
              fullWidth
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPayoutOpen(false)} disabled={payoutBusy}>Cancel</Button>
          <Button variant="contained" onClick={submitPayout} disabled={payoutBusy || !payoutPurpose.trim()}>
            {payoutBusy ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function Row({ label, value, bold, accent }) {
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center">
      <Typography sx={{ fontSize: 13, color: "#64748b", fontWeight: bold ? 700 : 500 }}>{label}</Typography>
      <Typography
        sx={{
          fontSize: bold ? 16 : 14,
          fontWeight: bold ? 800 : 700,
          color: accent ? VEEWASH_DASHBOARD.primaryBlueDark : "#0f172a",
        }}
      >
        {value}
      </Typography>
    </Stack>
  );
}
