import { useEffect, useMemo, useState, useDeferredValue } from "react";
import { Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Typography } from "@mui/material";
import { Bolt, CheckCircle, ExpandLess, ExpandMore, Inventory2, Refresh } from "@mui/icons-material";
import { useNavigate } from "react-router-dom";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import OpsSearchBar from "../components/layout/OpsSearchBar";
import RushTabCountBar from "../components/layout/RushTabCountBar";
import IconPillButton from "../components/layout/IconPillButton";
import OrderScanLookupBar from "../components/OrderScanLookupBar";
import { formatSystemDateLong } from "../utils/formatDateLocal";
import { getCurrentUploadBatch, getOrders } from "../api";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const WF_BG = "#141922";
const HD_BG = "#0a869d";

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
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const [rushFilter, setRushFilter] = useState("ALL"); // ALL | RUSH | NON-RUSH
  const [showProcessed, setShowProcessed] = useState(false);
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
      const id = String(r?.id || "").toLowerCase();
      const service = String(r?.service_type || "").toLowerCase();
      const weight = String(r?.weight_num ?? "").toLowerCase();
      return (
        name.startsWith(q) ||
        id.startsWith(q) ||
        service.startsWith(q) ||
        weight.startsWith(q)
      );
    });
  }, [rows, deferredSearch, rushFilter, showProcessed, userId]);

  const grouped = useMemo(() => {
    const out = {};
    for (const a of ALPHAS) out[a] = [];
    for (const r of visibleRows) {
      const c = String(r?.name_clean || "").trim().charAt(0).toUpperCase();
      const k = /^[A-Z]$/.test(c) ? c : "A";
      out[k].push(r);
    }
    return out;
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
    const c = String(first?.name_clean || "").trim().charAt(0).toUpperCase();
    const alpha = /^[A-Z]$/.test(c) ? c : "A";
    setOpenAlpha(alpha);
  }, [deferredSearch, visibleRows]);

  const activeBatchDate = batchInfo?.batch_date || rows[0]?.batch_date || null;
  const batchDateScan = activeBatchDate ? String(activeBatchDate).slice(0, 10) : "";
  const batchLabelShort = (() => {
    if (!batchDateScan) return "";
    const d = parseAsLocalDate(batchDateScan);
    if (!d) return "";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  })();
  const headerDateLine = batchLabelShort
    ? `${formatSystemDateLong()} · Batch ${batchLabelShort}`
    : formatSystemDateLong();
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

  return (
    <Box
      sx={{
        minHeight: "100vh",
        px: { xs: 1, sm: 1.5 },
        py: 1,
        background: "linear-gradient(185deg, #e8edf7 0%, #f1f5f9 18%, #fafbfc 55%, #ffffff 100%)",
      }}
    >
      <StandardScreenHeader
        title="Rinse orders"
        dateLabel={headerDateLine}
        dense
        right={
          <>
            <IconPillButton
              title={showProcessed ? "Showing orders you folded" : "Show orders you folded"}
              icon={<Inventory2 />}
              label={showProcessed ? "Folded" : "Folded"}
              variant={showProcessed ? "contained" : "outlined"}
              onClick={() => setShowProcessed((p) => !p)}
            />
            <IconPillButton title="Refresh" icon={<Refresh />} label="" onClick={load} />
          </>
        }
      />

      <RushTabCountBar
        value={rushFilter}
        onChange={setRushFilter}
        tabs={[
          { key: "ALL", label: "All", count: counts.all },
          { key: "RUSH", label: "Rush", count: counts.rush, Icon: Bolt, accent: "#b91c1c" },
          { key: "NON-RUSH", label: "Non-Rush", count: counts.nonRush, Icon: CheckCircle, accent: "#0f766e" },
        ]}
      />

      <OrderScanLookupBar
        storageKey="washpro_scan_lookup_orders"
        batchDate={batchDateScan}
        onPickOrder={onScanPickOrder}
      />

      <OpsSearchBar value={search} onChange={setSearch} />

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
          <CircularProgress size={26} />
          <Typography color="text.secondary">Loading...</Typography>
        </Stack>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {ALPHAS.map((alpha) => {
            const list = grouped[alpha] || [];
            if (searchActive && list.length === 0) return null;
            const expanded = searchActive ? true : openAlpha === alpha;
            return (
              <Paper
                key={alpha}
                sx={{
                  borderRadius: 2,
                  border: "1px solid #e5e7eb",
                  overflow: "hidden",
                  opacity: list.length === 0 ? 0.36 : 1,
                }}
              >
                <Button
                  fullWidth
                  onClick={() => toggleAlpha(alpha)}
                  sx={{
                    px: 1.1,
                    py: 1,
                    justifyContent: "space-between",
                    textTransform: "none",
                    color: "#111827",
                    bgcolor: "#f8fafc",
                  }}
                >
                  <Stack direction="row" spacing={1.2} alignItems="center">
                    <Box
                      sx={{
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        display: "grid",
                        placeItems: "center",
                        bgcolor: "#111827",
                        color: "#ffffff",
                        fontSize: 14,
                        fontWeight: 400,
                      }}
                    >
                      {alpha}
                    </Box>
                    <Typography sx={{ fontSize: 16, fontWeight: 400 }}>{list.length} bags</Typography>
                  </Stack>
                  {expanded ? <ExpandLess /> : <ExpandMore />}
                </Button>

                {expanded && (
                  <Box sx={{ p: 1 }}>
                    {list.length === 0 ? (
                      <Typography sx={{ color: "#6b7280", fontSize: 14 }}>No orders.</Typography>
                    ) : (
                      <Stack spacing={1}>
                        {list.map((r) => {
                          const rush = rushOf(r) === "RUSH";
                          const hd = isHD(r);
                          const pending = normalizeProcessing(r) === "PENDING";
                          const gameSt = String(r.gaming_flow_status || "").toUpperCase();
                          const lockUid = Number(r.gaming_locked_by_user_id || 0);
                          const lockedOther = gameSt === "ACTIVE" && lockUid && lockUid !== userId;
                          const lockedMe = gameSt === "ACTIVE" && lockUid === userId;
                          const gameDone = gameSt === "COMPLETED";
                          const cardCursor =
                            showProcessed || !pending || gameDone || lockedOther ? "default" : "pointer";
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

                                  <Typography sx={{ fontSize: 38 > String(r?.name_clean || "").length ? 20 : 18, lineHeight: 1.15, fontWeight: 400 }}>
                                    {r.name_clean}
                                  </Typography>

                                  <Typography sx={{ fontSize: 16, opacity: 0.92, fontWeight: 400 }}>
                                    {formatDate(r.date_clean)} • {formatMeasure(r)}
                                  </Typography>
                                </Stack>
                              </Box>
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
