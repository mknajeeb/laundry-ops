import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  createManagementCashPayout,
  createManagementRevenueDisposition,
  deleteManagementCashPayout,
  getManagementRevenueBootstrap,
  getManagementRevenueCashTab,
  getManagementRevenueDaily,
  getManagementRevenueDhsBoard,
  getManagementRevenueSchedulePreview,
  getManagementRevenueStreamTab,
  getManagementRinseHd,
  postManagementRevenueDhsManualPickup,
  saveManagementRevenueDhs,
  saveManagementRevenueNonRinse,
  saveManagementRevenueWf,
  updateManagementCashPayout,
} from "../api";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import CashLedgerPanel from "../components/revenueShared/CashLedgerPanel";
import DhsAccountSheet from "../components/revenueShared/DhsAccountSheet";
import DhsScheduleBoard from "../components/revenueShared/DhsScheduleBoard";
import RevenueOverviewHome from "../components/revenueShared/RevenueOverviewHome";
import RevenueSectionNav from "../components/revenueShared/RevenueSectionNav";
import StreamEntryHome from "../components/revenueShared/StreamEntryHome";
import {
  fmtMoney,
  moneyToInput,
  parseMoneyInput,
  todayEtIso,
} from "../components/revenueShared/revenueFormat";
import HdMobileAwaitingEntryPanel from "./HdMobileAwaitingEntryPanel";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { useI18n } from "../i18n/I18nContext";

