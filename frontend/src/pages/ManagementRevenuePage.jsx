import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import SettingsIcon from "@mui/icons-material/Settings";
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
import CashActivityPanel from "../components/management/revenue/CashActivityPanel";
import CashPayoutDialog from "../components/management/revenue/CashPayoutDialog";
import RevenueAccountDrawer from "../components/management/revenue/RevenueAccountDrawer";
import RevenueDashboardPanel from "../components/management/revenue/RevenueDashboardPanel";
import RevenueSummaryStrip, {
  RevenueGroupCards,
} from "../components/management/revenue/RevenueSummaryStrip";
import {
  parseMoneyInput,
  todayEtIso,
} from "../components/management/revenue/revenueFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

export default function ManagementRevenuePage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [data, setData] = useState(null);

  const [view, setView] = useState("entry");
  const [drawerGroup, setDrawerGroup] = useState(null);

  const [cashPeriod, setCashPeriod] = useState("today");
  const [cashActivity, setCashActivity] = useState(null);
  const [cashLoading, setCashLoading] = useState(false);
  const [customStart, setCustomStart] = useState(todayEtIso);
  const [customEnd, setCustomEnd] = useState(todayEtIso);

  const [payoutOpen, setPayoutOpen] = useState(false);
  const [payoutDate, setPayoutDate] = useState(todayEtIso);
  const [payoutPurpose, setPayoutPurpose] = useState("");
  const [payoutAmount, setPayoutAmount] = useState("");
  const [payoutNote, setPayoutNote] = useState("");
  const [payoutBusy, setPayoutBusy] = useState(false);

  const [dashPeriod, setDashPeriod] = useState("week");
  const [dashboard, setDashboard] = useState(null);
  const [dashLoading, setDashLoading] = useState(false);

  const applyPayload = useCallback((payload) => {
    setData(payload);
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
    loadDay();
  }, [loadDay]);

  useEffect(() => {
    loadCashActivity();
  }, [loadCashActivity]);

  useEffect(() => {
    if (view === "dashboard") loadDashboard();
  }, [view, loadDashboard]);

  const saveNonRinse = async (fields) => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const body = { date_et: dateEt };
      for (const key of ["self_service_cash", "self_service_card", "drop_off_cash", "drop_off_card"]) {
        if (fields[key] !== undefined) body[key] = fields[key];
      }
      const res = await saveManagementRevenueNonRinse(body);
      applyPayload(res.data || {});
      setSuccess("Non-Rinse saved");
      loadCashActivity();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveDhsAccount = async (accountBody) => {
    setSaving(true);
    setError("");
    try {
      const res = await saveManagementRevenueDhs({
        date_et: dateEt,
        accounts: [accountBody],
      });
      applyPayload(res.data || {});
      setSuccess(`${accountBody.name || "Account"} saved`);
      if (view === "dashboard") loadDashboard();
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
        payout_business_date: payoutDate,
        date_et: payoutDate,
        purpose: payoutPurpose.trim(),
        amount: parseMoneyInput(payoutAmount),
        note: payoutNote.trim() || null,
      });
      setPayoutOpen(false);
      setPayoutPurpose("");
      setPayoutAmount("");
      setPayoutNote("");
      setPayoutDate(dateEt);
      await loadDay();
      await loadCashActivity();
      if (view === "dashboard") loadDashboard();
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
      if (view === "dashboard") loadDashboard();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Could not delete payout");
    }
  };

  const cashDay = data?.cash_activity || {};
  const groups = data?.groups || [];

  return (
    <Box
      sx={{
        maxWidth: 1280,
        mx: "auto",
        px: { xs: 1.25, sm: 2 },
        pb: 5,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <ManagementHubNav activeId="revenue" />

      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
        sx={{
          py: 1.5,
          position: { xs: "sticky", md: "static" },
          top: 0,
          zIndex: 3,
          bgcolor: VEEWASH_DASHBOARD.pageBackground,
        }}
      >
        <Typography sx={{ fontSize: { xs: 20, sm: 22 }, fontWeight: 800, lineHeight: 1.1 }}>
          Revenue & Cash
        </Typography>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Button
            component={RouterLink}
            to="/management/revenue-accounts"
            size="small"
            startIcon={<SettingsIcon />}
            variant="outlined"
            sx={{ textTransform: "none", fontWeight: 700 }}
          >
            Accounts & Pricing
          </Button>
          <PlanningDatePicker value={dateEt} onChange={setDateEt} label="Date (ET)" />
          <IconButton onClick={loadDay} disabled={loading} aria-label="Refresh">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      <Tabs
        value={view}
        onChange={(_, v) => setView(v)}
        sx={{ mb: 2, minHeight: 40, "& .MuiTab-root": { minHeight: 40, fontWeight: 800, textTransform: "none" } }}
      >
        <Tab value="entry" label="Daily Entry" />
        <Tab value="dashboard" label="Dashboard" />
      </Tabs>

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

      {view === "dashboard" ? (
        <RevenueDashboardPanel
          period={dashPeriod}
          onPeriodChange={setDashPeriod}
          customStart={customStart}
          customEnd={customEnd}
          onCustomStart={setCustomStart}
          onCustomEnd={setCustomEnd}
          loading={dashLoading}
          dashboard={dashboard}
        />
      ) : null}

      {view === "entry" && loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : null}

      {view === "entry" && !loading ? (
        <Stack spacing={1.75}>
          <RevenueSummaryStrip
            data={data}
            cashDay={cashDay}
            onOpenCashOut={() => {
              setPayoutDate(dateEt);
              setPayoutOpen(true);
            }}
            onOpenGroup={setDrawerGroup}
          />

          <RevenueGroupCards groups={groups} onOpenGroup={setDrawerGroup} />

          <Box
            sx={{
              display: "grid",
              gap: 1.5,
              gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
            }}
          >
            <CashActivityPanel
              period={cashPeriod}
              onPeriodChange={setCashPeriod}
              customStart={customStart}
              customEnd={customEnd}
              onCustomStart={setCustomStart}
              onCustomEnd={setCustomEnd}
              loading={cashLoading}
              activity={cashActivity}
              onAddPayout={() => {
                setPayoutDate(dateEt);
                setPayoutOpen(true);
              }}
              onDeletePayout={removePayout}
            />
            <Box
              sx={{
                border: "1px solid #e5e7eb",
                borderRadius: 2,
                bgcolor: "#fff",
                p: 2,
                boxShadow: VEEWASH_DASHBOARD.cardShadow,
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: 15, mb: 1 }}>How to enter</Typography>
              <Typography sx={{ fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>
                Tap a revenue group card to open accounts. DHS accounts open one at a time — only the
                fields that account needs. Blank means not entered; type 0 only when you mean zero.
              </Typography>
            </Box>
          </Box>
        </Stack>
      ) : null}

      <RevenueAccountDrawer
        open={Boolean(drawerGroup)}
        groupId={drawerGroup}
        data={data}
        dateEt={dateEt}
        saving={saving}
        onClose={() => setDrawerGroup(null)}
        onSaveNonRinse={saveNonRinse}
        onSaveDhsAccount={saveDhsAccount}
      />

      <CashPayoutDialog
        open={payoutOpen}
        busy={payoutBusy}
        payoutDate={payoutDate}
        purpose={payoutPurpose}
        amount={payoutAmount}
        note={payoutNote}
        onChange={(patch) => {
          if (patch.payoutDate != null) setPayoutDate(patch.payoutDate);
          if (patch.purpose != null) setPayoutPurpose(patch.purpose);
          if (patch.amount != null) setPayoutAmount(patch.amount);
          if (patch.note != null) setPayoutNote(patch.note);
        }}
        onClose={() => setPayoutOpen(false)}
        onSubmit={submitPayout}
      />
    </Box>
  );
}
