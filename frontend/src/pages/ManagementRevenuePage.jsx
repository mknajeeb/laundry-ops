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
import {
  createManagementCashPayout,
  deleteManagementCashPayout,
  getManagementCashActivity,
  getManagementRevenue,
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

  const nonRinseTotals = useMemo(() => {
    const ss = parseMoneyInput(ssCash) + parseMoneyInput(ssCard);
    const dO = parseMoneyInput(doCash) + parseMoneyInput(doCard);
    return { ss, do: dO, total: ss + dO };
  }, [ssCash, ssCard, doCash, doCard]);

  const applyPayload = useCallback((payload) => {
    setData(payload);
    const nr = payload?.non_rinse || {};
    setSsCash(String(nr.self_service?.cash ?? ""));
    setSsCard(String(nr.self_service?.card ?? ""));
    setDoCash(String(nr.drop_off?.cash ?? ""));
    setDoCard(String(nr.drop_off?.card ?? ""));
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
          <PlanningDatePicker value={dateEt} onChange={setDateEt} label="Date (ET)" />
          <IconButton onClick={loadDay} disabled={loading} aria-label="Refresh">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>{error}</Alert> : null}
      {success ? <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setSuccess("")}>{success}</Alert> : null}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Stack spacing={2} sx={{ maxWidth: 390, mx: { xs: 0, md: 0 }, width: "100%" }}>
          <SectionCard title="RINSE" subtitle="Production revenue">
            <Stack spacing={1.5}>
              <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f8fafc", border: "1px dashed #cbd5e1" }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>Rinse WF Revenue</Typography>
                  <Chip size="small" label="Coming soon" />
                </Stack>
                <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.5 }}>
                  {wf.note || "Calculation logic will be supplied later."}
                </Typography>
              </Box>
              <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#f0f9ff", border: "1px solid #bae6fd" }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>Rinse HD Revenue</Typography>
                  <Chip size="small" label="From HD entry" color="info" variant="outlined" />
                </Stack>
                <Typography sx={{ fontWeight: 800, fontSize: 20, mt: 0.75 }}>{fmtMoney(hd.revenue)}</Typography>
                <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                  {hd.orders ?? 0} complete orders · enter details on Rinse HD
                </Typography>
              </Box>
            </Stack>
          </SectionCard>

          <SectionCard
            title="NON-RINSE"
            subtitle="Self Service & Drop Off — totals calculate automatically"
          >
            <Stack spacing={1.5}>
              <Typography sx={{ fontWeight: 800, fontSize: 13, color: "#475569" }}>Self Service</Typography>
              <MoneyField label="Cash" value={ssCash} onChange={setSsCash} />
              <MoneyField label="Card" value={ssCard} onChange={setSsCard} />
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                Total: {fmtMoney(nonRinseTotals.ss)}
              </Typography>

              <Typography sx={{ fontWeight: 800, fontSize: 13, color: "#475569", pt: 0.5 }}>Drop Off</Typography>
              <MoneyField label="Cash" value={doCash} onChange={setDoCash} />
              <MoneyField label="Card" value={doCard} onChange={setDoCard} />
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                Total: {fmtMoney(nonRinseTotals.do)}
              </Typography>

              <Button
                variant="contained"
                onClick={saveNonRinse}
                disabled={saving}
                sx={{ mt: 0.5, fontWeight: 800, textTransform: "none" }}
              >
                {saving ? "Saving…" : "Save Non-Rinse Revenue"}
              </Button>
            </Stack>
          </SectionCard>

          <SectionCard
            title="Cash Paid Out"
            subtitle="Not counted as negative revenue"
            action={
              <IconButton size="small" onClick={() => setPayoutOpen(true)} aria-label="Add payout">
                <AddIcon />
              </IconButton>
            }
          >
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
          </SectionCard>

          <SectionCard title="Cash Activity" subtitle="Net Cash Movement = cash revenue − paid out">
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
          </SectionCard>
        </Stack>
      )}

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
