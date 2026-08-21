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
  createManagementRevenueDisposition,
  deleteManagementCashPayout,
  getManagementCashActivity,
  getManagementRevenue,
  getManagementRevenueDashboard,
  getManagementRevenueMissingWork,
  saveManagementRevenueDhs,
  saveManagementRevenueNonRinse,
  saveManagementRevenueWf,
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
import DailyCompletenessStrip from "../components/revenueShared/DailyCompletenessStrip";
import MissingWorkPanel from "../components/revenueShared/MissingWorkPanel";
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

  const [missingFilter, setMissingFilter] = useState("all");
  const [missing, setMissing] = useState(null);
  const [missingLoading, setMissingLoading] = useState(false);
  const [dispBusy, setDispBusy] = useState("");
  const [focusAccountId, setFocusAccountId] = useState(null);
  const [focusWf, setFocusWf] = useState(false);

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

  const loadMissing = useCallback(async () => {
    setMissingLoading(true);
    try {
      const res = await getManagementRevenueMissingWork({
        date_et: dateEt,
        filter: missingFilter,
      });
      setMissing(res.data || null);
    } catch {
      setMissing(null);
    } finally {
      setMissingLoading(false);
    }
  }, [dateEt, missingFilter]);

  useEffect(() => {
    loadDay();
  }, [loadDay]);

  useEffect(() => {
    if (view === "cash" || view === "dashboard") loadCashActivity();
  }, [loadCashActivity, view]);

  useEffect(() => {
    if (view === "dashboard") loadDashboard();
  }, [view, loadDashboard]);

  useEffect(() => {
    loadMissing();
  }, [loadMissing]);

  const openMissingItem = (item) => {
    setView("entry");
    if (item.kind === "dhs") {
      setFocusAccountId(item.account_id || null);
      setFocusWf(false);
      setDrawerGroup("dhs");
      return;
    }
    setFocusAccountId(null);
    if (item.source_key === "self_service" || item.source_key === "drop_off") {
      setFocusWf(false);
      setDrawerGroup("non_rinse");
      return;
    }
    if (item.source_key === "rinse_wf") {
      setFocusWf(true);
      setDrawerGroup("rinse");
      return;
    }
    if (item.source_key === "rinse_hd") {
      setFocusWf(false);
      setDrawerGroup("rinse");
    }
  };

  const postDisposition = async (body, busyKey) => {
    setDispBusy(busyKey);
    setError("");
    try {
      await createManagementRevenueDisposition(body);
      setSuccess("Disposition saved");
      await loadDay();
      await loadMissing();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Disposition failed");
    } finally {
      setDispBusy("");
    }
  };
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

  const saveWf = async (fields) => {
    setSaving(true);
    setError("");
    try {
      const res = await saveManagementRevenueWf({
        date_et: dateEt,
        processing_date: dateEt,
        volume_lbs: fields.volume_lbs,
        revenue: fields.revenue,
        use_revenue_override: fields.use_revenue_override,
      });
      applyPayload(res.data || {});
      setSuccess("Rinse WF saved");
      loadCashActivity();
      await loadMissing();
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "WF save failed");
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
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 2, minHeight: 40, "& .MuiTab-root": { minHeight: 40, fontWeight: 800, textTransform: "none" } }}
      >
        <Tab value="entry" label="Daily" />
        <Tab
          value="missing"
          label={`Missing Work${missing?.summary?.missing_total != null ? ` · ${missing.summary.missing_total}` : ""}`}
        />
        <Tab value="cash" label="Cash" />
        <Tab value="dashboard" label="Stats" />
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

      {view === "missing" ? (
        <MissingWorkPanel
          loading={missingLoading}
          data={missing}
          filter={missingFilter}
          onFilterChange={setMissingFilter}
          onOpenItem={openMissingItem}
          busyId={dispBusy}
          onNoActivity={(item, reason) =>
            postDisposition(
              {
                source_key: item.source_key,
                processing_date_et: item.processing_date_et || dateEt,
                disposition: "no_activity",
                reason,
              },
              `${item.source_key}:${item.processing_date_et}`,
            )
          }
          onNoPickup={(item, reason) =>
            postDisposition(
              {
                source_key: item.source_key,
                account_id: item.account_id,
                scheduled_pickup_date: item.scheduled_pickup_date,
                scheduled_delivery_date: item.scheduled_delivery_date,
                disposition: "no_pickup",
                reason,
              },
              `${item.source_key}:${item.scheduled_pickup_date}`,
            )
          }
          onReschedule={(item, reason) => {
            const next = window.prompt("New Pickup Date (YYYY-MM-DD)", item.scheduled_pickup_date);
            if (!next) return;
            postDisposition(
              {
                source_key: item.source_key,
                account_id: item.account_id,
                scheduled_pickup_date: item.scheduled_pickup_date,
                scheduled_delivery_date: item.scheduled_delivery_date,
                disposition: "rescheduled",
                new_pickup_date: next,
                reason,
              },
              `${item.source_key}:${item.scheduled_pickup_date}`,
            );
          }}
        />
      ) : null}

      {view === "entry" && loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : null}

      {view === "entry" && !loading ? (
        <Stack spacing={1.75}>
          <DailyCompletenessStrip
            completeness={data?.daily_completeness}
            dhsDay={data?.dhs_day || data?.dhs_completeness}
            amounts={{
              self_service: data?.non_rinse?.self_service?.total,
              drop_off: data?.non_rinse?.drop_off?.total,
              rinse_wf: data?.rinse?.wf?.revenue,
              rinse_hd: data?.rinse?.hd?.revenue,
            }}
            cashAmount={data?.cash_activity?.cash_paid_out}
            onOpenCash={() => {
              setPayoutDate(dateEt);
              setPayoutOpen(true);
            }}
            onOpenSection={(s) => {
              if (s.key === "self_service" || s.key === "drop_off") setDrawerGroup("non_rinse");
              else setDrawerGroup("rinse");
            }}
            onOpenDhsAccount={() => setDrawerGroup("dhs")}
          />

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
              border: "1px solid #e5e7eb",
              borderRadius: 2,
              bgcolor: "#fff",
              p: 2,
              boxShadow: VEEWASH_DASHBOARD.cardShadow,
            }}
          >
            <Typography sx={{ fontWeight: 800, fontSize: 15, mb: 1 }}>Daily closeout</Typography>
            <Typography sx={{ fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>
              Self Service, Drop Off, Rinse WF, and Rinse HD only. DHS and Cash Paid Out are separate tabs.
              Blank is never treated as $0.
            </Typography>
            {data?.missing_work_summary ? (
              <Typography sx={{ mt: 1, fontSize: 13, fontWeight: 700, color: "#d97706" }}>
                Missing: {data.missing_work_summary.missing_total} ({data.missing_work_summary.daily_missing}{" "}
                daily · {data.missing_work_summary.dhs_pending} DHS)
              </Typography>
            ) : null}
          </Box>
        </Stack>
      ) : null}

      {view === "cash" ? (
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
      ) : null}

      <RevenueAccountDrawer
        open={Boolean(drawerGroup)}
        groupId={drawerGroup}
        data={data}
        dateEt={dateEt}
        saving={saving}
        focusAccountId={focusAccountId}
        focusWf={focusWf}
        onClose={() => {
          setDrawerGroup(null);
          setFocusAccountId(null);
          setFocusWf(false);
        }}
        onSaveNonRinse={saveNonRinse}
        onSaveWf={saveWf}
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
