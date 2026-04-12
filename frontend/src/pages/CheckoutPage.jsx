import { useCallback, useEffect, useMemo, useState, useDeferredValue } from "react";
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
  Drawer,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import {
  Bolt,
  CheckCircle,
  ChevronRight,
  ExpandLess,
  ExpandMore,
  LocalShipping,
  Refresh,
  Undo,
} from "@mui/icons-material";
import { checkoutOrder, getCheckoutLog, getOrders, undoCheckout } from "../api";
import TaOperationalBanner from "../components/TaOperationalBanner";
import { useTaOperationalGate } from "../hooks/useTaOperationalGate";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import OpsSearchBar from "../components/layout/OpsSearchBar";
import RushTabCountBar from "../components/layout/RushTabCountBar";
import IconPillButton from "../components/layout/IconPillButton";
import OrderScanLookupBar from "../components/OrderScanLookupBar";
import { formatSystemDateLong } from "../utils/formatDateLocal";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const HEADER_BG = ["#f8fafc", "#fefce8", "#f0f9ff", "#fdf2f8", "#f0fdfa"];

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
  const { checkoutBlocked, assertCanCheckout, bannerMessage } = useTaOperationalGate();
  const scanDisabled = checkoutBlocked;

  const [rows, setRows] = useState([]);
  const [checkedRows, setCheckedRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [rushTab, setRushTab] = useState("ALL");
  const [openAlpha, setOpenAlpha] = useState(null);
  const [openAlphaSent, setOpenAlphaSent] = useState(null);
  const [sentDrawerOpen, setSentDrawerOpen] = useState(false);
  const [activeRow, setActiveRow] = useState(null);
  const [nameConfirmDialog, setNameConfirmDialog] = useState(null);
  const [nameConfirmSelectedId, setNameConfirmSelectedId] = useState(null);
  const [undoRow, setUndoRow] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [ordersRes, checkedRes] = await Promise.allSettled([
        getOrders({ include_all: true }),
        getCheckoutLog(),
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
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
  const nameOf = (r) => String(r?.name_clean || r?.name || "").trim();
  const nameOfLog = (r) => String(r?.name || r?.name_clean || "").trim();

  const alphaOf = useCallback((row) => {
    const ch = nameOf(row).charAt(0).toUpperCase();
    return /^[A-Z]$/.test(ch) ? ch : "#";
  }, []);

  const alphaOfLog = useCallback((row) => {
    const ch = nameOfLog(row).charAt(0).toUpperCase();
    return /^[A-Z]$/.test(ch) ? ch : "#";
  }, []);

  const searchFilteredRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      const name = String(r?.name_clean || "").toLowerCase();
      const id = String(r?.id || "").toLowerCase();
      const svc = String(r?.service_type || "").toLowerCase();
      const w = String(r?.weight_num ?? r?.weight ?? "").toLowerCase();
      return name.includes(q) || id.startsWith(q) || svc.includes(q) || w.includes(q);
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

  const groupedSent = useMemo(() => {
    const groups = {};
    checkedRows.forEach((row) => {
      const alpha = alphaOfLog(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });
    ALPHAS.forEach((k) => {
      if (!groups[k]) groups[k] = [];
      groups[k].sort((a, b) => nameOfLog(a).localeCompare(nameOfLog(b)));
    });
    if (groups["#"]?.length) {
      groups["#"].sort((a, b) => nameOfLog(a).localeCompare(nameOfLog(b)));
      return { keys: [...ALPHAS, "#"], groups };
    }
    return { keys: ALPHAS, groups };
  }, [checkedRows, alphaOfLog]);

  const counters = useMemo(() => {
    const rushCount = searchFilteredRows.filter((r) => rushOf(r) === "RUSH").length;
    const nonRushCount = searchFilteredRows.filter((r) => rushOf(r) === "NON-RUSH").length;
    return {
      allCount: searchFilteredRows.length,
      rushCount,
      nonRushCount,
      sentCount: checkedRows.length,
    };
  }, [searchFilteredRows, checkedRows.length]);

  const handleAlphaToggle = (alpha) => {
    setOpenAlpha((prev) => (prev === alpha ? null : alpha));
  };

  const handleAlphaSentToggle = (alpha) => {
    setOpenAlphaSent((prev) => (prev === alpha ? null : alpha));
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

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <TaOperationalBanner message={bannerMessage} />
      <StandardScreenHeader
        title="Checkout"
        dateLabel={formatSystemDateLong()}
        right={
          <>
            <IconPillButton
              title="Sent to rinse"
              icon={<Undo />}
              label={counters.sentCount ? `Sent (${counters.sentCount})` : "Sent"}
              onClick={() => setSentDrawerOpen(true)}
            />
            <IconPillButton title="Refresh queue" icon={<Refresh />} label="" onClick={load} />
          </>
        }
      />

      <RushTabCountBar
        fullWidth
        value={rushTab}
        onChange={(k) => {
          setRushTab(k);
          setOpenAlpha(null);
        }}
        tabs={[
          { key: "ALL", label: "All", count: counters.allCount },
          { key: "RUSH", label: "Rush", count: counters.rushCount, Icon: Bolt, accent: "#b91c1c" },
          { key: "NON-RUSH", label: "Non-Rush", count: counters.nonRushCount, Icon: CheckCircle, accent: "#0f766e" },
        ]}
      />

      <OpsSearchBar value={search} onChange={setSearch} />

      <OrderScanLookupBar
        storageKey="washpro_scan_lookup_checkout"
        disabled={scanDisabled}
        onPickOrder={(o) => onSelectForCheckout(o)}
      />

      <Box sx={{ mt: 1.2 }}>
        {groupedQueue.keys.map((alpha, idx) => {
          const list = groupedQueue.groups[alpha] || [];
          const expanded = openAlpha === alpha;
          return (
            <Paper
              key={alpha}
              sx={{
                mb: 1.1,
                borderRadius: 2,
                overflow: "hidden",
                border: "1px solid #e5e7eb",
                boxShadow: "none",
                bgcolor: "#ffffff",
              }}
            >
              <Button
                fullWidth
                onClick={() => handleAlphaToggle(alpha)}
                sx={{
                  px: 1.1,
                  py: 1.1,
                  justifyContent: "space-between",
                  color: "#111827",
                  textTransform: "none",
                  bgcolor: HEADER_BG[idx % HEADER_BG.length],
                }}
              >
                <Stack direction="row" spacing={1.3} alignItems="center">
                  <Box
                    sx={{
                      width: 31,
                      height: 31,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      bgcolor: "#111827",
                      color: "#fff",
                      fontWeight: 500,
                      fontSize: 14,
                    }}
                  >
                    {alpha}
                  </Box>
                  <Typography sx={{ fontSize: 16, fontWeight: 500, letterSpacing: 0.2 }}>{list.length} bags</Typography>
                </Stack>
                {expanded ? <ExpandLess /> : <ExpandMore />}
              </Button>
              {expanded && (
                <Box sx={{ p: 1, bgcolor: "transparent" }}>
                  {list.length === 0 ? (
                    <Typography sx={{ color: "#6b7280", fontSize: 14, px: 0.25, py: 0.5 }}>No bags in this section.</Typography>
                  ) : (
                    <Stack spacing={0.9}>
                      {list.map((r) => {
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
                                <Typography sx={{ fontSize: 21, fontWeight: 500 }}>{r.name_clean}</Typography>
                                <ChevronRight sx={{ color: "#fff" }} />
                              </Stack>
                              <Typography sx={{ opacity: 0.95 }}>
                                {formatDate(r.date_clean)} • {measureOf(r)}
                              </Typography>
                              <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap>
                                <Chip size="small" label={serviceOf(r) || "—"} sx={{ bgcolor: "#ffffff", color: "#111827" }} />
                                <Chip
                                  size="small"
                                  label={rt === "RUSH" ? "RUSH" : "NON-RUSH"}
                                  icon={rt === "RUSH" ? <Bolt sx={{ fontSize: 15 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                                  sx={{ bgcolor: "#ffffff", color: "#111827" }}
                                />
                              </Stack>
                            </Stack>
                          </Paper>
                        );
                      })}
                    </Stack>
                  )}
                </Box>
              )}
            </Paper>
          );
        })}
      </Box>

      <Drawer anchor="right" open={sentDrawerOpen} onClose={() => setSentDrawerOpen(false)} PaperProps={{ sx: { width: { xs: "100%", sm: 380 } } }}>
        <Box sx={{ p: 1.5, borderBottom: "1px solid #e5e7eb" }}>
          <Typography sx={{ fontSize: 18, fontWeight: 600 }}>Sent to rinse</Typography>
          <Typography sx={{ fontSize: 13, color: "text.secondary", mt: 0.5 }}>
            Tap a bag to undo and move it back to the queue.
          </Typography>
        </Box>
        <Box sx={{ p: 1, overflow: "auto", pb: "env(safe-area-inset-bottom, 16px)" }}>
          {checkedRows.length === 0 ? (
            <Typography sx={{ color: "#6b7280", px: 1 }}>No recent sends yet.</Typography>
          ) : (
            groupedSent.keys.map((alpha, idx) => {
              const list = groupedSent.groups[alpha] || [];
              const expanded = openAlphaSent === alpha;
              return (
                <Paper
                  key={`sent-${alpha}`}
                  sx={{
                    mb: 1,
                    borderRadius: 2,
                    overflow: "hidden",
                    border: "1px solid #e5e7eb",
                    boxShadow: "none",
                  }}
                >
                  <Button
                    fullWidth
                    onClick={() => handleAlphaSentToggle(alpha)}
                    sx={{
                      px: 1,
                      py: 1,
                      justifyContent: "space-between",
                      color: "#111827",
                      textTransform: "none",
                      bgcolor: HEADER_BG[idx % HEADER_BG.length],
                    }}
                  >
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Box
                        sx={{
                          width: 28,
                          height: 28,
                          borderRadius: "50%",
                          display: "grid",
                          placeItems: "center",
                          bgcolor: "#0f766e",
                          color: "#fff",
                          fontWeight: 600,
                          fontSize: 13,
                        }}
                      >
                        {alpha}
                      </Box>
                      <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{list.length} sent</Typography>
                    </Stack>
                    {expanded ? <ExpandLess /> : <ExpandMore />}
                  </Button>
                  {expanded && list.length > 0 && (
                    <Stack spacing={0.8} sx={{ p: 1 }}>
                      {list.map((r) => (
                        <Paper
                          key={`${r.id}-${r.order_id}`}
                          variant="outlined"
                          sx={{ p: 1, borderRadius: 1.5 }}
                        >
                          <Stack spacing={0.8}>
                            <Typography sx={{ fontWeight: 600 }}>{r.name || `#${r.order_id}`}</Typography>
                            <Typography sx={{ fontSize: 13, color: "text.secondary" }}>
                              #{r.order_id} • {formatDate(r.rush_date || r.checkout_time)} • {logMeasureOf(r)}
                            </Typography>
                            <Stack direction="row" justifyContent="flex-end">
                              <Button size="small" variant="contained" color="warning" startIcon={<Undo />} onClick={() => setUndoRow(r)}>
                                Undo
                              </Button>
                            </Stack>
                          </Stack>
                        </Paper>
                      ))}
                    </Stack>
                  )}
                </Paper>
              );
            })
          )}
        </Box>
      </Drawer>

      <Dialog open={Boolean(activeRow)} onClose={() => setActiveRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Send to Rinse</DialogTitle>
        <DialogContent dividers>
          {activeRow && (
            <Stack spacing={1}>
              <Typography sx={{ fontSize: 21 }}>{activeRow.name_clean}</Typography>
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
                Multiple active orders found for {nameConfirmDialog.name_clean}. Verify ticket weight/count and date.
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
              <Typography sx={{ fontSize: 19 }}>{undoRow.name || `Order #${undoRow.order_id}`}</Typography>
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
