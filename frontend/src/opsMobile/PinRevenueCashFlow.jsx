import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import {
  createManagementCashPayout,
  deleteManagementCashPayout,
  getManagementRevenue,
  getManagementRinseHd,
  getManagementRinseHdDetail,
  markManagementRinseHdComplete,
  saveManagementRevenueDhs,
  saveManagementRevenueNonRinse,
  saveManagementRinseHdProduction,
} from "../api";
import CashPayoutForm, { CashPayoutList } from "../components/revenueShared/CashPayoutForm";
import DhsAccountRow from "../components/revenueShared/DhsAccountRow";
import DhsAccountSheet from "../components/revenueShared/DhsAccountSheet";
import MoneyAmountField from "../components/revenueShared/MoneyAmountField";
import NonRinseEntryPanel from "../components/revenueShared/NonRinseEntryPanel";
import SectionStatusCard from "../components/revenueShared/SectionStatusCard";
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
};

/**
 * Employee PIN Revenue / Cash — shared Management APIs + shared entry components.
 * Hang Dry writes only hd_day_bag_production via Management HD APIs.
 */
export default function PinRevenueCashFlow({ onBack, onLock }) {
  const { t } = useI18n();
  const dateEt = todayEtIso();
  const [screen, setScreen] = useState("home");
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

  const nonRinseRef = useRef({ ssCash: null, ssCard: null, doCash: null, doCard: null });
  const autosaveTimerRef = useRef(null);
  const saveGenRef = useRef(0);
  nonRinseRef.current = { ssCash, ssCard, doCash, doCard };

  const applyDayPayload = useCallback((payload) => {
    setData(payload);
    const nr = payload?.non_rinse || payload?.non_rinse_revenue || {};
    setSsCash(moneyToInput(nr.self_service?.cash) === "" ? null : nr.self_service?.cash);
    setSsCard(moneyToInput(nr.self_service?.card) === "" ? null : nr.self_service?.card);
    setDoCash(moneyToInput(nr.drop_off?.cash) === "" ? null : nr.drop_off?.cash);
    setDoCard(moneyToInput(nr.drop_off?.card) === "" ? null : nr.drop_off?.card);
  }, []);

  const loadRevenue = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRevenue(dateEt);
      applyDayPayload(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [applyDayPayload, dateEt, t]);

  useEffect(() => {
    loadRevenue();
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [loadRevenue]);

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
    }, 450);
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

  const openDhsAccount = (row) => {
    setDhsAccount(row);
    setDhsDraft({
      volume: moneyToInput(row.volume) === "" ? null : row.volume,
      revenue: moneyToInput(row.revenue) === "" ? null : row.revenue,
      pickup_date: row.pickup_date || "",
      // Visible prefill with entry date when processing enabled and no saved value
      processing_date: row.processing_date || (row.use_processing_date !== false ? dateEt : ""),
      delivery_date: row.delivery_date || "",
      use_revenue_override: Boolean(row.use_revenue_override),
    });
    setScreen("dhs_account");
    setSaveState("");
  };

  const saveDhsAccount = async (body) => {
    setSaveState("saving");
    setError("");
    try {
      const res = await saveManagementRevenueDhs({
        date_et: dateEt,
        accounts: [body],
      });
      applyDayPayload(res.data || null);
      setSaveState("saved");
      const updated = (res.data?.dhs?.accounts || []).find((a) => a.account_id === body.account_id);
      if (updated) setDhsAccount(updated);
    } catch (e) {
      setSaveState("error");
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    }
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
      setScreen("dhs");
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
  const section = data?.section_status || {};
  const totalRev = data?.total_revenue;
  const cashOut = data?.cash_activity?.cash_paid_out;

  const title = t(SCREEN_TITLE_KEYS[screen] || "mobileOps.revenue.title");
  const backLabel = screen === "home" ? t("mobileOps.backPin") : t("mobileOps.back");

  const homeCards = [
    {
      id: "self_service",
      title: t("mobileOps.revenue.selfService"),
      primary: nr.self_service?.total,
      secondary:
        nr.self_service?.total == null
          ? null
          : `${t("mobileOps.revenue.cash")} ${fmtMoney(nr.self_service?.cash)} · ${t("mobileOps.revenue.card")} ${fmtMoney(nr.self_service?.card)}`,
      statusLabel:
        nr.self_service?.total == null ? t("mobileOps.revenue.needsEntry") : t("mobileOps.revenue.savedCheck"),
      statusTone: nr.self_service?.total == null ? "warn" : "ok",
      onClick: () => {
        setSaveState("");
        setScreen("self_service");
      },
    },
    {
      id: "drop_off",
      title: t("mobileOps.revenue.dropOff"),
      primary: nr.drop_off?.total,
      secondary:
        nr.drop_off?.total == null
          ? null
          : `${t("mobileOps.revenue.cash")} ${fmtMoney(nr.drop_off?.cash)} · ${t("mobileOps.revenue.card")} ${fmtMoney(nr.drop_off?.card)}`,
      statusLabel:
        nr.drop_off?.total == null ? t("mobileOps.revenue.needsEntry") : t("mobileOps.revenue.savedCheck"),
      statusTone: nr.drop_off?.total == null ? "warn" : "ok",
      onClick: () => {
        setSaveState("");
        setScreen("drop_off");
      },
    },
    {
      id: "dhs",
      title: t("mobileOps.revenue.dhs"),
      primary: dhs.total,
      secondary: dhs.accounts?.length
        ? [
            dhs.volume_lbs != null ? `${fmtInt(dhs.volume_lbs)} lb` : null,
            `${dhs.entered_count || 0}/${dhs.active_count || 0} ${t("mobileOps.revenue.accountsEntered")}`,
          ]
            .filter(Boolean)
            .join(" · ")
        : t("mobileOps.revenue.noDhsAccounts"),
      statusLabel:
        !dhs.accounts?.length
          ? "—"
          : dhs.entered_count === dhs.active_count
            ? t("mobileOps.revenue.complete")
            : t("mobileOps.revenue.needsEntry"),
      statusTone: dhs.entered_count === dhs.active_count && dhs.active_count ? "ok" : "warn",
      onClick: () => {
        setSaveState("");
        setScreen("dhs");
      },
    },
    {
      id: "cash",
      title: t("mobileOps.revenue.cashPaidOut"),
      primary: payouts.length ? cashOut : null,
      secondary: payouts.length
        ? t("mobileOps.revenue.payoutEntries", { count: payouts.length })
        : null,
      statusLabel: payouts.length ? t("mobileOps.revenue.savedCheck") : t("mobileOps.revenue.needsEntry"),
      statusTone: payouts.length ? "ok" : "neutral",
      onClick: () => {
        setSaveState("");
        setAddingPayout(false);
        setScreen("cash");
      },
    },
    {
      id: "hang_dry",
      title: t("mobileOps.revenue.hangDry"),
      primary: hd.revenue,
      secondary:
        hd.orders != null
          ? t("mobileOps.revenue.hdCompletedCount", { count: hd.orders })
          : null,
      statusLabel: hd.revenue != null || hd.orders ? t("mobileOps.revenue.complete") : t("mobileOps.revenue.needsEntry"),
      statusTone: hd.revenue != null || hd.orders ? "ok" : "warn",
      onClick: openHangDry,
    },
  ];

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

      {screen === "home" ? (
        <Typography sx={{ fontSize: 13, fontWeight: 700, color: OPS_MOBILE.muted, mb: 1 }}>
          {t("mobileOps.revenue.todayLabel")} · {formatHomeDate(dateEt)}
        </Typography>
      ) : null}

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading && screen === "home" ? (
        <Box sx={{ py: 6, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {screen === "home" && !loading ? (
        <Stack spacing={1.25} sx={{ pb: 2 }}>
          <Box
            sx={{
              p: 1.5,
              borderRadius: 2,
              bgcolor: "#fff",
              border: "1px solid rgba(0,151,178,0.28)",
            }}
          >
            <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
              {t("mobileOps.revenue.todaysEntry")}
            </Typography>
            <Typography sx={{ mt: 0.35, fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
              {t("mobileOps.revenue.summaryLine", {
                revenue: fmtMoney(totalRev),
                cashOut: fmtMoney(cashOut ?? 0),
                complete: section.label || "—",
              })}
            </Typography>
          </Box>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr" },
              gap: 1.25,
            }}
          >
            {homeCards.map((c) => (
              <SectionStatusCard
                key={c.id}
                title={c.title}
                primary={c.primary}
                secondary={c.secondary}
                statusLabel={c.statusLabel}
                statusTone={c.statusTone}
                onClick={c.onClick}
              />
            ))}
          </Box>
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </Stack>
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
        />
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
          onSave={saveDhsAccount}
          saving={saveState === "saving"}
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
            save: t("mobileOps.revenue.save"),
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
