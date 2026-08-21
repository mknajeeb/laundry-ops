import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import {
  createManagementCashPayout,
  createManagementRevenueDisposition,
  deleteManagementCashPayout,
  getManagementRevenueBootstrap,
  getManagementRevenueCashTab,
  getManagementRevenueDaily,
  getManagementRevenueDashboard,
  getManagementRevenueDhsBoard,
  getManagementRevenueMissingWork,
  getManagementRevenueSchedulePreview,
  getManagementRinseHd,
  getManagementRinseHdDetail,
  markManagementRinseHdComplete,
  postManagementRevenueDhsManualPickup,
  saveManagementRevenueDhs,
  saveManagementRevenueNonRinse,
  saveManagementRevenueWf,
  saveManagementRinseHdProduction,
} from "../api";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import RevenueDashboardPanel from "../components/management/revenue/RevenueDashboardPanel";
import CashPayoutForm, { CashPayoutList } from "../components/revenueShared/CashPayoutForm";
import DailyCompletenessStrip from "../components/revenueShared/DailyCompletenessStrip";
import DailyEntryCards from "../components/revenueShared/DailyEntryCards";
import DhsAccountRow from "../components/revenueShared/DhsAccountRow";
import DhsAccountSheet from "../components/revenueShared/DhsAccountSheet";
import DhsScheduleBoard from "../components/revenueShared/DhsScheduleBoard";
import MissingWorkPanel from "../components/revenueShared/MissingWorkPanel";
import MoneyAmountField from "../components/revenueShared/MoneyAmountField";
import NonRinseEntryPanel from "../components/revenueShared/NonRinseEntryPanel";
import SaveStatusChip from "../components/revenueShared/SaveStatusChip";
import {
  fmtMoney,
  moneyToInput,
  parseMoneyInput,
  todayEtIso,
} from "../components/revenueShared/revenueFormat";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
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

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

const SCREEN_TITLE_KEYS = {
  home: "mobileOps.revenue.title",
  self_service: "mobileOps.revenue.selfService",
  drop_off: "mobileOps.revenue.dropOff",
  dhs: "mobileOps.revenue.dhs",
  dhs_account: "mobileOps.revenue.dhs",
  cash: "mobileOps.revenue.cashPaidOut",
  hang_dry: "mobileOps.revenue.hangDry",
  hang_dry_detail: "mobileOps.revenue.hangDry",
  rinse_wf: "mobileOps.revenue.rinseWf",
  missing: "mobileOps.revenue.missingWork",
};

/**
 * Employee PIN Revenue / Cash — shared Management APIs + shared entry components.
 * Hang Dry writes only hd_day_bag_production via Management HD APIs.
 */
