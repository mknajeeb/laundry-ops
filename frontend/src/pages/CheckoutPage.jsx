import { useCallback, useEffect, useMemo, useState, useDeferredValue, useRef } from "react";
import {
  Alert,
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
  ChevronRight,
  ExpandLess,
  ExpandMore,
  GridView,
  LocalShipping,
  QrCodeScanner,
  Refresh,
  Send,
  SortByAlpha,
  Undo,
} from "@mui/icons-material";
import { checkoutOrder, getCheckoutBatchSummary, getCheckoutLog, getOrders, undoCheckout } from "../api";
import TaOperationalBanner from "../components/TaOperationalBanner";
import { useTaOperationalGate } from "../hooks/useTaOperationalGate";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import OpsAlphaJumpRail from "../components/layout/OpsAlphaJumpRail";
import OpsSearchBar from "../components/layout/OpsSearchBar";
import RushTabCountBar from "../components/layout/RushTabCountBar";
import OrderScanLookupBar from "../components/OrderScanLookupBar";
import { useI18n } from "../i18n/I18nContext";
import { formatSystemDateLong } from "../utils/formatDateLocal";
import { getOpsAlphaPaletteForLetter, opsAlphaEmptySectionSx } from "../utils/opsAlphaIndex";
import { displayCustomerName } from "../utils/displayCustomerName";
import { useAuth } from "../context/AuthContext";
import { scanBrowseDefaultsFromOpsUi } from "../utils/opsScanBrowseDefaults";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const BROWSE_STORAGE_CHECKOUT = "washpro_ops_browse_checkout";
const SCAN_STORAGE_CHECKOUT = "washpro_ops_scan_checkout";

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

