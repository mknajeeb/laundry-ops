import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import {
  getManagementRinseHdDetail,
  markManagementRinseHdComplete,
  saveManagementRinseHdProduction,
} from "../api";
import MoneyAmountField from "../components/revenueShared/MoneyAmountField";
import SaveStatusChip from "../components/revenueShared/SaveStatusChip";
import { parseMoneyInput } from "../components/revenueShared/revenueFormat";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import HdMobileAwaitingCard from "./HdMobileAwaitingCard";
import { OPS_MOBILE } from "./tokens";

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

function statusLabel(status) {
  if (status === "awaiting_entry") return "Awaiting Entry";
  if (status === "washed") return "Washed";
  if (status === "pending_wash") return "Pending Wash";
  if (status === "complete") return "Complete";
  return status || "—";
}

function draftFromOrder(order) {
  return {
    items: order?.items != null ? order.items : null,
    revenue: order?.revenue != null ? order.revenue : null,
    version: order?.production_version ?? 0,
    saveState: "",
    saving: false,
  };
}

/**
 * Mobile Hang Dry awaiting-entry list: inline Items/Revenue on each card,
 * autosave draft, explicit Complete, detail bottom sheet on card tap.
 */
export default function HdMobileAwaitingEntryPanel({
  dateEt,
  orders,
  loading,
  error,
  onOrdersChanged,
  onError,
  t,
  completeSectionBusy,
  onCompleteSection,
  onNoActivity,
}) {
  const [drafts, setDrafts] = useState({});
  const draftsRef = useRef({});
  const timersRef = useRef({});
  const listScrollRef = useRef(null);
  const scrollRestoreRef = useRef(0);

  const [sheetBagId, setSheetBagId] = useState(null);
  const [sheetDetail, setSheetDetail] = useState(null);
  const [sheetLoading, setSheetLoading] = useState(false);

  useEffect(() => {
    draftsRef.current = drafts;
  }, [drafts]);

  useEffect(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      const ids = new Set();
      for (const order of orders || []) {
        const id = order.bag_id;
        if (!id) continue;
        ids.add(id);
        const existing = prev[id];
        if (existing?.saving || existing?.saveState === "saving") continue;
        next[id] = {
          ...draftFromOrder(order),
          saveState: existing?.saveState === "saved" ? "saved" : existing?.saveState || "",
        };
      }
      for (const key of Object.keys(next)) {
        if (!ids.has(key)) delete next[key];
      }
      return next;
    });
  }, [orders]);

  useEffect(() => {
    return () => {
      Object.values(timersRef.current).forEach((id) => clearTimeout(id));
      timersRef.current = {};
    };
  }, []);

  const patchDraft = useCallback((bagId, patch) => {
    setDrafts((prev) => {
      const base = prev[bagId] || draftFromOrder({});
      const next = { ...prev, [bagId]: { ...base, ...patch } };
      draftsRef.current = next;
      return next;
    });
  }, []);

  const saveProduction = useCallback(
    async (bagId, { markComplete = false } = {}) => {
      const draft = draftsRef.current[bagId];
      if (!bagId || !draft) return;
      patchDraft(bagId, { saving: true, saveState: "saving" });
      onError?.("");
      try {
        const saveRes = await saveManagementRinseHdProduction(bagId, {
          date_et: dateEt,
          total_items: draft.items === null || draft.items === "" ? null : Number(draft.items),
          revenue: parseMoneyInput(draft.revenue),
          version: draft.version ?? 0,
        });
        const nextVersion = saveRes.data?.version ?? draft.version ?? 0;
        patchDraft(bagId, { version: nextVersion });
        if (markComplete) {
          await markManagementRinseHdComplete(bagId, {
            date_et: dateEt,
            version: nextVersion,
          });
          if (sheetBagId === bagId) {
            setSheetBagId(null);
            setSheetDetail(null);
          }
          await onOrdersChanged?.();
          patchDraft(bagId, { saving: false, saveState: "saved" });
          return;
        }
        patchDraft(bagId, { saving: false, saveState: "saved", version: nextVersion });
        await onOrdersChanged?.({ quiet: true });
      } catch (e) {
        const msg =
          e?.response?.data?.message ||
          e?.response?.data?.error ||
          e?.message ||
          t("mobileOps.revenue.saveFailed");
        onError?.(msg);
        patchDraft(bagId, { saving: false, saveState: "error" });
      }
    },
    [dateEt, onError, onOrdersChanged, patchDraft, sheetBagId, t],
  );

  const scheduleAutosave = useCallback(
    (bagId) => {
      if (timersRef.current[bagId]) clearTimeout(timersRef.current[bagId]);
      patchDraft(bagId, { saveState: "saving" });
      timersRef.current[bagId] = setTimeout(() => {
        saveProduction(bagId, { markComplete: false });
      }, 700);
    },
    [patchDraft, saveProduction],
  );

  const openSheet = useCallback(
    async (order) => {
      if (!order?.bag_id) return;
      if (listScrollRef.current) {
        scrollRestoreRef.current = listScrollRef.current.scrollTop || 0;
      }
      setSheetBagId(order.bag_id);
      setSheetLoading(true);
      setSheetDetail({ order });
      onError?.("");
      try {
        const res = await getManagementRinseHdDetail(order.bag_id, { date_et: dateEt });
        setSheetDetail(res.data || { order });
        const prod = res.data?.production || res.data?.order || {};
        const existing = draftsRef.current[order.bag_id];
        if (!existing?.saving && existing?.saveState !== "saving") {
          patchDraft(order.bag_id, {
            items: prod.items != null ? prod.items : order.items != null ? order.items : null,
            revenue:
              prod.revenue != null ? prod.revenue : order.revenue != null ? order.revenue : null,
            version: prod.version ?? order.production_version ?? 0,
          });
        }
      } catch (e) {
        onError?.(e?.response?.data?.error || e?.message || t("mobileOps.revenue.loadOrderFailed"));
        setSheetDetail({ order });
      } finally {
        setSheetLoading(false);
      }
    },
    [dateEt, onError, patchDraft, t],
  );

  const closeSheet = useCallback(() => {
    setSheetBagId(null);
    setSheetDetail(null);
    requestAnimationFrame(() => {
      if (listScrollRef.current) {
        listScrollRef.current.scrollTop = scrollRestoreRef.current || 0;
      }
    });
  }, []);

  const saveLabels = {
    saving: t("mobileOps.revenue.saving"),
    saved: t("mobileOps.revenue.savedCheck"),
    error: t("mobileOps.revenue.saveFailed"),
  };

  const cardLabels = {
    washedBy: "Washed by",
    foldedBy: "Folded by",
    items: t("mobileOps.revenue.items"),
    revenue: t("mobileOps.revenue.revenue"),
    complete: t("mobileOps.revenue.complete"),
    saving: t("mobileOps.revenue.saving"),
  };

  const sheetOrder = sheetDetail?.order || orders?.find((o) => o.bag_id === sheetBagId) || null;
  const sheetDraft = sheetBagId ? drafts[sheetBagId] : null;

  return (
    <Stack
      spacing={1.25}
      sx={{ pb: 2, flex: 1, minHeight: 0 }}
      data-hd-mobile-inline-entry="1"
    >
      <Typography sx={{ fontSize: 13, fontWeight: 700, color: OPS_MOBILE.muted }}>
        {t("mobileOps.revenue.hdAwaitingHint")}
      </Typography>

      {loading ? (
        <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {!loading && !(orders || []).length ? (
        <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted }}>
          {t("mobileOps.revenue.noHdOrders")}
        </Typography>
      ) : null}

      <Box
        ref={listScrollRef}
        sx={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 1.25,
          WebkitOverflowScrolling: "touch",
        }}
      >
        {(orders || []).map((order) => {
          const draft = drafts[order.bag_id] || draftFromOrder(order);
          return (
            <HdMobileAwaitingCard
              key={order.bag_id}
              order={order}
              items={draft.items}
              revenue={draft.revenue}
              saveState={draft.saveState}
              saveLabels={saveLabels}
              completing={Boolean(draft.saving)}
              onOpenDetail={openSheet}
              onItemsChange={(v) => {
                patchDraft(order.bag_id, { items: v });
                scheduleAutosave(order.bag_id);
              }}
              onRevenueChange={(v) => {
                patchDraft(order.bag_id, { revenue: v });
                scheduleAutosave(order.bag_id);
              }}
              onComplete={() => saveProduction(order.bag_id, { markComplete: true })}
              labels={cardLabels}
            />
          );
        })}
      </Box>

      {error ? (
        <Typography sx={{ fontSize: 13, color: "#b91c1c", fontWeight: 700 }}>{error}</Typography>
      ) : null}

      <Button
        variant="contained"
        disabled={Boolean(completeSectionBusy)}
        onClick={onCompleteSection}
        sx={{ textTransform: "none", fontWeight: 900, minHeight: 48 }}
      >
        {t("mobileOps.revenue.complete")}
      </Button>
      <Button
        variant="outlined"
        disabled={Boolean(completeSectionBusy)}
        onClick={onNoActivity}
        sx={{ textTransform: "none", fontWeight: 700, minHeight: 44 }}
      >
        {t("mobileOps.revenue.noActivity")}
      </Button>

      <Drawer
        anchor="bottom"
        open={Boolean(sheetBagId)}
        onClose={closeSheet}
        PaperProps={{
          sx: {
            maxHeight: "88vh",
            borderTopLeftRadius: 16,
            borderTopRightRadius: 16,
            px: 2,
            pt: 1.5,
            pb: 2.5,
          },
        }}
      >
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 900, fontSize: 18 }}>
            {t("mobileOps.revenue.hdOrder")}
          </Typography>
          <IconButton aria-label="Close" onClick={closeSheet} edge="end">
            <CloseIcon />
          </IconButton>
        </Stack>
        {sheetLoading ? (
          <Box sx={{ py: 4, display: "grid", placeItems: "center" }}>
            <CircularProgress size={28} />
          </Box>
        ) : (
          <Stack spacing={1.25} sx={{ overflowY: "auto" }} data-hd-mobile-detail-sheet="1">
            <Typography sx={{ fontWeight: 900, fontSize: 20, color: "#0f172a" }}>
              {sheetOrder?.customer_name || sheetOrder?.customer || "—"}
            </Typography>
            <Typography sx={{ fontWeight: 800, fontSize: 16, fontFamily: "monospace" }}>
              {sheetOrder?.bag_id || sheetBagId || "—"}
            </Typography>
            <Chip
              size="small"
              label={statusLabel(sheetOrder?.status || "awaiting_entry")}
              sx={{ alignSelf: "flex-start", fontWeight: 700, bgcolor: "#fff7ed", color: "#9a3412" }}
            />
            <Box>
              <Typography sx={{ fontSize: 14, fontWeight: 700 }}>
                Washed by {sheetOrder?.washed_by_name || sheetDetail?.production?.washed_by_name || "—"}
              </Typography>
              <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted, fontWeight: 600 }}>
                {fmtTime(sheetOrder?.washed_at || sheetDetail?.production?.washed_at)}
              </Typography>
            </Box>
            <Box>
              <Typography sx={{ fontSize: 14, fontWeight: 700 }}>
                Folded by {sheetOrder?.folded_by_name || sheetDetail?.production?.folded_by_name || "—"}
              </Typography>
              <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted, fontWeight: 600 }}>
                {fmtTime(sheetOrder?.folded_at || sheetDetail?.production?.folded_at)}
              </Typography>
            </Box>
            {sheetOrder?.revenue_date_et ? (
              <Typography sx={{ fontSize: 13, color: OPS_MOBILE.muted, fontWeight: 600 }}>
                Revenue date {sheetOrder.revenue_date_et}
              </Typography>
            ) : null}

            {sheetDraft ? (
              <>
                <MoneyAmountField
                  label={t("mobileOps.revenue.items")}
                  value={sheetDraft.items}
                  prefix=""
                  onChange={(v) => {
                    patchDraft(sheetBagId, { items: v });
                    scheduleAutosave(sheetBagId);
                  }}
                />
                <MoneyAmountField
                  label={t("mobileOps.revenue.revenue")}
                  value={sheetDraft.revenue}
                  onChange={(v) => {
                    patchDraft(sheetBagId, { revenue: v });
                    scheduleAutosave(sheetBagId);
                  }}
                />
                <SaveStatusChip state={sheetDraft.saveState} labels={saveLabels} />
                <Button
                  variant="contained"
                  disabled={sheetDraft.saving}
                  onClick={() => saveProduction(sheetBagId, { markComplete: true })}
                  sx={{ textTransform: "none", fontWeight: 900, minHeight: 56, fontSize: 17 }}
                >
                  {t("mobileOps.revenue.complete")}
                </Button>
              </>
            ) : null}

            {(sheetDetail?.chronology || []).length ? (
              <Box sx={{ mt: 0.5 }}>
                <Typography sx={{ fontSize: 13, fontWeight: 800, mb: 0.75 }}>Timeline</Typography>
                <Stack spacing={0.75}>
                  {(sheetDetail.chronology || []).slice(-12).map((ev, idx) => (
                    <Typography
                      key={`${ev.id || idx}-${ev.at}`}
                      sx={{ fontSize: 12, color: "#475569", fontWeight: 600 }}
                    >
                      {fmtTime(ev.at)} · {ev.purpose || "—"}
                      {ev.user_name ? ` · ${ev.user_name}` : ""}
                    </Typography>
                  ))}
                </Stack>
              </Box>
            ) : null}
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}