export default function PinRevenueCashFlow({ onBack, onLock }) {
  const { t } = useI18n();
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [mainTab, setMainTab] = useState("daily"); // daily | dhs | missing | cash | stats
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
  const [dhsDraft, setDhsDraft] = useState({});

  const [addingPayout, setAddingPayout] = useState(false);
  const [payoutDate, setPayoutDate] = useState(dateEt);
  const [payoutPurpose, setPayoutPurpose] = useState("");
  const [payoutAmount, setPayoutAmount] = useState(null);
  const [payoutNote, setPayoutNote] = useState("");
  const [payoutBusy, setPayoutBusy] = useState(false);

  const [hdList, setHdList] = useState(null);
  const [hdLoading, setHdLoading] = useState(false);
  const [hdDetail, setHdDetail] = useState(null);
  const [hdItems, setHdItems] = useState(null);
  const [hdRevenue, setHdRevenue] = useState(null);
  const [hdSaving, setHdSaving] = useState(false);

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

  const loadMissingTab = useCallback(async (filter = "all") => {
    setMissingLoading(true);
    try {
      const res = await getManagementRevenueMissingWork({ date_et: dateEt, filter });
      setMissing(res.data || null);
      loadedTabsRef.current.missing = true;
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setMissingLoading(false);
    }
  }, [dateEt, t]);

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
      const res = await getManagementRevenueCashTab(dateEt);
      setCashTab(res.data || null);
      loadedTabsRef.current.cash = true;
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setCashLoading(false);
    }
  }, [dateEt, t]);

  useEffect(() => {
    loadRevenue();
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [loadRevenue]);

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
    if (mainTab === "stats") loadDashboard();
  }, [mainTab, loadDashboard]);

  useEffect(() => {
    if (mainTab === "missing") loadMissingTab(missingFilter);
  }, [mainTab, missingFilter, loadMissingTab]);

  useEffect(() => {
    if (mainTab === "dhs") loadDhsTab();
  }, [mainTab, loadDhsTab]);

  useEffect(() => {
    if (mainTab === "cash") loadCashTab();
  }, [mainTab, loadCashTab]);

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
        setMainTab("daily");
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
        use_pickup_date: true,
        use_processing_date: true,
        use_delivery_date: true,
      };
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
        setMainTab("daily");
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

  const submitPayout = async () => {
    if (!payoutPurpose.trim() || !payoutDate) return;
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
      setAddingPayout(false);
      setPayoutPurpose("");
      setPayoutAmount(null);
      setPayoutNote("");
      setPayoutDate(dateEt);
      await loadRevenue();
      setSaveState("saved");
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.payoutFailed"));
    } finally {
      setPayoutBusy(false);
    }
  };

  const removePayout = async (id) => {
    setError("");
    try {
      await deleteManagementCashPayout(id);
      await loadRevenue();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.deletePayoutFailed"));
    }
  };

  const loadHangDry = async () => {
    setHdLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHd({ date_et: dateEt, status: "all" });
      setHdList(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadHdFailed"));
      setHdList(null);
    } finally {
      setHdLoading(false);
    }
  };

  const openHangDry = async () => {
    setScreen("hang_dry");
    await loadHangDry();
  };

  const openHangDryDetail = async (order) => {
    setError("");
    setScreen("hang_dry_detail");
    setHdDetail({ loading: true, order });
    setHdItems(order.items != null ? order.items : null);
    setHdRevenue(order.revenue != null ? order.revenue : null);
    try {
      const res = await getManagementRinseHdDetail(order.bag_id, { date_et: dateEt });
      setHdDetail(res.data || { order });
      const prod = res.data?.production || res.data?.order || {};
      setHdItems(prod.items != null ? prod.items : order.items != null ? order.items : null);
      setHdRevenue(
        prod.revenue != null ? prod.revenue : order.revenue != null ? order.revenue : null,
      );
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadOrderFailed"));
      setHdDetail({ order });
    }
  };

  const saveHdProduction = async ({ markComplete = false } = {}) => {
    const bagId = hdDetail?.order?.bag_id || hdDetail?.bag_id;
    if (!bagId) return;
    setHdSaving(true);
    setError("");
    try {
      await saveManagementRinseHdProduction(bagId, {
        date_et: dateEt,
        total_items: hdItems === null || hdItems === "" ? null : Number(hdItems),
        revenue: parseMoneyInput(hdRevenue),
        version: hdDetail?.production?.version ?? hdDetail?.order?.production_version ?? 0,
      });
      if (markComplete) {
        await markManagementRinseHdComplete(bagId, {
          date_et: dateEt,
          version: hdDetail?.production?.version ?? hdDetail?.order?.production_version ?? 0,
        });
        await loadHangDry();
        setScreen("hang_dry");
        setHdDetail(null);
      } else {
        const res = await getManagementRinseHdDetail(bagId, { date_et: dateEt });
        setHdDetail(res.data || { order: { bag_id: bagId } });
        await loadHangDry();
      }
      setSaveState("saved");
      await loadRevenue();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    } finally {
      setHdSaving(false);
    }
  };

  const handleTopBack = () => {
    if (screen === "home") {
      onBack?.();
      return;
    }
    if (screen === "hang_dry_detail") {
      setScreen("hang_dry");
      setHdDetail(null);
      return;
    }
    if (screen === "dhs_account") {
      if (returnScreen === "missing") {
        setMainTab("missing");
        setScreen("home");
      } else {
        setScreen("dhs");
      }
      setDhsAccount(null);
      return;
    }
    if (screen === "self_service" || screen === "drop_off") {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
        flushNonRinse();
      }
    }
    setMainTab("daily");
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
  const dhs = data?.dhs || {};
  const dhsAccounts = dhs.accounts || [];
  const payouts = data?.cash_payouts || [];
  const hd = data?.rinse?.hd || {};
  const cashOut = data?.cash_activity?.cash_paid_out;

  const title = t(SCREEN_TITLE_KEYS[screen] || "mobileOps.revenue.title");
  const backLabel = screen === "home" ? t("mobileOps.backPin") : t("mobileOps.back");

  const entryAmounts = {
    self_service: nr.self_service?.total,
    drop_off: nr.drop_off?.total,
    rinse_wf: data?.rinse?.wf?.revenue,
    rinse_hd: hd?.revenue,
  };

  const missingBadge =
    missing?.summary?.missing_total != null && Number(missing.summary.missing_total) > 0
      ? ` ${missing.summary.missing_total}`
      : "";

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

      {(screen === "home") &&
      screen !== "self_service" &&
      screen !== "drop_off" &&
      screen !== "rinse_wf" &&
      screen !== "dhs" &&
      screen !== "dhs_account" &&
      screen !== "cash" &&
      screen !== "hang_dry" &&
      screen !== "hang_dry_detail" ? (
        <Box
          sx={{
            position: "sticky",
            top: 0,
            zIndex: 3,
            bgcolor: "#F3F7F8",
            pt: 0.5,
            pb: 0.5,
            mb: 1,
            borderBottom: "1px solid rgba(0,122,145,0.14)",
          }}
        >
          <Tabs
            value={mainTab}
            onChange={(_, v) => {
              setMainTab(v);
              setScreen("home");
              setSaveState("");
            }}
            variant="scrollable"
            scrollButtons="auto"
            allowScrollButtonsMobile
            sx={{
              minHeight: 44,
              "& .MuiTabs-indicator": { height: 3, bgcolor: "#007a91" },
              "& .MuiTab-root": {
                minHeight: 44,
                fontWeight: 800,
                textTransform: "none",
                fontSize: 13,
                px: 1.25,
                color: "#64748b",
              },
              "& .Mui-selected": { color: "#007a91 !important" },
            }}
          >
            <Tab value="daily" label="Daily" />
            <Tab value="dhs" label="DHS" />
            <Tab
              value="missing"
              label={`Missing${missingBadge ? ` ${String(missingBadge).trim()}` : ""}`}
            />
            <Tab value="cash" label="Cash" />
            <Tab value="stats" label="Stats" />
          </Tabs>
        </Box>
      ) : null}

      {mainTab === "daily" && screen === "home" ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          <Box sx={{ flex: 1 }}>
            <PlanningDatePicker
              label={t("mobileOps.revenue.processingDate") !== "mobileOps.revenue.processingDate" ? t("mobileOps.revenue.processingDate") : "Processing Date"}
              value={dateEt}
              onChange={(v) => {
                if (v) setDateEt(v);
              }}
            />
          </Box>
        </Stack>
      ) : null}

      {loading && mainTab === "daily" && screen === "home" ? (
        <Box sx={{ py: 6, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {mainTab === "daily" && screen === "home" && !loading ? (
        <Stack spacing={1.25} sx={{ pb: 2 }}>
          <DailyEntryCards
            dateLabel={formatHomeDate(dateEt)}
            completeness={data?.daily_completeness}
            nonRinse={data?.non_rinse}
            rinse={data?.rinse}
            t={t}
            onOpenSection={(key) => {
              setSaveState("");
              if (key === "self_service") setScreen("self_service");
              else if (key === "drop_off") setScreen("drop_off");
              else if (key === "rinse_hd") openHangDry();
              else if (key === "rinse_wf") {
                setWfVolume(moneyToInput(data?.rinse?.wf?.volume_lbs));
                setScreen("rinse_wf");
              }
            }}
          />
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </Stack>
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
        <Stack spacing={1.25} sx={{ pb: 2 }}>
          <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
            Cash
          </Typography>
          {cashLoading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}><CircularProgress size={28} /></Box>
          ) : (
            <>
              <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: "#fff", border: "1px solid rgba(0,122,145,0.22)" }}>
                <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Cash received · {fmtMoney(cashTab?.today?.cash_received)}</Typography>
                <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Cash paid out · {fmtMoney(cashTab?.today?.cash_paid_out)}</Typography>
                <Typography sx={{ fontSize: 15, fontWeight: 900, color: "#007a91" }}>
                  Net · {fmtMoney(cashTab?.today?.net_cash)}
                </Typography>
              </Box>
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={() => {
                  setPayoutDate(dateEt);
                  setAddingPayout(true);
                  setScreen("cash");
                }}
                sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
              >
                Add Cash Paid Out
              </Button>
              <Stack spacing={0.75}>
                {(cashTab?.payouts || []).map((p) => (
                  <Box key={p.id} sx={{ p: 1.25, borderRadius: 2, bgcolor: "#fff", border: "1px solid #e5e7eb" }}>
                    <Typography sx={{ fontWeight: 800 }}>{p.payout_date_et}</Typography>
                    <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#007a91" }}>
                      {fmtMoney(p.amount)} · {p.purpose}
                    </Typography>
                    {p.note ? <Typography sx={{ fontSize: 12, color: "#64748b" }}>{p.note}</Typography> : null}
                  </Box>
                ))}
              </Stack>
            </>
          )}
        </Stack>
      ) : null}

      {mainTab === "missing" && screen === "home" ? (
        <MissingWorkPanel
          loading={missingLoading}
          data={missing}
          filter={missingFilter}
          onFilterChange={async (f) => {
            setMissingFilter(f);
            setMissingLoading(true);
            try {
              const res = await getManagementRevenueMissingWork({ date_et: dateEt, filter: f });
              setMissing(res.data || null);
            } finally {
              setMissingLoading(false);
            }
          }}
          busyId={dispBusy}
          onOpenItem={(item) => {
            setMainTab("daily");
            if (item.kind === "dhs") {
              const row = (data?.dhs?.accounts || []).find((a) => a.account_id === item.account_id);
              openDhsAccount(row, { fromScreen: "missing", obligation: item });
              return;
            }
            if (item.source_key === "self_service") setScreen("self_service");
            else if (item.source_key === "drop_off") setScreen("drop_off");
            else if (item.source_key === "rinse_hd") openHangDry();
            else if (item.source_key === "rinse_wf") {
              setWfVolume(moneyToInput(data?.rinse?.wf?.volume_lbs));
              setScreen("rinse_wf");
            }
          }}
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
                disposition: "no_pickup",
                reason,
              },
              `${item.source_key}:${item.scheduled_pickup_date}`,
            )
          }
          onReschedule={(item, reason) => {
            const next = window.prompt(t("mobileOps.revenue.newPickupDate"), item.scheduled_pickup_date);
            if (!next) return;
            postDisposition(
              {
                source_key: item.source_key,
                account_id: item.account_id,
                scheduled_pickup_date: item.scheduled_pickup_date,
                disposition: "rescheduled",
                new_pickup_date: next,
                reason,
              },
              `${item.source_key}:${item.scheduled_pickup_date}`,
            );
          }}
        />
      ) : null}

      {mainTab === "stats" && screen === "home" ? (
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

      {screen === "self_service" ? (
        <NonRinseEntryPanel
          title={t("mobileOps.revenue.selfService")}
          cash={ssCash}
          card={ssCard}
          onCashChange={setSsCashField}
          onCardChange={setSsCardField}
          saveState={saveState}
          saveLabels={saveLabels}
          cashLabel={t("mobileOps.revenue.cash")}
          cardLabel={t("mobileOps.revenue.card")}
          totalLabel={t("mobileOps.revenue.total")}
          processingDate={dateEt}
          onProcessingDateChange={(v) => {
            if (v) setDateEt(v);
          }}
          processingDateLabel={
            t("mobileOps.revenue.processingDate") !== "mobileOps.revenue.processingDate"
              ? t("mobileOps.revenue.processingDate")
              : "Processing Date"
          }
          completeLabel={t("mobileOps.revenue.complete")}
          completeBusy={dispBusy === `self_service:${dateEt}`}
          onComplete={() => completeDailySection("self_service")}
          noActivityLabel={t("mobileOps.revenue.noActivity")}
          onNoActivity={() =>
            postDisposition(
              {
                source_key: "self_service",
                processing_date_et: dateEt,
                disposition: "no_activity",
                reason: "No activity",
              },
              `self_service:${dateEt}`,
            )
          }
        />
      ) : null}

      {screen === "drop_off" ? (
        <NonRinseEntryPanel
          title={t("mobileOps.revenue.dropOff")}
          cash={doCash}
          card={doCard}
          onCashChange={setDoCashField}
          onCardChange={setDoCardField}
          saveState={saveState}
          saveLabels={saveLabels}
          cashLabel={t("mobileOps.revenue.cash")}
          cardLabel={t("mobileOps.revenue.card")}
          totalLabel={t("mobileOps.revenue.total")}
          processingDate={dateEt}
          onProcessingDateChange={(v) => {
            if (v) setDateEt(v);
          }}
          processingDateLabel={
            t("mobileOps.revenue.processingDate") !== "mobileOps.revenue.processingDate"
              ? t("mobileOps.revenue.processingDate")
              : "Processing Date"
          }
          completeLabel={t("mobileOps.revenue.complete")}
          completeBusy={dispBusy === `drop_off:${dateEt}`}
          onComplete={() => completeDailySection("drop_off")}
          noActivityLabel={t("mobileOps.revenue.noActivity")}
          onNoActivity={() =>
            postDisposition(
              {
                source_key: "drop_off",
                processing_date_et: dateEt,
                disposition: "no_activity",
                reason: "No activity",
              },
              `drop_off:${dateEt}`,
            )
          }
        />
      ) : null}

      {screen === "rinse_wf" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 900 }}>
            {t("mobileOps.revenue.rinseWf") !== "mobileOps.revenue.rinseWf" ? t("mobileOps.revenue.rinseWf") : "Rinse WF"}
          </Typography>
          <PlanningDatePicker
            label={
              t("mobileOps.revenue.processingDate") !== "mobileOps.revenue.processingDate"
                ? t("mobileOps.revenue.processingDate")
                : "Processing Date"
            }
            value={dateEt}
            onChange={(v) => {
              if (v) setDateEt(v);
            }}
          />
          <MoneyAmountField
            label="Volume (lb)"
            value={wfVolume}
            onChange={(v) => {
              setWfVolume(v);
              setSaveState("");
            }}
            prefix=""
          />
          <SaveStatusChip state={saveState} labels={saveLabels} />
          <Button
            variant="contained"
            disabled={dispBusy === `rinse_wf:${dateEt}` || saveState === "saving"}
            onClick={() => completeDailySection("rinse_wf")}
            sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
          >
            {t("mobileOps.revenue.complete")}
          </Button>
          <Button
            variant="outlined"
            disabled={dispBusy === `rinse_wf:${dateEt}`}
            onClick={() =>
              postDisposition(
                {
                  source_key: "rinse_wf",
                  processing_date_et: dateEt,
                  disposition: "no_activity",
                  reason: "No activity",
                },
                `rinse_wf:${dateEt}`,
              )
            }
            sx={{ textTransform: "none", fontWeight: 700, minHeight: 44 }}
          >
            {t("mobileOps.revenue.noActivity")}
          </Button>
        </Stack>
      ) : null}

      {screen === "dhs" ? (
        <Stack spacing={1.25} sx={{ pb: 2 }}>
          {!dhsAccounts.length ? (
            <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
              {t("mobileOps.revenue.noDhsAccounts")}
            </Typography>
          ) : (
            dhsAccounts.map((row) => (
              <DhsAccountRow
                key={row.account_id}
                account={row}
                onClick={() => openDhsAccount(row)}
                needsEntryLabel={t("mobileOps.revenue.needsEntry")}
              />
            ))
          )}
        </Stack>
      ) : null}

      {screen === "dhs_account" && dhsAccount ? (
        <DhsAccountSheet
          account={dhsAccount}
          entryDate={dateEt}
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

      {screen === "cash" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          {!addingPayout ? (
            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={() => {
                setPayoutDate(dateEt);
                setAddingPayout(true);
              }}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
            >
              {t("mobileOps.revenue.addPayout")}
            </Button>
          ) : (
            <CashPayoutForm
              payoutDate={payoutDate}
              purpose={payoutPurpose}
              amount={payoutAmount}
              note={payoutNote}
              busy={payoutBusy}
              onChange={(patch) => {
                if ("payoutDate" in patch) setPayoutDate(patch.payoutDate);
                if ("purpose" in patch) setPayoutPurpose(patch.purpose);
                if ("amount" in patch) setPayoutAmount(patch.amount);
                if ("note" in patch) setPayoutNote(patch.note);
              }}
              onCancel={() => setAddingPayout(false)}
              onSubmit={submitPayout}
              labels={{
                payoutDate: t("mobileOps.revenue.payoutDate"),
                payoutDateHelp: t("mobileOps.revenue.payoutDateHelp"),
                purpose: t("mobileOps.revenue.purpose"),
                amount: t("mobileOps.revenue.amount"),
                noteOptional: t("mobileOps.revenue.noteOptional"),
                cancel: t("mobileOps.revenue.cancel"),
                save: t("mobileOps.revenue.save"),
                saving: t("mobileOps.revenue.saving"),
              }}
            />
          )}
          <CashPayoutList
            payouts={payouts}
            onDelete={removePayout}
            labels={{
              noPayouts: t("mobileOps.revenue.noPayouts"),
              delete: t("mobileOps.revenue.deletePayout"),
            }}
          />
        </Stack>
      ) : null}

      {screen === "hang_dry" ? (
        <Stack spacing={1.25} sx={{ pb: 2 }}>
          {hdLoading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
              <CircularProgress size={28} />
            </Box>
          ) : null}
          {!hdLoading && !(hdList?.orders || []).length ? (
            <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
              {t("mobileOps.revenue.noHdOrders")}
            </Typography>
          ) : null}
          {(hdList?.orders || []).map((order) => (
            <Box
              key={order.bag_id}
              component="button"
              type="button"
              onClick={() => openHangDryDetail(order)}
              sx={{
                display: "block",
                width: "100%",
                textAlign: "left",
                p: 1.5,
                borderRadius: 2,
                border: "1px solid #e5e7eb",
                bgcolor: "#fff",
                appearance: "none",
                fontFamily: "inherit",
                cursor: "pointer",
              }}
            >
              <Typography sx={{ fontWeight: 900 }}>
                {order.customer_name || t("mobileOps.revenue.hdOrder")}
              </Typography>
              <Typography sx={{ fontSize: 12, color: OPS_MOBILE.muted }}>{order.bag_id}</Typography>
              <Typography sx={{ mt: 0.5, fontSize: 13, fontWeight: 700, color: "#007a91" }}>
                {fmtMoney(order.revenue)}
                {order.items != null ? ` · ${t("mobileOps.revenue.itemsCount", { count: order.items })}` : ""}
              </Typography>
            </Box>
          ))}
          <Button
            variant="contained"
            disabled={dispBusy === `rinse_hd:${dateEt}`}
            onClick={() => completeDailySection("rinse_hd")}
            sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
          >
            {t("mobileOps.revenue.complete")}
          </Button>
          <Button
            variant="outlined"
            disabled={dispBusy === `rinse_hd:${dateEt}`}
            onClick={() =>
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
            sx={{ textTransform: "none", fontWeight: 700, minHeight: 44 }}
          >
            {t("mobileOps.revenue.noActivity")}
          </Button>
        </Stack>
      ) : null}

      {screen === "hang_dry_detail" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          <Typography sx={{ fontWeight: 900 }}>
            {hdDetail?.order?.customer_name || t("mobileOps.revenue.hdOrder")}
          </Typography>
          <Typography sx={{ fontSize: 12, color: OPS_MOBILE.muted }}>
            {hdDetail?.order?.bag_id}
            {hdDetail?.order?.started_at
              ? ` · ${t("mobileOps.revenue.started", {
                  time: fmtTime(hdDetail.order.started_at),
                  operator: hdDetail.order.operator_name || "—",
                })}`
              : ""}
          </Typography>
          <MoneyAmountField
            label={t("mobileOps.revenue.items")}
            value={hdItems}
            onChange={setHdItems}
            prefix=""
          />
          <MoneyAmountField
            label={t("mobileOps.revenue.revenue")}
            value={hdRevenue}
            onChange={setHdRevenue}
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <Button
              variant="outlined"
              disabled={hdSaving}
              onClick={() => saveHdProduction({ markComplete: false })}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
            >
              {t("mobileOps.revenue.save")}
            </Button>
            <Button
              variant="contained"
              disabled={hdSaving}
              onClick={() => saveHdProduction({ markComplete: true })}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
            >
              {t("mobileOps.revenue.saveComplete")}
            </Button>
          </Stack>
        </Stack>
      ) : null}
    </OpsMobileShell>
  );
}