function CheckoutPage() {
  const { t } = useI18n();
  const { opsUi } = useAuth();
  const masterScan = opsUi?.scan_lookup_enabled !== false;
  const masterBrowse = opsUi?.browse_list_enabled !== false;
  const isMobile = useMediaQuery("(max-width:900px)");
  const { checkoutBlocked, assertCanCheckout, bannerMessage } = useTaOperationalGate();
  const scanDisabled = checkoutBlocked;
  const alphaQueueRefs = useRef({});

  const [rows, setRows] = useState([]);
  const [checkedRows, setCheckedRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [rushTab, setRushTab] = useState("ALL");
  const [openAlpha, setOpenAlpha] = useState(null);
  const [showBrowse, setShowBrowse] = useState(() => scanBrowseDefaultsFromOpsUi(opsUi).browse);
  const [scanEnabled, setScanEnabled] = useState(() => scanBrowseDefaultsFromOpsUi(opsUi).scan);
  const [sentDrawerOpen, setSentDrawerOpen] = useState(false);
  const [activeRow, setActiveRow] = useState(null);
  const [nameConfirmDialog, setNameConfirmDialog] = useState(null);
  const [nameConfirmSelectedId, setNameConfirmSelectedId] = useState(null);
  const [undoRow, setUndoRow] = useState(null);
  const [batchSummary, setBatchSummary] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [ordersRes, checkedRes, summaryRes] = await Promise.allSettled([
        getOrders({ include_all: true }),
        getCheckoutLog(),
        getCheckoutBatchSummary(),
      ]);

      if (ordersRes.status === "fulfilled") {
        const allRows = Array.isArray(ordersRes.value?.data) ? ordersRes.value.data : [];
        const active = allRows.filter((r) => {
          const l = normalizeCode(r?.logistics_status || r?.status);
          return !["SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(l);
        });
        setRows(active);
      }

      if (checkedRes.status === "fulfilled") {
        setCheckedRows(Array.isArray(checkedRes.value?.data) ? checkedRes.value.data : []);
      }

      if (summaryRes.status === "fulfilled") {
        setBatchSummary(summaryRes.value?.data || null);
      } else {
        setBatchSummary(null);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    localStorage.setItem(BROWSE_STORAGE_CHECKOUT, showBrowse ? "1" : "0");
  }, [showBrowse]);

  useEffect(() => {
    localStorage.setItem(SCAN_STORAGE_CHECKOUT, scanEnabled ? "1" : "0");
  }, [scanEnabled]);

  useEffect(() => {
    const d = scanBrowseDefaultsFromOpsUi(opsUi);
    setScanEnabled(d.scan);
    setShowBrowse(d.browse);
  }, [opsUi?.scan_lookup_enabled, opsUi?.browse_list_enabled]);

  const effectiveShowBrowse = masterBrowse && showBrowse;
  const effectiveScanEnabled = masterScan && scanEnabled;

  const rushOf = (r) => {
    const raw = String(r?.rush_type ?? "").trim();
    if (raw) {
      return normalizeCode(raw) === "RUSH" ? "RUSH" : "NON-RUSH";
    }
    if (r?.rush_date) {
      const due = parseAsLocalDate(r.rush_date);
      if (!due) return "NON-RUSH";
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      due.setHours(0, 0, 0, 0);
      return due < today ? "RUSH" : "NON-RUSH";
    }
    return "NON-RUSH";
  };

  const serviceOf = (r) => normalizeCode(r?.service_type);
  const isHD = (r) => serviceOf(r) === "HD";
  const measureOf = (r) => {
    const n = Number(r?.weight_num ?? r?.weight ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };

  const logMeasureOf = (r) => {
    const svc = normalizeCode(r?.service);
    const n = Number(r?.weight ?? 0);
    if (svc === "HD") return `${Math.round(n)} pcs`;
    return `${n.toFixed(2)} lb`;
  };
  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const normalizeName = (value) => String(value || "").trim().toLowerCase();
  const nameOf = (r) => displayCustomerName(String(r?.name_clean || r?.name || "").trim());

  const alphaOf = useCallback((row) => {
    const ch = displayCustomerName(String(row?.name_clean || row?.name || "").trim())
      .charAt(0)
      .toUpperCase();
    return /^[A-Z]$/.test(ch) ? ch : "#";
  }, []);

  const searchFilteredRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      const name = String(r?.name_clean || "").toLowerCase();
      const disp = displayCustomerName(r?.name_clean || "").toLowerCase();
      const tid = String(r?.ticket_id || "").toLowerCase();
      const id = String(r?.id || "").toLowerCase();
      const svc = String(r?.service_type || "").toLowerCase();
      const w = String(r?.weight_num ?? r?.weight ?? "").toLowerCase();
      return (
        name.includes(q) ||
        disp.includes(q) ||
        tid.includes(q) ||
        id.startsWith(q) ||
        svc.includes(q) ||
        w.includes(q)
      );
    });
  }, [rows, deferredSearch]);

  const queueForRushTab = useMemo(() => {
    if (rushTab === "ALL") return searchFilteredRows;
    return searchFilteredRows.filter((r) => rushOf(r) === rushTab);
  }, [searchFilteredRows, rushTab]);

  const groupedQueue = useMemo(() => {
    const groups = {};
    queueForRushTab.forEach((row) => {
      const alpha = alphaOf(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });
    ALPHAS.forEach((k) => {
      if (!groups[k]) groups[k] = [];
      groups[k].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
    });
    if (groups["#"]?.length) {
      groups["#"].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
      return { keys: [...ALPHAS, "#"], groups };
    }
    return { keys: ALPHAS, groups };
  }, [queueForRushTab, alphaOf]);

  const sequentialCheckoutRows = useMemo(() => {
    return [...queueForRushTab].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
  }, [queueForRushTab]);

  const sentSequential = useMemo(() => {
    return [...checkedRows].sort((a, b) => {
      const na = displayCustomerName(String(a?.name || a?.name_clean || "").trim()).toLowerCase();
      const nb = displayCustomerName(String(b?.name || b?.name_clean || "").trim()).toLowerCase();
      const cmp = na.localeCompare(nb);
      if (cmp) return cmp;
      return String(b.checkout_time || "").localeCompare(String(a.checkout_time || ""));
    });
  }, [checkedRows]);

  const counters = useMemo(() => {
    const rushInQueue = searchFilteredRows.filter((r) => rushOf(r) === "RUSH").length;
    const nonRushInQueue = searchFilteredRows.filter((r) => rushOf(r) === "NON-RUSH").length;
    const batchRush = batchSummary?.rush || {};
    const batchNonRush = batchSummary?.non_rush || {};
    const rushTotal = batchRush.total != null ? Number(batchRush.total) : rushInQueue;
    const nonRushTotal = batchNonRush.total != null ? Number(batchNonRush.total) : nonRushInQueue;
    const rushCheckedOut = Number(batchRush.checked_out || 0);
    const nonRushCheckedOut = Number(batchNonRush.checked_out || 0);
    const rushExcluded =
      Number(batchRush.excluded_already_completed || 0) + Number(batchRush.excluded_not_staged || 0);
    const nonRushExcluded =
      Number(batchNonRush.excluded_already_completed || 0) + Number(batchNonRush.excluded_not_staged || 0);
    return {
      allCount: searchFilteredRows.length,
      rushInQueue,
      nonRushInQueue,
      rushTotal,
      nonRushTotal,
      rushCheckedOut,
      nonRushCheckedOut,
      rushExcluded,
      nonRushExcluded,
      sentCount: checkedRows.length,
    };
  }, [searchFilteredRows, checkedRows.length, batchSummary]);

  /** Narrows scan lookup to the dominant batch in the current queue (faster, fewer collisions). */
  const lookupBatchDate = useMemo(() => {
    const dates = rows
      .map((r) => String(r?.batch_date || "").trim().slice(0, 10))
      .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d));
    if (!dates.length) return "";
    const counts = {};
    dates.forEach((d) => {
      counts[d] = (counts[d] || 0) + 1;
    });
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const [best, n] = sorted[0] || ["", 0];
    if (!best || n < dates.length * 0.5) return "";
    return best;
  }, [rows]);

  const handleAlphaToggle = (alpha) => {
    setOpenAlpha((prev) => (prev === alpha ? null : alpha));
  };

  const confirmCheckout = async () => {
    if (!activeRow) return;
    const gate = await assertCanCheckout();
    if (!gate.ok) {
      const detail = gate.reasons?.length ? gate.reasons.join(", ") : "Time & attendance rules not met.";
      window.alert(`Checkout blocked: ${detail}`);
      return;
    }
    try {
      setBusy(true);
      await checkoutOrder(activeRow.id, "FrontDesk");
      setActiveRow(null);
      await load();
    } catch (error) {
      console.error(error);
    } finally {
      setBusy(false);
    }
  };

  const onSelectForCheckout = (row) => {
    const key = normalizeName(row?.name_clean);
    const sameName = searchFilteredRows.filter((r) => normalizeName(r?.name_clean) === key);
    if (sameName.length > 1) {
      setNameConfirmDialog({
        name_clean: row?.name_clean,
        options: sameName.sort((a, b) => Number(a?.id || 0) - Number(b?.id || 0)),
      });
      setNameConfirmSelectedId(row?.id);
      return;
    }
    setActiveRow(row);
  };

  const renderCheckoutQueueCard = (r) => {
    const hd = isHD(r);
    const rt = rushOf(r);
    return (
      <Paper
        key={r.id}
        onClick={() => !checkoutBlocked && onSelectForCheckout(r)}
        sx={{
          p: 1.1,
          borderRadius: 2,
          cursor: checkoutBlocked ? "not-allowed" : "pointer",
          opacity: checkoutBlocked ? 0.45 : 1,
          bgcolor: hd ? "#0097b2" : "#0b1324",
          border: hd ? "1px solid #52d4e4" : "1px solid #1f2d4a",
          color: "#ffffff",
        }}
      >
        <Stack spacing={0.6}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography sx={{ fontSize: 21, fontWeight: 500 }}>{displayCustomerName(r.name_clean)}</Typography>
            <ChevronRight sx={{ color: "#fff" }} />
          </Stack>
          {r.ticket_id ? (
            <Typography sx={{ fontSize: 14, opacity: 0.92, fontWeight: 600 }}>
              {t("ops.bagIdShort")} {String(r.ticket_id)}
            </Typography>
          ) : null}
          <Typography sx={{ opacity: 0.95 }}>
            {formatDate(r.date_clean)} • {measureOf(r)}
          </Typography>
          <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap>
            <Stack
              direction="row"
              alignItems="center"
              spacing={0.5}
              sx={{
                px: 1.1,
                py: 0.35,
                borderRadius: 999,
                bgcolor: "#ffffff",
                color: "#111827",
              }}
            >
              <Typography component="span" sx={{ fontSize: 12, fontWeight: 700 }}>
                {serviceOf(r) || "—"}
              </Typography>
            </Stack>
            <Stack
              direction="row"
              alignItems="center"
              spacing={0.5}
              sx={{
                px: 1.1,
                py: 0.35,
                borderRadius: 999,
                bgcolor: "#ffffff",
                color: "#111827",
              }}
            >
              {rt === "RUSH" ? (
                <Bolt sx={{ fontSize: 15, color: "#111827" }} />
              ) : (
                <CheckCircle sx={{ fontSize: 14, color: "#111827" }} />
              )}
              <Typography component="span" sx={{ fontSize: 12, fontWeight: 700 }}>
                {rt === "RUSH" ? "RUSH" : "NON-RUSH"}
              </Typography>
            </Stack>
          </Stack>
        </Stack>
      </Paper>
    );
  };

  const confirmUndo = async () => {
    if (!undoRow) return;
    try {
      setBusy(true);
      await undoCheckout(undoRow.order_id);
      setUndoRow(null);
      await load();
    } catch (error) {
      console.error(error);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
        <CircularProgress size={26} />
        <Typography color="text.secondary">Loading...</Typography>
      </Stack>
    );
  }

  const checkoutPageBg =
    "linear-gradient(168deg, #e3f0ff 0%, #dbeafe 32%, #eff6ff 62%, #f8fafc 100%)";
  const sentOverlayBg =
    "linear-gradient(168deg, #fff4e6 0%, #ffedd5 28%, #fff7ed 58%, #fffefb 100%)";

  return (
    <Box
      sx={{
        minHeight: "100vh",
        px: { xs: 1, sm: 1.5 },
        py: 1,
        background: checkoutPageBg,
      }}
    >
      {!sentDrawerOpen && (
        <>
          <TaOperationalBanner message={bannerMessage} />
          <StandardScreenHeader
            title={isMobile ? undefined : t("nav.checkout")}
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
                <Tooltip title={t("ops.checkoutSentOpen")}>
                  <IconButton
                    size="large"
                    onClick={() => setSentDrawerOpen(true)}
                    aria-pressed={sentDrawerOpen}
                    sx={{
                      bgcolor: "rgba(254, 243, 199, 0.95)",
                      color: "#b45309",
                      width: 48,
                      height: 48,
                      "&:hover": { bgcolor: "rgba(253, 230, 138, 0.98)" },
                    }}
                  >
                    <Send />
                  </IconButton>
                </Tooltip>
                <Tooltip
                  title={
                    !masterScan
                      ? "Scan lookup is turned off in Maintenance for this business."
                      : scanEnabled
                        ? t("ops.scanToggleOnHint")
                        : t("ops.scanToggleOffHint")
                  }
                >
                  <IconButton
                    size="large"
                    onClick={() => setScanEnabled((v) => !v)}
                    aria-pressed={effectiveScanEnabled}
                    disabled={scanDisabled || !masterScan}
                    sx={{
                      bgcolor: effectiveScanEnabled ? "rgba(219, 234, 254, 0.98)" : "rgba(226, 232, 240, 0.95)",
                      color: effectiveScanEnabled ? "primary.main" : "#64748b",
                      width: 48,
                      height: 48,
                      border: effectiveScanEnabled ? "2px solid" : "none",
                      borderColor: "primary.main",
                      "&:hover": { bgcolor: effectiveScanEnabled ? "rgba(191, 219, 254, 0.98)" : "rgba(203, 213, 225, 0.95)" },
                    }}
                  >
                    <QrCodeScanner />
                  </IconButton>
                </Tooltip>
                <Tooltip
                  title={
                    !masterBrowse
                      ? "Browse list is turned off in Maintenance for this business."
                      : showBrowse
                        ? t("ops.indexToggleOnHint")
                        : t("ops.indexToggleOffHint")
                  }
                >
                  <IconButton
                    size="large"
                    onClick={() => setShowBrowse((v) => !v)}
                    aria-pressed={effectiveShowBrowse}
                    disabled={!masterBrowse}
                    sx={{
                      bgcolor: effectiveShowBrowse ? "rgba(219, 234, 254, 0.98)" : "rgba(226, 232, 240, 0.95)",
                      color: effectiveShowBrowse ? "primary.main" : "#64748b",
                      width: 48,
                      height: 48,
                      border: effectiveShowBrowse ? "2px solid" : "none",
                      borderColor: "primary.main",
                      "&:hover": { bgcolor: effectiveShowBrowse ? "rgba(191, 219, 254, 0.98)" : "rgba(203, 213, 225, 0.95)" },
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
            scanEnabled={effectiveScanEnabled}
            onScanEnabledChange={(v) => {
              if (masterScan) setScanEnabled(v);
            }}
            storageKey="washpro_scan_lookup_checkout"
            batchDate={lookupBatchDate}
            disabled={scanDisabled || !masterScan}
            onPickOrder={(o) => onSelectForCheckout(o)}
          />

          <RushTabCountBar
            variant="cards"
            fullWidth
            value={rushTab}
            onChange={(k) => {
              setRushTab(k);
              setOpenAlpha(null);
            }}
            tabs={[
              { key: "ALL", label: "All", count: counters.allCount, Icon: GridView, accent: "#4338ca" },
              {
                key: "RUSH",
                label: "Rush",
                count: counters.rushInQueue,
                detail: batchSummary?.rush?.total != null
                  ? `${counters.rushTotal} uploaded · ${counters.rushCheckedOut} sent · ${counters.rushExcluded} excluded`
                  : undefined,
                Icon: Bolt,
                accent: "#b91c1c",
              },
              {
                key: "NON-RUSH",
                label: "Non-Rush",
                count: counters.nonRushInQueue,
                detail: batchSummary?.non_rush?.total != null
                  ? `${counters.nonRushTotal} uploaded · ${counters.nonRushCheckedOut} sent · ${counters.nonRushExcluded} excluded`
                  : undefined,
                Icon: CheckCircle,
                accent: "#0f766e",
              },
            ]}
          />

          {effectiveShowBrowse && (
            <OpsSearchBar value={search} onChange={setSearch} placeholder={t("ops.searchNameHint")} />
          )}

          {effectiveShowBrowse && (
            <OpsAlphaJumpRail
              letters={groupedQueue.keys}
              ariaLabelFor={(letter) => t("ops.jumpLetter").replace("{l}", letter)}
              onPick={(letter) => {
                setOpenAlpha(letter);
                requestAnimationFrame(() => {
                  alphaQueueRefs.current[letter]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                });
              }}
            />
          )}

        </>
      )}

      {!sentDrawerOpen && effectiveShowBrowse && (
      <Box sx={{ mt: 1.2 }}>
        {groupedQueue.keys.map((alpha) => {
          const list = groupedQueue.groups[alpha] || [];
          const expanded = openAlpha === alpha;
          const pal = getOpsAlphaPaletteForLetter(alpha);
          return (
            <Paper
              key={alpha}
              ref={(el) => {
                alphaQueueRefs.current[alpha] = el;
              }}
              sx={{
                mb: 1.1,
                borderRadius: 2,
                overflow: "hidden",
                border: `1px solid ${pal.border}`,
                boxShadow: "none",
                bgcolor: "#ffffff",
                transition: "border-color 0.15s ease, background-color 0.15s ease",
                ...opsAlphaEmptySectionSx(list.length),
              }}
            >
              <Button
                fullWidth
                onClick={() => handleAlphaToggle(alpha)}
                sx={{
                  px: 1.25,
                  py: 1.35,
                  minHeight: 56,
                  justifyContent: "space-between",
                  color: "#0f172a",
                  textTransform: "none",
                  bgcolor: pal.rowBg,
                }}
              >
                <Stack direction="row" spacing={1.4} alignItems="center">
                  <Box
                    sx={{
                      width: 42,
                      height: 42,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      bgcolor: pal.chipBg,
                      color: pal.chipColor,
                      fontWeight: 700,
                      fontSize: 18,
                      letterSpacing: 0.02,
                      boxShadow: list.length === 0 ? "none" : "0 2px 8px rgba(15,23,42,0.12)",
                    }}
                  >
                    {alpha}
                  </Box>
                  <Typography sx={{ fontSize: 17, fontWeight: 600, letterSpacing: 0.02 }}>
                    {t("ops.nBags").replace("{n}", String(list.length))}
                  </Typography>
                </Stack>
                {expanded ? <ExpandLess sx={{ fontSize: 26, color: "#334155" }} /> : <ExpandMore sx={{ fontSize: 26, color: "#334155" }} />}
              </Button>
              {expanded && (
                <Box sx={{ p: 1, bgcolor: "transparent" }}>
                  {list.length === 0 ? (
                    <Typography sx={{ color: "#64748b", fontSize: 13, px: 0.25, py: 0.5 }}>{t("ops.emptyBagsLetter")}</Typography>
                  ) : (
                    <Stack spacing={0.9}>{list.map((r) => renderCheckoutQueueCard(r))}</Stack>
                  )}
                </Box>
              )}
            </Paper>
          );
        })}
      </Box>
      )}

      {!sentDrawerOpen && !effectiveShowBrowse && (
        <Box sx={{ mt: 1.2 }}>
          {sequentialCheckoutRows.length === 0 ? (
            <Typography sx={{ color: "#64748b", fontSize: 13, px: 0.25 }}>{t("ops.emptyBagsLetter")}</Typography>
          ) : (
            <Stack spacing={0.9}>{sequentialCheckoutRows.map((r) => renderCheckoutQueueCard(r))}</Stack>
          )}
        </Box>
      )}

      {sentDrawerOpen && (
        <Box
          role="dialog"
          aria-modal="true"
          aria-label={t("ops.sentTitle")}
          sx={{
            position: "fixed",
            inset: 0,
            zIndex: 1400,
            display: "flex",
            flexDirection: "column",
            background: sentOverlayBg,
            pb: "env(safe-area-inset-bottom, 0px)",
            px: { xs: 1, sm: 1.5 },
            pt: 1,
          }}
        >
          <StandardScreenHeader
            title={t("ops.sentTitle")}
            dense
            onBack={() => setSentDrawerOpen(false)}
            homePath="/checkout"
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
          <Box sx={{ flex: 1, overflow: "auto", pt: 0.5 }}>
            {checkedRows.length === 0 ? (
              <Typography sx={{ color: "#64748b", fontSize: 13, px: 0.5 }}>{t("ops.noSentRecent")}</Typography>
            ) : (
              <Stack spacing={0.75} sx={{ pt: 0.5 }}>
                {sentSequential.map((r) => (
                  <Paper
                    key={`${r.id}-${r.order_id}`}
                    variant="outlined"
                    sx={{
                      p: 1,
                      borderRadius: 2,
                      borderColor: "rgba(148, 163, 184, 0.5)",
                      bgcolor: "rgba(255,255,255,0.88)",
                    }}
                  >
                    <Stack spacing={1}>
                      <Stack spacing={0.35} sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 700, fontSize: "1.05rem" }}>
                          {displayCustomerName(r.name || "") || `#${r.order_id}`}
                        </Typography>
                        {r.ticket_id ? (
                          <Typography sx={{ fontSize: 12.5, fontWeight: 600, color: "text.primary" }}>
                            {t("ops.bagIdShort")} {String(r.ticket_id)}
                          </Typography>
                        ) : null}
                        <Typography sx={{ fontSize: 12.5, color: "text.secondary", lineHeight: 1.4 }}>
                          #{r.order_id} • {formatDate(r.rush_date || r.checkout_time)} • {logMeasureOf(r)}
                        </Typography>
                      </Stack>
                      <Button
                        fullWidth
                        variant="outlined"
                        color="warning"
                        size="medium"
                        startIcon={<Undo sx={{ fontSize: 22 }} />}
                        onClick={() => setUndoRow(r)}
                        sx={{
                          py: 1.1,
                          fontWeight: 700,
                          borderRadius: 2,
                          textTransform: "none",
                          fontSize: "0.95rem",
                        }}
                      >
                        {t("ops.undoSend")}
                      </Button>
                    </Stack>
                  </Paper>
                ))}
              </Stack>
            )}
          </Box>
        </Box>
      )}

      <Dialog open={Boolean(activeRow)} onClose={() => setActiveRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Send to Rinse</DialogTitle>
        <DialogContent dividers>
          {activeRow && (
            <Stack spacing={1}>
              <Typography sx={{ fontSize: 21 }}>{displayCustomerName(activeRow.name_clean)}</Typography>
              {activeRow.ticket_id ? (
                <Typography sx={{ fontSize: 15, fontWeight: 600 }}>
                  {t("ops.bagIdShort")} {String(activeRow.ticket_id)}
                </Typography>
              ) : null}
              <Typography>
                {formatDate(activeRow.date_clean)} • {measureOf(activeRow)}
              </Typography>
              <Alert severity="warning">Confirm physical tag before sending.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ flexDirection: "column", gap: 1.5, px: 2, pb: 2, pt: 0 }}>
          <Button fullWidth onClick={() => setActiveRow(null)} sx={{ borderRadius: 999, py: 1.2 }}>
            Cancel
          </Button>
          <Button
            fullWidth
            variant="contained"
            disabled={checkoutBlocked || busy}
            startIcon={<LocalShipping />}
            onClick={confirmCheckout}
            sx={{
              borderRadius: 999,
              py: 2,
              fontSize: "1.05rem",
              fontWeight: 800,
              boxShadow: "0 8px 24px rgba(15,118,110,0.35)",
            }}
          >
            Confirm Send
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(nameConfirmDialog)} onClose={() => setNameConfirmDialog(null)} fullWidth maxWidth="xs">
        <DialogTitle>Confirm Customer Order</DialogTitle>
        <DialogContent dividers>
          {nameConfirmDialog && (
            <Stack spacing={1}>
              <Alert severity="warning">
                Multiple active orders found for {displayCustomerName(nameConfirmDialog.name_clean)}. Verify ticket
                weight/count and date.
              </Alert>
              <Stack spacing={0.8}>
                {nameConfirmDialog.options.map((opt) => (
                  <Button
                    key={opt.id}
                    variant={nameConfirmSelectedId === opt.id ? "contained" : "outlined"}
                    onClick={() => setNameConfirmSelectedId(opt.id)}
                    sx={{ textTransform: "none", justifyContent: "flex-start" }}
                  >
                    <span>
                      {opt.ticket_id ? `${t("ops.bagIdShort")} ${opt.ticket_id} · ` : ""}
                      {formatDate(opt.date_clean)} • {measureOf(opt)}
                    </span>
                  </Button>
                ))}
              </Stack>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNameConfirmDialog(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              const chosen = nameConfirmDialog?.options?.find((o) => o.id === nameConfirmSelectedId);
              if (!chosen) return;
              setNameConfirmDialog(null);
              setActiveRow(chosen);
            }}
          >
            Continue
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(undoRow)} onClose={() => setUndoRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Undo Checkout</DialogTitle>
        <DialogContent dividers>
          {undoRow && (
            <Stack spacing={1}>
              <Typography sx={{ fontSize: 19 }}>
                {displayCustomerName(undoRow.name || "") || `Order #${undoRow.order_id}`}
              </Typography>
              {undoRow.ticket_id ? (
                <Typography sx={{ fontWeight: 600 }}>
                  {t("ops.bagIdShort")} {String(undoRow.ticket_id)}
                </Typography>
              ) : null}
              <Typography>Move this bag back to the operations queue.</Typography>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUndoRow(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={confirmUndo} startIcon={<Undo />}>
            Confirm Undo
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default CheckoutPage;
