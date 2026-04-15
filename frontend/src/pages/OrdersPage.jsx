import { useEffect, useMemo, useState, useDeferredValue, useRef } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import {
  Bolt,
  CheckCircle,
  ExpandLess,
  ExpandMore,
  Inventory2,
  QrCodeScanner,
  Refresh,
  SortByAlpha,
} from "@mui/icons-material";
import { useNavigate } from "react-router-dom";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import OpsAlphaJumpRail from "../components/layout/OpsAlphaJumpRail";
import OpsSearchBar from "../components/layout/OpsSearchBar";
import RushTabCountBar from "../components/layout/RushTabCountBar";
import OrderScanLookupBar from "../components/OrderScanLookupBar";
import { useI18n } from "../i18n/I18nContext";
import { formatSystemDateLong } from "../utils/formatDateLocal";
import { getOpsAlphaPaletteForLetter, opsAlphaEmptySectionSx } from "../utils/opsAlphaIndex";
import { getCurrentUploadBatch, getOrders } from "../api";
import { displayCustomerName } from "../utils/displayCustomerName";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const WF_BG = "#141922";
const HD_BG = "#0a869d";
const BROWSE_STORAGE_ORDERS = "washpro_ops_browse_orders";
const SCAN_STORAGE_ORDERS = "washpro_ops_scan_orders";

function parseAsLocalDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return null;
  return new Date(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate());
}

function normalizeCode(value) {
  return String(value || "").trim().toUpperCase();
}