function formatHomeDate(iso) {
  try {
    const [y, m, d] = String(iso).split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

const SCREEN_TITLE_KEYS = {
  home: "mobileOps.revenue.title",
  self_service: "mobileOps.revenue.selfService",
  drop_off: "mobileOps.revenue.dropOff",
  dhs: "mobileOps.revenue.dhs",
  dhs_account: "mobileOps.revenue.dhs",
  cash: "mobileOps.revenue.cashPaidOut",
  hang_dry: "mobileOps.revenue.hangDry",
  rinse_wf: "mobileOps.revenue.rinseWf",
  missing: "mobileOps.revenue.missingWork",
};

/**
 * Employee PIN Revenue / Cash — shared Management APIs + shared entry components.
 * Hang Dry uses the canonical HD workflow APIs (Awaiting Entry → Complete).
 */
export default function PinRevenueCashFlow({ onBack, onLock }) {
  const { t } = useI18n();
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [mainTab, setMainTab] = useState("overview");
  const [period, setPeriod] = useState("month");
  const [streamTab, setStreamTab] = useState(null);
  const [streamLoading, setStreamLoading] = useState(false);
  const [periodMenu, setPeriodMenu] = useState(false);
  const [screen, setScreen] = useState("home");
  const [dashPeriod, setDashPeriod] = useState("week");
  const [dashboard, setDashboard] = useState(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [customStart, setCustomStart] = useState(todayEtIso);
  const [customEnd, setCustomEnd] = useState(todayEtIso);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState("");
  const [data, setData] = useState(null);

  const [ssCash, setSsCash] = useState(null);
  const [ssCard, setSsCard] = useState(null);
  const [doCash, setDoCash] = useState(null);
  const [doCard, setDoCard] = useState(null);

  const [dhsAccount, setDhsAccount] = useState(null);
  const [dhsOccurrence, setDhsOccurrence] = useState(null);
  const [dhsDraft, setDhsDraft] = useState({});

  const [hdList, setHdList] = useState(null);
  const [hdLoading, setHdLoading] = useState(false);
  const [hdListError, setHdListError] = useState("");

  const [missingFilter, setMissingFilter] = useState("all");
  const [missing, setMissing] = useState(null);
  const [missingLoading, setMissingLoading] = useState(false);
  const [dispBusy, setDispBusy] = useState("");
  const [returnScreen, setReturnScreen] = useState("home");
  const [wfVolume, setWfVolume] = useState(null);
  const [dhsBoard, setDhsBoard] = useState(null);
  const [dhsLoading, setDhsLoading] = useState(false);
  const [cashTab, setCashTab] = useState(null);
  const [cashLoading, setCashLoading] = useState(false);

  const nonRinseRef = useRef({ ssCash: null, ssCard: null, doCash: null, doCard: null });
  const autosaveTimerRef = useRef(null);
  const dhsAutosaveTimerRef = useRef(null);
  const saveGenRef = useRef(0);
  const scheduleCacheRef = useRef({});
  const dhsPendingBodyRef = useRef(null);
  const loadedTabsRef = useRef({ missing: false, dhs: false, cash: false, stats: false });
  nonRinseRef.current = { ssCash, ssCard, doCash, doCard };

  const applyDayPayload = useCallback((payload) => {
    setData((prev) => ({ ...(prev || {}), ...(payload || {}) }));
    const nr = payload?.non_rinse || payload?.non_rinse_revenue || {};
    if (nr.self_service || nr.drop_off) {
      setSsCash(moneyToInput(nr.self_service?.cash) === "" ? null : nr.self_service?.cash);
      setSsCard(moneyToInput(nr.self_service?.card) === "" ? null : nr.self_service?.card);
      setDoCash(moneyToInput(nr.drop_off?.cash) === "" ? null : nr.drop_off?.cash);
      setDoCard(moneyToInput(nr.drop_off?.card) === "" ? null : nr.drop_off?.card);
    }
  }, []);

  const loadRevenue = useCallback(async () => {
    setLoading(true);
    setError("");
    loadedTabsRef.current = { missing: false, dhs: false, cash: false, stats: false };
    try {
      const res = await getManagementRevenueBootstrap(dateEt);
      const boot = res.data || {};
      applyDayPayload({
        date_et: boot.date_et,
        daily_completeness: boot.daily_completeness,
        non_rinse: boot.non_rinse,
        rinse: boot.rinse,
        cash_activity: boot.cash_today
          ? {
              total_cash_revenue: boot.cash_today.cash_received,
              cash_paid_out: boot.cash_today.cash_paid_out,
              net_cash_movement: boot.cash_today.net_cash,
            }
          : null,
      });
      setMissing({ summary: boot.badges || {}, items: [], groups: [] });
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [applyDayPayload, dateEt, t]);

  const loadDailyTab = useCallback(async () => {
    try {
      const res = await getManagementRevenueDaily(dateEt);
      applyDayPayload(res.data || {});
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    }
  }, [applyDayPayload, dateEt, t]);

  const loadDhsTab = useCallback(async () => {
    setDhsLoading(true);
    try {
      const res = await getManagementRevenueDhsBoard(dateEt);
      setDhsBoard(res.data || null);
      loadedTabsRef.current.dhs = true;
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setDhsLoading(false);
    }
  }, [dateEt, t]);

  const loadCashTab = useCallback(async () => {
    setCashLoading(true);
    try {
      const res = await getManagementRevenueCashTab(dateEt, { period });
      setCashTab(res.data || null);
      loadedTabsRef.current.cash = true;
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setCashLoading(false);
    }
  }, [dateEt, period, t]);

  const loadStreamTab = useCallback(async (stream) => {
    if (!stream || stream === "dhs" || stream === "cash") return;
    setStreamLoading(true);
    try {
      const res = await getManagementRevenueStreamTab(stream, dateEt, { period });
      setStreamTab(res.data || null);
      const nr = res.data?.non_rinse || {};
      if (stream === "self_service") {
        setSsCash(moneyToInput(nr.self_service?.cash) === "" ? null : nr.self_service?.cash);
        setSsCard(moneyToInput(nr.self_service?.card) === "" ? null : nr.self_service?.card);
      }
      if (stream === "drop_off") {
        setDoCash(moneyToInput(nr.drop_off?.cash) === "" ? null : nr.drop_off?.cash);
        setDoCard(moneyToInput(nr.drop_off?.card) === "" ? null : nr.drop_off?.card);
      }
      if (stream === "rinse_wf") {
        const wf = res.data?.rinse?.wf;
        setWfVolume(wf?.volume_lbs != null ? String(wf.volume_lbs) : "");
      }
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setStreamLoading(false);
    }
  }, [dateEt, period, t]);

  useEffect(() => {
    loadRevenue();
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [loadRevenue]);

  useEffect(() => {
    if (mainTab === "dhs" || mainTab === "overview") loadDhsTab();
  }, [mainTab, loadDhsTab]);

  useEffect(() => {
    if (mainTab === "cash" || mainTab === "overview") loadCashTab();
  }, [mainTab, loadCashTab]);

  useEffect(() => {
    if (["self_service", "drop_off", "rinse_wf", "rinse_hd"].includes(mainTab)) {
      loadStreamTab(mainTab);
    }
  }, [mainTab, loadStreamTab]);

  const flushNonRinse = useCallback(async () => {
    const gen = ++saveGenRef.current;
    const vals = nonRinseRef.current;
    setSaveState("saving");
    try {
      const body = { date_et: dateEt };
      if (screen === "self_service" || screen === "home") {
        body.self_service_cash = parseMoneyInput(vals.ssCash);
        body.self_service_card = parseMoneyInput(vals.ssCard);
      }
      if (screen === "drop_off" || screen === "home") {
        body.drop_off_cash = parseMoneyInput(vals.doCash);
        body.drop_off_card = parseMoneyInput(vals.doCard);
      }
      // Always send the section being edited; skip nulls so blank ≠ overwrite with 0
      const payload = { date_et: dateEt };
      if (screen === "self_service") {
        if (vals.ssCash !== undefined) payload.self_service_cash = parseMoneyInput(vals.ssCash);
        if (vals.ssCard !== undefined) payload.self_service_card = parseMoneyInput(vals.ssCard);
      } else if (screen === "drop_off") {
        if (vals.doCash !== undefined) payload.drop_off_cash = parseMoneyInput(vals.doCash);
        if (vals.doCard !== undefined) payload.drop_off_card = parseMoneyInput(vals.doCard);
      } else {
        payload.self_service_cash = parseMoneyInput(vals.ssCash);
        payload.self_service_card = parseMoneyInput(vals.ssCard);
        payload.drop_off_cash = parseMoneyInput(vals.doCash);
        payload.drop_off_card = parseMoneyInput(vals.doCard);
      }
      const res = await saveManagementRevenueNonRinse(payload);
      if (gen !== saveGenRef.current) return;
      applyDayPayload(res.data || null);
      setSaveState("saved");
    } catch (e) {
      if (gen !== saveGenRef.current) return;
      setSaveState("error");
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    }
  }, [applyDayPayload, dateEt, screen, t]);

  const scheduleNonRinseAutosave = useCallback(() => {
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      autosaveTimerRef.current = null;
      flushNonRinse();
    }, 650);
  }, [flushNonRinse]);

  const setSsCashField = (v) => {
    setSsCash(v);
    scheduleNonRinseAutosave();
  };
  const setSsCardField = (v) => {
    setSsCard(v);
    scheduleNonRinseAutosave();
  };
  const setDoCashField = (v) => {
    setDoCash(v);
    scheduleNonRinseAutosave();
  };
  const setDoCardField = (v) => {
    setDoCard(v);
    scheduleNonRinseAutosave();
  };

  const flushPendingNonRinse = useCallback(async () => {
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    await flushNonRinse();
  }, [flushNonRinse]);

  const completeDailySection = useCallback(
    async (sourceKey) => {
      setError("");
      setDispBusy(`${sourceKey}:${dateEt}`);
      try {
        if (sourceKey === "self_service" || sourceKey === "drop_off") {
          await flushPendingNonRinse();
        }
        if (sourceKey === "rinse_wf") {
          const vol = parseMoneyInput(wfVolume);
          if (vol == null) throw new Error("Enter WF volume before Complete");
          const res = await saveManagementRevenueWf({ date_et: dateEt, volume_lbs: vol });
          applyDayPayload(res.data || null);
        }
        await createManagementRevenueDisposition({
          source_key: sourceKey,
          processing_date_et: dateEt,
          disposition: "completed",
        });
        await loadRevenue();
        setSaveState("saved");
        setScreen("home");
        setMainTab("overview");
      } catch (e) {
        setSaveState("error");
        setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
      } finally {
        setDispBusy("");
      }
    },
    [applyDayPayload, dateEt, flushPendingNonRinse, loadRevenue, t, wfVolume],
  );

  const openDhsAccount = async (row, { fromScreen, obligation } = {}) => {
    if (fromScreen) setReturnScreen(fromScreen);
    else if (mainTab === "missing") setReturnScreen("missing");
    else setReturnScreen("dhs");
    const accountRow =
      row ||
      (data?.dhs?.accounts || []).find((a) => a.account_id === obligation?.account_id) ||
      {
        account_id: obligation?.account_id,
        name: obligation?.name,
        dr_commercial_account_id: obligation?.dr_commercial_account_id,
        revenue_mode: obligation?.revenue_mode,
        allow_override: obligation?.allow_override,
        use_pickup_date: obligation?.use_pickup_date,
        use_processing_date: obligation?.use_processing_date,
        use_delivery_date: obligation?.use_delivery_date,
      };
    setDhsOccurrence(obligation || null);
    setDhsAccount(accountRow);
    let pickup = accountRow.pickup_date || obligation?.scheduled_pickup_date || "";
    let delivery = accountRow.delivery_date || "";
    let scheduledPickup = obligation?.scheduled_pickup_date || "";
    let scheduledDelivery = obligation?.scheduled_delivery_date || "";
    const cacheKey = `${accountRow.account_id}:${dateEt}`;
    try {
      let defaults = scheduleCacheRef.current[cacheKey];
      if (!defaults) {
        const res = await getManagementRevenueSchedulePreview(accountRow.account_id, {
          processing_date: dateEt,
        });
        defaults = res.data?.defaults || {};
        scheduleCacheRef.current[cacheKey] = defaults;
      }
      scheduledPickup = scheduledPickup || defaults.scheduled_pickup_date || "";
      scheduledDelivery = scheduledDelivery || defaults.scheduled_delivery_date || "";
      if (!pickup && accountRow.use_pickup_date) pickup = defaults.pickup_date || scheduledPickup || "";
      if (!delivery && accountRow.use_delivery_date) delivery = defaults.delivery_date || "";
    } catch {
      /* ignore */
    }
    setDhsDraft({
      volume: moneyToInput(accountRow.volume) === "" ? null : accountRow.volume,
      revenue: moneyToInput(accountRow.revenue) === "" ? null : accountRow.revenue,
      pickup_date: pickup,
      processing_date:
        accountRow.processing_date ||
        obligation?.suggested_processing_date ||
        (accountRow.use_processing_date !== false ? dateEt : ""),
      delivery_date: delivery,
      scheduled_pickup_date: scheduledPickup,
      scheduled_delivery_date: scheduledDelivery,
      use_revenue_override: Boolean(accountRow.use_revenue_override),
    });
    setScreen("dhs_account");
    setSaveState("");
  };

  const postDisposition = async (body, busyKey) => {
    setDispBusy(busyKey);
    setError("");
    try {
      await createManagementRevenueDisposition(body);
      await loadRevenue();
      setSaveState("saved");
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    } finally {
      setDispBusy("");
    }
  };

  const saveDhsAccount = async (body, { finalize = false } = {}) => {
    setSaveState("saving");
    setError("");
    try {
      const res = await saveManagementRevenueDhs({
        date_et: dateEt,
        accounts: [body],
      });
      applyDayPayload(res.data || null);
      const updated = (res.data?.dhs?.accounts || []).find((a) => a.account_id === body.account_id);
      if (updated) setDhsAccount(updated);
      if (finalize) {
        const pickup = body.scheduled_pickup_date || body.pickup_date;
        if (!pickup) throw new Error("Pickup date required to Complete");
        await createManagementRevenueDisposition({
          source_key: `dhs:${body.account_id}`,
          account_id: body.account_id,
          scheduled_pickup_date: pickup,
          scheduled_delivery_date: body.scheduled_delivery_date || body.delivery_date || null,
          processing_date_et: body.processing_date || dateEt,
          disposition: "completed",
        });
        await loadRevenue();
        setScreen("home");
        setMainTab("overview");
      }
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    }
  };

  const scheduleDhsAutosave = (body) => {
    dhsPendingBodyRef.current = body;
    if (dhsAutosaveTimerRef.current) clearTimeout(dhsAutosaveTimerRef.current);
    dhsAutosaveTimerRef.current = setTimeout(() => {
      dhsAutosaveTimerRef.current = null;
      const pending = dhsPendingBodyRef.current;
      if (pending) saveDhsAccount(pending, { finalize: false });
    }, 650);
  };

  const completeDhsAccount = async (body) => {
    if (dhsAutosaveTimerRef.current) {
      clearTimeout(dhsAutosaveTimerRef.current);
      dhsAutosaveTimerRef.current = null;
    }
    await saveDhsAccount(body, { finalize: true });
  };

  const loadHangDry = async ({ quiet = false } = {}) => {
    if (!quiet) setHdLoading(true);
    setHdListError("");
    if (!quiet) setError("");
    try {
      // Mobile HD is data-entry only: Folded / Awaiting Entry orders.
      const res = await getManagementRinseHd(dateEt, { status: "awaiting_entry", mobile: 1 });
      setHdList(res.data || null);
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadHdFailed");
      if (!quiet) setError(msg);
      setHdListError(msg);
      if (!quiet) setHdList(null);
    } finally {
      if (!quiet) setHdLoading(false);
    }
  };

  const openHangDry = async () => {
    setScreen("hang_dry");
    await loadHangDry();
  };

  const handleTopBack = () => {
    if (screen === "home") {
      onBack?.();
      return;
    }
    if (screen === "dhs_account") {
      if (returnScreen === "missing") {
        setMainTab("missing");
      } else {
        setMainTab("dhs");
      }
      setScreen("home");
      setDhsAccount(null);
      setDhsOccurrence(null);
      return;
    }
    if (screen === "self_service" || screen === "drop_off") {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
        flushNonRinse();
      }
    }
    setMainTab("overview");
    setScreen("home");
    setAddingPayout(false);
    loadRevenue();
  };

  const saveLabels = {
    saving: t("mobileOps.revenue.saving"),
    saved: t("mobileOps.revenue.savedCheck"),
    error: t("mobileOps.revenue.saveFailed"),
  };

  const nr = data?.non_rinse || {};
  const hd = data?.rinse?.hd || {};

  const title = t(SCREEN_TITLE_KEYS[screen] || "mobileOps.revenue.title");
  const backLabel = screen === "home" ? t("mobileOps.backPin") : t("mobileOps.back");

  return (
    <OpsMobileShell
      maxWidth={960}
      sx={{
        px: { xs: 1.5, sm: 2, md: 3 },
        py: { xs: 1.5, sm: 2 },
      }}
      contentSx={{
        maxWidth: { xs: 560, sm: 720, md: 960 },
      }}
    >
      <OpsTopBar
        title={title}
        onBack={handleTopBack}
        backLabel={backLabel}
        onLock={onLock}
        lockLabel={t("mobileOps.lock")}
        right={<OpsLocaleToggle />}
      />

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {!["dhs_account", "hang_dry"].includes(screen) ? (
        <Box
          sx={{
            position: "sticky",
            top: 0,
            zIndex: 3,
            bgcolor: "#F3F7F8",
            pt: 0.5,
            pb: 0.75,
            mb: 1,
          }}
        >
          <RevenueSectionNav
            value={mainTab}
            onChange={(id) => {
              setMainTab(id);
              setSaveState("");
              setScreen("home");
              if (id === "rinse_hd") openHangDry();
            }}
          />
          {periodMenu ? (
            <TextField
              select
              size="small"
              fullWidth
              label="Summary period"
              value={period}
              onChange={(e) => {
                setPeriod(e.target.value);
                setPeriodMenu(false);
              }}
              sx={{ mt: 1 }}
            >
              <MenuItem value="today">Today</MenuItem>
              <MenuItem value="week">This Week</MenuItem>
              <MenuItem value="month">This Month</MenuItem>
              <MenuItem value="previous_month">Previous Month</MenuItem>
            </TextField>
          ) : null}
        </Box>
      ) : null}

      {mainTab === "overview" && screen === "home" ? (
        <RevenueOverviewHome
          dateEt={dateEt}
          dateLabel={formatHomeDate(dateEt)}
          loading={loading}
          nonRinse={nr}
          rinse={data?.rinse}
          cashToday={data?.cash_activity}
          dailyCompleteness={data?.daily_completeness}
          dhsBoard={dhsBoard}
          cashTab={cashTab}
          t={t}
          onDateChange={(v) => {
            if (v) setDateEt(v);
          }}
          onOpenSection={(id) => {
            setMainTab(id);
            setScreen("home");
            if (id === "rinse_hd") openHangDry();
          }}
        />
      ) : null}

      {["self_service", "drop_off", "rinse_wf"].includes(mainTab) &&
      (screen === mainTab || screen === "home") ? (
        <StreamEntryHome
          stream={mainTab}
          periodLabel={streamTab?.summary?.period_label || (period === "month" ? "This Month" : period)}
          onPeriodClick={() => setPeriodMenu((v) => !v)}
          summary={streamTab?.summary}
          loading={streamLoading}
          cash={mainTab === "self_service" ? ssCash : doCash}
          card={mainTab === "self_service" ? ssCard : doCard}
          onCashChange={mainTab === "self_service" ? setSsCashField : setDoCashField}
          onCardChange={mainTab === "self_service" ? setSsCardField : setDoCardField}
          volume={wfVolume}
          onVolumeChange={(v) => {
            setWfVolume(v);
            setSaveState("dirty");
            if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
            autosaveTimerRef.current = setTimeout(() => {
              saveManagementRevenueWf({
                date_et: dateEt,
                volume_lbs: v === "" || v == null ? null : Number(v),
              }).then(() => setSaveState("saved")).catch(() => setSaveState("error"));
            }, 600);
          }}
          revenueLabel={fmtMoney(streamTab?.rinse?.wf?.revenue ?? data?.rinse?.wf?.revenue)}
          dateEt={dateEt}
          onDateChange={(v) => { if (v) setDateEt(v); }}
          saveState={saveState}
          completeBusy={Boolean(dispBusy)}
          onComplete={async () => {
            if (mainTab === "rinse_wf") {
              await saveManagementRevenueWf({
                date_et: dateEt,
                volume_lbs: wfVolume === "" || wfVolume == null ? null : Number(wfVolume),
                finalize: true,
              });
              await createManagementRevenueDisposition({
                source_key: "rinse_wf",
                processing_date_et: dateEt,
                disposition: "completed",
              });
              await loadStreamTab(mainTab);
              return;
            }
            await flushNonRinse();
            await createManagementRevenueDisposition({
              source_key: mainTab,
              processing_date_et: dateEt,
              disposition: "completed",
            });
            await loadStreamTab(mainTab);
          }}
          onNoActivity={async () => {
            await createManagementRevenueDisposition({
              source_key: mainTab === "rinse_wf" ? "rinse_wf" : mainTab,
              processing_date_et: dateEt,
              disposition: "no_activity",
            });
            await loadStreamTab(mainTab);
          }}
          recent={streamTab?.recent || []}
          onOpenRecent={(d) => {
            setDateEt(d);
          }}
        />
      ) : null}

      {mainTab === "dhs" && screen === "home" ? (
        dhsLoading ? (
          <Box sx={{ py: 4, display: "grid", placeItems: "center" }}><CircularProgress size={28} /></Box>
        ) : (
          <DhsScheduleBoard
            board={dhsBoard}
            dateEt={dateEt}
            busy={Boolean(dispBusy)}
            onOpenOccurrence={(row) => openDhsAccount(null, { obligation: row, fromScreen: "dhs" })}
            onSkipOccurrence={async (row, reason) => {
              setDispBusy(row.occurrence_id || String(row.account_id));
              setError("");
              try {
                await createManagementRevenueDisposition({
                  source_key: row.source_key || `dhs:${row.account_id}`,
                  disposition: "skipped",
                  scheduled_pickup_date: row.scheduled_pickup_date,
                  reason: reason || null,
                });
                await loadDhsTab();
              } catch (e) {
                setError(e?.response?.data?.error || e.message || "Skip failed");
              } finally {
                setDispBusy("");
              }
            }}
            onAddManualPickup={async (payload) => {
              setDispBusy("manual");
              setError("");
              try {
                await postManagementRevenueDhsManualPickup(payload);
                await loadDhsTab();
              } catch (e) {
                setError(e?.response?.data?.error || e.message || "Add pickup failed");
              } finally {
                setDispBusy("");
              }
            }}
          />
        )
      ) : null}

      {mainTab === "cash" && screen === "home" ? (
        <CashLedgerPanel
          period={period === "previous_month" ? "month" : period}
          onPeriodChange={(p) => setPeriod(p)}
          summary={cashTab?.summary || cashTab?.today}
          payouts={cashTab?.payouts || []}
          loading={cashLoading}
          busy={Boolean(dispBusy)}
          onCreate={async (payload) => {
            await createManagementCashPayout(payload);
            await loadCashTab();
          }}
          onUpdate={async (id, payload) => {
            await updateManagementCashPayout(id, payload);
            await loadCashTab();
          }}
          onDelete={async (row) => {
            await deleteManagementCashPayout(row.id);
            await loadCashTab();
          }}
        />
      ) : null}

      {screen === "dhs_account" && dhsAccount ? (
        <DhsAccountSheet
          account={dhsAccount}
          entryDate={dateEt}
          occurrence={dhsOccurrence}
          draft={dhsDraft}
          onChange={setDhsDraft}
          onAutosave={scheduleDhsAutosave}
          onComplete={completeDhsAccount}
          saving={saveState === "saving"}
          completeBusy={Boolean(dispBusy)}
          saveState={saveState}
          saveLabels={saveLabels}
          labels={{
            pickupDate: t("mobileOps.revenue.pickupDate"),
            processingDate: t("mobileOps.revenue.processingDate"),
            deliveryDate: t("mobileOps.revenue.deliveryDate"),
            volumeLb: t("mobileOps.revenue.volumeLb"),
            revenue: t("mobileOps.revenue.revenue"),
            revenueOverride: t("mobileOps.revenue.revenueOverride"),
            useOverride: t("mobileOps.revenue.useOverride"),
            calculated: t("mobileOps.revenue.calculatedRevenue"),
            complete: t("mobileOps.revenue.complete"),
          }}
        />
      ) : null}

      {screen === "hang_dry" ? (
        <HdMobileAwaitingEntryPanel
          dateEt={dateEt}
          orders={hdList?.orders || []}
          loading={hdLoading}
          error={hdListError}
          onOrdersChanged={async (opts) => {
            await loadHangDry(opts);
            if (!opts?.quiet) await loadRevenue();
          }}
          onError={(msg) => {
            setHdListError(msg || "");
            if (msg) setError(msg);
          }}
          t={t}
          completeSectionBusy={dispBusy === `rinse_hd:${dateEt}`}
          onCompleteSection={() => completeDailySection("rinse_hd")}
          onNoActivity={() =>
            postDisposition(
              {
                source_key: "rinse_hd",
                processing_date_et: dateEt,
                disposition: "no_activity",
                reason: "No activity",
              },
              `rinse_hd:${dateEt}`,
            )
          }
        />
      ) : null}
    </OpsMobileShell>
  );
}
