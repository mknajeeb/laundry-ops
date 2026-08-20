import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
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
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import OpsChoiceCard from "./OpsChoiceCard";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import { useI18n } from "../i18n/I18nContext";

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

function parseMoneyInput(v) {
  const n = Number(String(v ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

function MoneyField({ label, value, onChange, disabled }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      fullWidth
      inputMode="decimal"
      sx={{
        "& .MuiInputBase-root": {
          minHeight: 56,
          fontWeight: 700,
          fontSize: "1.15rem",
        },
      }}
    />
  );
}

const HOME_CARD_IDS = ["self_service", "drop_off", "dhs", "cash", "hang_dry"];

const SCREEN_TITLE_KEYS = {
  home: "mobileOps.revenue.title",
  self_service: "mobileOps.revenue.selfService",
  drop_off: "mobileOps.revenue.dropOff",
  dhs: "mobileOps.revenue.dhs",
  cash: "mobileOps.revenue.cashPaidOut",
  hang_dry: "mobileOps.revenue.hangDry",
  hang_dry_detail: "mobileOps.revenue.hangDry",
};

const HOME_TITLE_KEYS = {
  self_service: "mobileOps.revenue.selfService",
  drop_off: "mobileOps.revenue.dropOff",
  dhs: "mobileOps.revenue.dhs",
  cash: "mobileOps.revenue.cashPaidOut",
  hang_dry: "mobileOps.revenue.hangDry",
};

/**
 * Employee PIN Revenue / Cash entry — Management APIs only.
 * Hang Dry lives inside this flow (not a separate hub tile).
 */
export default function PinRevenueCashFlow({ onBack, onLock }) {
  const { t } = useI18n();
  const dateEt = todayEtIso();
  const [screen, setScreen] = useState("home");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState("");
  const [data, setData] = useState(null);

  const [ssCash, setSsCash] = useState("");
  const [ssCard, setSsCard] = useState("");
  const [doCash, setDoCash] = useState("");
  const [doCard, setDoCard] = useState("");
  const [dhsDraft, setDhsDraft] = useState({});

  const [payoutPurpose, setPayoutPurpose] = useState("");
  const [payoutAmount, setPayoutAmount] = useState("");
  const [payoutNote, setPayoutNote] = useState("");
  const [payoutBusy, setPayoutBusy] = useState(false);
  const [addingPayout, setAddingPayout] = useState(false);

  const [hdLoading, setHdLoading] = useState(false);
  const [hdOrders, setHdOrders] = useState([]);
  const [hdDetail, setHdDetail] = useState(null);
  const [hdItems, setHdItems] = useState("");
  const [hdRevenue, setHdRevenue] = useState("");
  const [hdSaving, setHdSaving] = useState(false);

  const nonRinseRef = useRef({ ssCash: "", ssCard: "", doCash: "", doCard: "" });
  const autosaveTimerRef = useRef(null);
  const saveGenRef = useRef(0);

  nonRinseRef.current = { ssCash, ssCard, doCash, doCard };

  const applyRevenuePayload = useCallback((payload) => {
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

  const loadRevenue = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRevenue(dateEt);
      applyRevenuePayload(res.data || {});
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [applyRevenuePayload, dateEt, t]);

  const loadHangDry = useCallback(async () => {
    setHdLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHd(dateEt, { status: "all" });
      setHdOrders(res.data?.orders || []);
    } catch (e) {
      setHdOrders([]);
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadHdFailed"));
    } finally {
      setHdLoading(false);
    }
  }, [dateEt, t]);

  useEffect(() => {
    loadRevenue();
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [loadRevenue]);

  const flushNonRinse = useCallback(async () => {
    const vals = nonRinseRef.current;
    const gen = ++saveGenRef.current;
    setSaveState("saving");
    setError("");
    try {
      const res = await saveManagementRevenueNonRinse({
        date_et: dateEt,
        self_service_cash: parseMoneyInput(vals.ssCash),
        self_service_card: parseMoneyInput(vals.ssCard),
        drop_off_cash: parseMoneyInput(vals.doCash),
        drop_off_card: parseMoneyInput(vals.doCard),
      });
      if (gen !== saveGenRef.current) return;
      applyRevenuePayload(res.data || {});
      setSaveState("saved");
    } catch (e) {
      if (gen !== saveGenRef.current) return;
      setSaveState("error");
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    }
  }, [applyRevenuePayload, dateEt]);

  const scheduleNonRinseAutosave = useCallback(() => {
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      autosaveTimerRef.current = null;
      flushNonRinse();
    }, 500);
  }, [flushNonRinse]);

  const setNonRinseField = (setter) => (raw) => {
    setter(raw);
    scheduleNonRinseAutosave();
  };

  const saveDhs = async () => {
    setSaveState("saving");
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
      applyRevenuePayload(res.data || {});
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      setError(e?.response?.data?.error || e?.message || t("mobileOps.revenue.saveFailed"));
    }
  };

  const submitPayout = async () => {
    if (!payoutPurpose.trim()) return;
    setPayoutBusy(true);
    setError("");
    try {
      await createManagementCashPayout({
        date_et: dateEt,
        purpose: payoutPurpose.trim(),
        amount: parseMoneyInput(payoutAmount),
        note: payoutNote.trim() || null,
      });
      setPayoutPurpose("");
      setPayoutAmount("");
      setPayoutNote("");
      setAddingPayout(false);
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

  const openHangDry = async () => {
    setScreen("hang_dry");
    await loadHangDry();
  };

  const openHangDryDetail = async (order) => {
    setError("");
    setScreen("hang_dry_detail");
    setHdDetail({ loading: true, order });
    setHdItems(order.items != null ? String(order.items) : "");
    setHdRevenue(order.revenue != null ? String(order.revenue) : "");
    try {
      const res = await getManagementRinseHdDetail(order.bag_id, { date_et: dateEt });
      setHdDetail(res.data || { order });
      const prod = res.data?.production || res.data?.order || {};
      setHdItems(
        prod.items != null
          ? String(prod.items)
          : order.items != null
            ? String(order.items)
            : "",
      );
      setHdRevenue(
        prod.revenue != null
          ? String(prod.revenue)
          : order.revenue != null
            ? String(order.revenue)
            : "",
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
        total_items: hdItems === "" ? null : Number(hdItems),
        revenue: hdRevenue === "" ? null : Number(hdRevenue),
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
        const prod = res.data?.production || res.data?.order || {};
        if (prod.items != null) setHdItems(String(prod.items));
        if (prod.revenue != null) setHdRevenue(String(prod.revenue));
        await loadHangDry();
      }
      setSaveState("saved");
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
    if (screen === "self_service" || screen === "drop_off") {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
        flushNonRinse();
      }
    }
    setScreen("home");
    setAddingPayout(false);
  };

  const saveLabel =
    saveState === "saving"
      ? t("mobileOps.revenue.saving")
      : saveState === "saved"
        ? t("mobileOps.revenue.saved")
        : saveState === "error"
          ? t("mobileOps.revenue.saveFailed")
          : "";

  const payouts = data?.cash_payouts || [];
  const dhsAccounts = data?.dhs?.accounts || [];
  const title = t(SCREEN_TITLE_KEYS[screen] || "mobileOps.revenue.title");
  const backLabel = screen === "home" ? t("mobileOps.backPin") : t("mobileOps.back");

  return (
    <OpsMobileShell
      maxWidth={720}
      sx={{
        px: { xs: 1.5, sm: 2, md: 3 },
        py: { xs: 1.5, sm: 2 },
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

      <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.85rem", mb: 1 }}>
        {[dateEt, saveLabel].filter(Boolean).join(" · ")}
      </Typography>

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
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                sm: "1fr 1fr",
                md: "1fr 1fr",
              },
              gap: 1.25,
            }}
          >
            {HOME_CARD_IDS.map((id) => (
              <OpsChoiceCard
                key={id}
                title={t(HOME_TITLE_KEYS[id])}
                onClick={() => {
                  if (id === "hang_dry") openHangDry();
                  else setScreen(id);
                }}
              />
            ))}
          </Box>
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </Stack>
      ) : null}

      {screen === "self_service" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          <MoneyField label={t("mobileOps.revenue.cash")} value={ssCash} onChange={setNonRinseField(setSsCash)} />
          <MoneyField label={t("mobileOps.revenue.card")} value={ssCard} onChange={setNonRinseField(setSsCard)} />
          <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            Total: {fmtMoney(parseMoneyInput(ssCash) + parseMoneyInput(ssCard))}
          </Typography>
        </Stack>
      ) : null}

      {screen === "drop_off" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          <MoneyField label={t("mobileOps.revenue.cash")} value={doCash} onChange={setNonRinseField(setDoCash)} />
          <MoneyField label={t("mobileOps.revenue.card")} value={doCard} onChange={setNonRinseField(setDoCard)} />
          <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
            Total: {fmtMoney(parseMoneyInput(doCash) + parseMoneyInput(doCard))}
          </Typography>
        </Stack>
      ) : null}

      {screen === "dhs" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          {!dhsAccounts.length ? (
            <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
              {t("mobileOps.revenue.noDhsAccounts")}
            </Typography>
          ) : (
            dhsAccounts.map((row) => {
              const draft = dhsDraft[row.account_id] || {};
              const isAbsolute = row.revenue_mode === "absolute";
              return (
                <Box
                  key={row.account_id}
                  sx={{
                    p: 1.25,
                    borderRadius: `${OPS_MOBILE.radius.card}px`,
                    border: "1px solid #e5e7eb",
                    bgcolor: "#fff",
                  }}
                >
                  <Typography sx={{ fontWeight: 800, mb: 1 }}>{row.name}</Typography>
                  {!isAbsolute ? (
                    <MoneyField
                      label={t("mobileOps.revenue.volumeLb")}
                      value={draft.volume ?? ""}
                      onChange={(v) =>
                        setDhsDraft((p) => ({
                          ...p,
                          [row.account_id]: { ...draft, volume: v },
                        }))
                      }
                    />
                  ) : null}
                  <Box sx={{ mt: 1 }}>
                    <MoneyField
                      label={
                        isAbsolute
                          ? t("mobileOps.revenue.revenue")
                          : t("mobileOps.revenue.revenueOverride")
                      }
                      value={draft.revenue ?? ""}
                      onChange={(v) =>
                        setDhsDraft((p) => ({
                          ...p,
                          [row.account_id]: { ...draft, revenue: v },
                        }))
                      }
                    />
                  </Box>
                </Box>
              );
            })
          )}
          {dhsAccounts.length ? (
            <Button
              variant="contained"
              onClick={saveDhs}
              disabled={saveState === "saving"}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
            >
              {saveState === "saving" ? t("mobileOps.revenue.saving") : t("mobileOps.revenue.saveDhs")}
            </Button>
          ) : null}
        </Stack>
      ) : null}

      {screen === "cash" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          {!addingPayout ? (
            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={() => setAddingPayout(true)}
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
            >
              {t("mobileOps.revenue.addPayout")}
            </Button>
          ) : (
            <Stack spacing={1.25}>
              <TextField
                label={t("mobileOps.revenue.purpose")}
                value={payoutPurpose}
                onChange={(e) => setPayoutPurpose(e.target.value)}
                fullWidth
                sx={{ "& .MuiInputBase-root": { minHeight: 56 } }}
              />
              <MoneyField
                label={t("mobileOps.revenue.amount")}
                value={payoutAmount}
                onChange={setPayoutAmount}
              />
              <TextField
                label={t("mobileOps.revenue.noteOptional")}
                value={payoutNote}
                onChange={(e) => setPayoutNote(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
              <Stack direction="row" spacing={1}>
                <Button
                  fullWidth
                  variant="outlined"
                  disabled={payoutBusy}
                  onClick={() => setAddingPayout(false)}
                  sx={{ textTransform: "none" }}
                >
                  {t("mobileOps.revenue.cancel")}
                </Button>
                <Button
                  fullWidth
                  variant="contained"
                  disabled={payoutBusy || !payoutPurpose.trim()}
                  onClick={submitPayout}
                  sx={{ textTransform: "none", fontWeight: 800 }}
                >
                  {payoutBusy ? t("mobileOps.revenue.saving") : t("mobileOps.revenue.save")}
                </Button>
              </Stack>
            </Stack>
          )}

          {!payouts.length ? (
            <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
              {t("mobileOps.revenue.noPayouts")}
            </Typography>
          ) : (
            payouts.map((p) => (
              <Stack
                key={p.id}
                direction="row"
                justifyContent="space-between"
                alignItems="flex-start"
                sx={{
                  p: 1.25,
                  borderRadius: `${OPS_MOBILE.radius.card}px`,
                  border: "1px solid #e5e7eb",
                  bgcolor: "#fff",
                }}
              >
                <Box sx={{ minWidth: 0, pr: 1 }}>
                  <Typography sx={{ fontWeight: 800, fontSize: 15 }}>{p.purpose}</Typography>
                  <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
                    {fmtMoney(p.amount)}
                    {p.entered_by ? ` · ${p.entered_by}` : ""}
                  </Typography>
                  {p.note ? (
                    <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.25 }}>{p.note}</Typography>
                  ) : null}
                </Box>
                <IconButton
                  size="small"
                  onClick={() => removePayout(p.id)}
                  aria-label={t("mobileOps.revenue.deletePayout")}
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            ))
          )}
        </Stack>
      ) : null}

      {screen === "hang_dry" ? (
        <Stack spacing={1} sx={{ pb: 2 }}>
          {hdLoading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
              <CircularProgress size={24} />
            </Box>
          ) : !hdOrders.length ? (
            <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 600, fontSize: 13 }}>
              {t("mobileOps.revenue.noHdOrders")}
            </Typography>
          ) : (
            hdOrders.map((order) => {
              const open = order.status === "open";
              return (
                <Box
                  key={`${order.bag_id}-${order.status}-${order.completion_at || "open"}`}
                  component="button"
                  type="button"
                  onClick={() => openHangDryDetail(order)}
                  sx={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    m: 0,
                    p: 1.25,
                    borderRadius: `${OPS_MOBILE.radius.card}px`,
                    border: "1px solid #e5e7eb",
                    bgcolor: "#fff",
                    cursor: "pointer",
                    appearance: "none",
                    fontFamily: "inherit",
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography sx={{ fontSize: 15, fontWeight: 800, fontFamily: "monospace" }}>
                      {order.bag_id}
                    </Typography>
                    <Typography sx={{ fontSize: 12, fontWeight: 700, color: OPS_MOBILE.muted }}>
                      {open ? t("mobileOps.revenue.inProcess") : t("mobileOps.revenue.completed")}
                    </Typography>
                  </Stack>
                  <Typography sx={{ mt: 0.5, fontSize: 12, color: OPS_MOBILE.muted, fontWeight: 600 }}>
                    {t("mobileOps.revenue.started", {
                      time: fmtTime(order.started_at),
                      operator: order.start_operator || "—",
                    })}
                  </Typography>
                  <Stack direction="row" spacing={2} sx={{ mt: 0.75 }}>
                    <Typography sx={{ fontSize: 13, fontWeight: 700 }}>
                      {t("mobileOps.revenue.itemsCount", { count: fmtInt(order.items) })}
                    </Typography>
                    <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(order.revenue)}</Typography>
                  </Stack>
                </Box>
              );
            })
          )}
        </Stack>
      ) : null}

      {screen === "hang_dry_detail" ? (
        <Stack spacing={1.5} sx={{ pb: 2 }}>
          {hdDetail?.loading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
              <CircularProgress size={24} />
            </Box>
          ) : (
            <>
              <Typography sx={{ fontWeight: 800, fontFamily: "monospace", fontSize: 16 }}>
                {hdDetail?.order?.bag_id || hdDetail?.bag_id || t("mobileOps.revenue.hdOrder")}
              </Typography>
              <MoneyField
                label={t("mobileOps.revenue.items")}
                value={hdItems}
                onChange={setHdItems}
                disabled={hdSaving}
              />
              <MoneyField
                label={t("mobileOps.revenue.revenue")}
                value={hdRevenue}
                onChange={setHdRevenue}
                disabled={hdSaving}
              />
              <Typography sx={{ fontSize: 12, color: OPS_MOBILE.muted }}>
                {t("mobileOps.revenue.started", {
                  time: fmtTime(hdDetail?.order?.started_at),
                  operator: hdDetail?.order?.start_operator || "—",
                })}
              </Typography>
              <Button
                variant="contained"
                disabled={hdSaving}
                onClick={() => saveHdProduction({ markComplete: false })}
                sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
              >
                {hdSaving ? t("mobileOps.revenue.saving") : t("mobileOps.revenue.save")}
              </Button>
              <Button
                variant="outlined"
                disabled={hdSaving}
                onClick={() => saveHdProduction({ markComplete: true })}
                sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
              >
                {t("mobileOps.revenue.saveComplete")}
              </Button>
            </>
          )}
        </Stack>
      ) : null}
    </OpsMobileShell>
  );
}