function OrdersPage({ user }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const isMobile = useMediaQuery("(max-width:900px)");
  const alphaRefs = useRef({});
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const [rushFilter, setRushFilter] = useState("ALL"); // ALL | RUSH | NON-RUSH
  const [showProcessed, setShowProcessed] = useState(false);
  const [showBrowse, setShowBrowse] = useState(() => localStorage.getItem(BROWSE_STORAGE_ORDERS) === "1");
  const [scanEnabled, setScanEnabled] = useState(() => localStorage.getItem(SCAN_STORAGE_ORDERS) !== "0");
  const [openAlpha, setOpenAlpha] = useState(null);

  const [notice, setNotice] = useState("");
  const [batchInfo, setBatchInfo] = useState(null);

  const userId = Number(user?.user_id || 0);

  const load = async () => {
    try {
      setLoading(true);
      const [ordersRes, batchRes] = await Promise.allSettled([
        getOrders({ include_all: true }),
        getCurrentUploadBatch(),
      ]);

      if (ordersRes.status === "fulfilled") {
        setRows(Array.isArray(ordersRes.value?.data) ? ordersRes.value.data : []);
      }

      if (batchRes.status === "fulfilled") {
        setBatchInfo(batchRes.value?.data || null);
      } else {
        setBatchInfo(null);
      }

      setNotice("");
    } catch (error) {
      console.error(error);
      setNotice(error?.response?.data?.error || "Failed to load orders.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    localStorage.setItem(BROWSE_STORAGE_ORDERS, showBrowse ? "1" : "0");
  }, [showBrowse]);

  const normalizeLogistics = (r) => {
    const v = normalizeCode(r?.logistics_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
    if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
    return "AT_WASHPRO";
  };

  const normalizeProcessing = (r) => {
    const v = normalizeCode(r?.processing_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    return s === "PROCESSED" ? "PROCESSED" : "PENDING";
  };

  const rushOf = (r) => normalizeCode(r?.rush_type) === "RUSH" ? "RUSH" : "NON-RUSH";
  const serviceOf = (r) => normalizeCode(r?.service_type);
  const isHD = (r) => serviceOf(r) === "HD";

  const formatMeasure = (r) => {
    const n = Number(r?.weight_num ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };

  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const visibleRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();

    return rows.filter((r) => {
      if (normalizeLogistics(r) !== "AT_WASHPRO") return false;

      const proc = normalizeProcessing(r);
      if (showProcessed) {
        if (proc !== "PROCESSED") return false;
        if (userId && Number(r?.processed_by_user_id || 0) !== userId) return false;
      } else if (proc !== "PENDING") {
        return false;
      }

      if (rushFilter !== "ALL" && rushOf(r) !== rushFilter) return false;

      if (!q) return true;
      const name = String(r?.name_clean || "").toLowerCase();
      const disp = displayCustomerName(r?.name_clean || "").toLowerCase();
      const tid = String(r?.ticket_id || "").toLowerCase();
      const id = String(r?.id || "").toLowerCase();
      const service = String(r?.service_type || "").toLowerCase();
      const weight = String(r?.weight_num ?? "").toLowerCase();
      return (
        name.includes(q) ||
        disp.includes(q) ||
        tid.includes(q) ||
        id.startsWith(q) ||
        service.includes(q) ||
        weight.includes(q)
      );
    });
  }, [rows, deferredSearch, rushFilter, showProcessed, userId]);

  const grouped = useMemo(() => {
    const out = {};
    for (const a of ALPHAS) out[a] = [];
    for (const r of visibleRows) {
      const c = String(displayCustomerName(r?.name_clean || "")).trim().charAt(0).toUpperCase();
      const k = /^[A-Z]$/.test(c) ? c : "A";
      out[k].push(r);
    }
    return out;
  }, [visibleRows]);

  const sequentialFolded = useMemo(() => {
    return [...visibleRows].sort((a, b) => {
      const na = displayCustomerName(a?.name_clean || "").toLowerCase();
      const nb = displayCustomerName(b?.name_clean || "").toLowerCase();
      const cmp = na.localeCompare(nb);
      if (cmp) return cmp;
      return Number(a?.id || 0) - Number(b?.id || 0);
    });
  }, [visibleRows]);

  const counts = useMemo(() => {
    const base = rows.filter((r) => normalizeLogistics(r) === "AT_WASHPRO");
    const pending = base.filter((r) => normalizeProcessing(r) === "PENDING");
    const mine = base.filter(
      (r) => normalizeProcessing(r) === "PROCESSED" && (!userId || Number(r?.processed_by_user_id || 0) === userId)
    );
    return {
      all: showProcessed ? mine.length : pending.length,
      rush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "RUSH").length,
      nonRush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "NON-RUSH").length,
    };
  }, [rows, showProcessed, userId]);

  const toggleAlpha = (alpha) => setOpenAlpha((prev) => (prev === alpha ? null : alpha));

  useEffect(() => {
    const q = deferredSearch.trim();
    if (!q || visibleRows.length === 0) return;
    const first = visibleRows[0];
    const c = String(displayCustomerName(first?.name_clean || "")).trim().charAt(0).toUpperCase();
    const alpha = /^[A-Z]$/.test(c) ? c : "A";
    setOpenAlpha(alpha);
  }, [deferredSearch, visibleRows]);

  const activeBatchDate = batchInfo?.batch_date || rows[0]?.batch_date || null;
  const batchDateScan = activeBatchDate ? String(activeBatchDate).slice(0, 10) : "";
  const searchActive = deferredSearch.trim().length > 0;

  const openDryerFlow = (r) => {
    if (showProcessed) return;
    if (normalizeProcessing(r) !== "PENDING") return;
    const st = String(r.gaming_flow_status || "").toUpperCase();
    if (st === "COMPLETED") return;
    const lockUid = Number(r.gaming_locked_by_user_id || 0);
    if (st === "ACTIVE" && lockUid && lockUid !== userId) {
      setNotice("This order is in use by another team member.");
      return;
    }
    navigate(`/orders/${r.id}/dryer-flow`);
  };

  const onScanPickOrder = (o) => {
    const st = String(o?.gaming_flow_status || "").toUpperCase();
    const lockUid = Number(o?.gaming_locked_by_user_id || 0);
    if (st === "ACTIVE" && lockUid && lockUid !== userId) {
      setNotice("This order is in use by another team member.");
      return;
    }
    if (st === "COMPLETED") {
      setNotice("Dryer assignment already completed. Use Upload → batch staging to submit or adjust.");
      return;
    }
    navigate(`/orders/${Number(o.id)}/dryer-flow`);
  };

  const renderOrderCard = (r) => {
    const rush = rushOf(r) === "RUSH";
    const hd = isHD(r);
    const pending = normalizeProcessing(r) === "PENDING";
    const gameSt = String(r.gaming_flow_status || "").toUpperCase();
    const lockUid = Number(r.gaming_locked_by_user_id || 0);
    const lockedOther = gameSt === "ACTIVE" && lockUid && lockUid !== userId;
    const lockedMe = gameSt === "ACTIVE" && lockUid === userId;
    const gameDone = gameSt === "COMPLETED";
    const cardCursor = showProcessed || !pending || gameDone || lockedOther ? "default" : "pointer";
    const showName = displayCustomerName(r.name_clean);
    const nameSize = 38 > String(showName || "").length ? 20 : 18;
    return (
      <Paper
        key={r.id}
        sx={{
          borderRadius: 2,
          bgcolor: hd ? HD_BG : WF_BG,
          color: "#ffffff",
          border: hd ? "1px solid #44c3d6" : "1px solid #2b3342",
          outline: lockedOther ? "3px solid #fb923c" : lockedMe ? "3px solid #facc15" : gameDone ? "3px solid #4ade80" : "none",
          outlineOffset: 1,
        }}
      >
        <Box
          role={!showProcessed && pending && !gameDone && !lockedOther ? "button" : undefined}
          onClick={() => openDryerFlow(r)}
          sx={{
            p: 1.2,
            cursor: cardCursor,
            opacity: lockedOther ? 0.72 : 1,
          }}
        >
          <Stack spacing={0.9}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Stack direction="row" spacing={0.7} alignItems="center">
                {rush ? <Bolt sx={{ fontSize: 20, color: "#ffcb5b" }} /> : <CheckCircle sx={{ fontSize: 17, color: "#d1fae5" }} />}
                <Typography sx={{ fontSize: 13, letterSpacing: 0.5, opacity: 0.9, fontWeight: 400 }}>
                  {rush ? "RUSH" : "NON-RUSH"}
                </Typography>
              </Stack>
              <Typography sx={{ fontSize: 13, opacity: 0.85, fontWeight: 400 }}>
                {pending ? "Pending" : "Processed"}
                {lockedOther ? " • In use" : lockedMe ? " • You" : gameDone ? " • Dryers OK" : ""}
              </Typography>
            </Stack>

            <Typography sx={{ fontSize: nameSize, lineHeight: 1.15, fontWeight: 400 }}>{showName}</Typography>
            {r.ticket_id ? (
              <Typography sx={{ fontSize: 15, opacity: 0.9, fontWeight: 500 }}>
                {t("ops.bagIdShort")} {String(r.ticket_id)}
              </Typography>
            ) : null}

            <Typography sx={{ fontSize: 16, opacity: 0.92, fontWeight: 400 }}>
              {formatDate(r.date_clean)} • {formatMeasure(r)}
            </Typography>
          </Stack>
        </Box>
      </Paper>
    );
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        px: { xs: 1, sm: 1.5 },
        py: 1,
        background:
          "linear-gradient(168deg, #ecfdf5 0%, #d1fae5 26%, #f0fdf4 58%, #f7fef9 100%)",
      }}
    >
      <StandardScreenHeader
        title={isMobile ? undefined : "Rinse orders"}
        titleRight={
          isMobile ? undefined : (
            <Typography sx={{ fontSize: 12, fontWeight: 600, color: "text.secondary", whiteSpace: "nowrap" }}>
              {formatSystemDateLong()}
            </Typography>
          )
        }
        dense
        mid={
          <>
            <Tooltip title={showProcessed ? t("ops.foldedShowMine") : t("ops.foldedShowPending")}>
              <IconButton
                size="large"
                onClick={() => setShowProcessed((p) => !p)}
                aria-pressed={showProcessed}
                sx={{
                  bgcolor: showProcessed ? "primary.main" : "rgba(226, 232, 240, 0.95)",
                  color: showProcessed ? "#fff" : "#334155",
                  width: 48,
                  height: 48,
                  "&:hover": { bgcolor: showProcessed ? "primary.dark" : "rgba(203, 213, 225, 0.95)" },
                }}
              >
                <Inventory2 />
              </IconButton>
            </Tooltip>
            <Tooltip title={scanEnabled ? t("ops.scanToggleOnHint") : t("ops.scanToggleOffHint")}>
              <IconButton
                size="large"
                onClick={() => setScanEnabled((v) => !v)}
                aria-pressed={scanEnabled}
                sx={{
                  bgcolor: scanEnabled ? "rgba(219, 234, 254, 0.98)" : "rgba(226, 232, 240, 0.95)",
                  color: scanEnabled ? "primary.main" : "#64748b",
                  width: 48,
                  height: 48,
                  border: scanEnabled ? "2px solid" : "none",
                  borderColor: "primary.main",
                  "&:hover": { bgcolor: scanEnabled ? "rgba(191, 219, 254, 0.98)" : "rgba(203, 213, 225, 0.95)" },
                }}
              >
                <QrCodeScanner />
              </IconButton>
            </Tooltip>
            <Tooltip title={showBrowse ? t("ops.indexToggleOnHint") : t("ops.indexToggleOffHint")}>
              <IconButton
                size="large"
                onClick={() => setShowBrowse((v) => !v)}
                aria-pressed={showBrowse}
                sx={{
                  bgcolor: showBrowse ? "rgba(219, 234, 254, 0.98)" : "rgba(226, 232, 240, 0.95)",
                  color: showBrowse ? "primary.main" : "#64748b",
                  width: 48,
                  height: 48,
                  border: showBrowse ? "2px solid" : "none",
                  borderColor: "primary.main",
                  "&:hover": { bgcolor: showBrowse ? "rgba(191, 219, 254, 0.98)" : "rgba(203, 213, 225, 0.95)" },
                }}
              >
                <SortByAlpha />
              </IconButton>
            </Tooltip>
          </>
        }
        right={
          <Tooltip title={t("common.refresh")}>
            <IconButton
              size="large"
              onClick={load}
              sx={{
                bgcolor: "rgba(219, 234, 254, 0.95)",
                color: "primary.main",
                width: 48,
                height: 48,
                "&:hover": { bgcolor: "rgba(191, 219, 254, 0.98)" },
              }}
            >
              <Refresh />
            </IconButton>
          </Tooltip>
        }
      />

      <OrderScanLookupBar
        variant="embedded"
        compactEmbedded
        scanEnabled={scanEnabled}
        onScanEnabledChange={setScanEnabled}
        storageKey="washpro_scan_lookup_orders"
        batchDate={batchDateScan}
        onPickOrder={onScanPickOrder}
      />

      <RushTabCountBar
        variant="cards"
        value={rushFilter}
        onChange={setRushFilter}
        tabs={[
          { key: "ALL", label: "All", count: counts.all },
          { key: "RUSH", label: "Rush", count: counts.rush, Icon: Bolt, accent: "#b91c1c" },
          { key: "NON-RUSH", label: "Non-Rush", count: counts.nonRush, Icon: CheckCircle, accent: "#0f766e" },
        ]}
      />

      {(showProcessed || (!showProcessed && showBrowse)) && (
        <OpsSearchBar value={search} onChange={setSearch} placeholder={t("ops.searchNameHint")} />
      )}

      {!loading && !showProcessed && showBrowse && (
        <OpsAlphaJumpRail
          letters={ALPHAS}
          ariaLabelFor={(letter) => t("ops.jumpLetter").replace("{l}", letter)}
          onPick={(letter) => {
            setOpenAlpha(letter);
            requestAnimationFrame(() => {
              alphaRefs.current[letter]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
            });
          }}
        />
      )}

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
          <CircularProgress size={26} />
          <Typography color="text.secondary">Loading...</Typography>
        </Stack>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {showProcessed ? (
            sequentialFolded.length === 0 ? (
              <Typography sx={{ color: "#64748b", fontSize: 13 }}>{t("ops.emptyOrdersLetter")}</Typography>
            ) : (
              <Stack spacing={1}>{sequentialFolded.map((r) => renderOrderCard(r))}</Stack>
            )
          ) : showBrowse ? (
            ALPHAS.map((alpha) => {
              const list = grouped[alpha] || [];
              if (searchActive && list.length === 0) return null;
              const expanded = searchActive ? true : openAlpha === alpha;
              const pal = getOpsAlphaPaletteForLetter(alpha);
              return (
                <Paper
                  key={alpha}
                  ref={(el) => {
                    alphaRefs.current[alpha] = el;
                  }}
                  sx={{
                    borderRadius: 2,
                    border: `1px solid ${pal.border}`,
                    overflow: "hidden",
                    transition: "border-color 0.15s ease, background-color 0.15s ease",
                    ...opsAlphaEmptySectionSx(list.length),
                  }}
                >
                  <Button
                    fullWidth
                    onClick={() => toggleAlpha(alpha)}
                    sx={{
                      px: 1.25,
                      py: 1.35,
                      minHeight: 56,
                      justifyContent: "space-between",
                      textTransform: "none",
                      color: "#0f172a",
                      bgcolor: pal.rowBg,
                    }}
                  >
                    <Stack direction="row" spacing={1.35} alignItems="center">
                      <Box
                        sx={{
                          width: 42,
                          height: 42,
                          borderRadius: "50%",
                          display: "grid",
                          placeItems: "center",
                          bgcolor: pal.chipBg,
                          color: pal.chipColor,
                          fontSize: 18,
                          fontWeight: 700,
                          letterSpacing: 0.02,
                          boxShadow: list.length === 0 ? "none" : "0 2px 8px rgba(15,23,42,0.12)",
                        }}
                      >
                        {alpha}
                      </Box>
                      <Typography sx={{ fontSize: 17, fontWeight: 600 }}>
                        {t("ops.nBags").replace("{n}", String(list.length))}
                      </Typography>
                    </Stack>
                    {expanded ? <ExpandLess sx={{ fontSize: 26, color: "#334155" }} /> : <ExpandMore sx={{ fontSize: 26, color: "#334155" }} />}
                  </Button>

                  {expanded && (
                    <Box sx={{ p: 1 }}>
                      {list.length === 0 ? (
                        <Typography sx={{ color: "#64748b", fontSize: 13 }}>{t("ops.emptyOrdersLetter")}</Typography>
                      ) : (
                        <Stack spacing={1}>{list.map((r) => renderOrderCard(r))}</Stack>
                      )}
                    </Box>
                  )}
                </Paper>
              );
            })
          ) : (
            <Stack spacing={1}>
              {sequentialFolded.length === 0 ? (
                <Typography sx={{ color: "#64748b", fontSize: 13 }}>{t("ops.emptyOrdersLetter")}</Typography>
              ) : (
                sequentialFolded.map((r) => renderOrderCard(r))
              )}
            </Stack>
          )}
        </Stack>
      )}

      <Dialog open={Boolean(notice)} onClose={() => setNotice("")} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Confirmation</DialogTitle>
        <DialogContent dividers>
          <Typography sx={{ fontWeight: 400 }}>{notice}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNotice("")} sx={{ fontWeight: 400 }}>OK</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
