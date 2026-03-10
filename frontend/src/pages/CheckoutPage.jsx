import { useCallback, useEffect, useMemo, useState } from "react";
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
  Paper,
  Snackbar,
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

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const HEADER_BG = ["#f8fafc", "#fefce8", "#f0f9ff", "#fdf2f8", "#f0fdfa"];

function CheckoutPage() {
  const [orders, setOrders] = useState([]);
  const [checkedLogs, setCheckedLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [viewMode, setViewMode] = useState("REMAINING"); // REMAINING | SENT_TO_RINSE

  const [openAlpha, setOpenAlpha] = useState(null);
  const [activeOrder, setActiveOrder] = useState(null);
  const [activeChecked, setActiveChecked] = useState(null);

  const [snack, setSnack] = useState({
    open: false,
    severity: "success",
    message: "",
  });

  const showSnack = useCallback((severity, message) => {
    setSnack({ open: true, severity, message });
  }, []);

  const nameOf = (row) => String(row?.name_clean || row?.name || "").trim();

  const alphaOf = useCallback((row) => {
    const ch = nameOf(row).charAt(0).toUpperCase();
    return /^[A-Z]$/.test(ch) ? ch : "#";
  }, []);

  const formatDate = (value) => {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value).split(" ")[0];
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const measureOf = (row) => {
    const service = String(row?.service_type || row?.service || "").toUpperCase();
    const raw = Number(row?.weight_num ?? row?.weight ?? 0);

    if (service === "WF") return `${raw.toFixed(2)} lb`;
    if (service === "HD") return `${Math.round(raw)} pcs`;
    return "-";
  };

  const serviceOf = (row) => String(row?.service_type || row?.service || "").toUpperCase();

  const rushOf = (row) => {
    if (row?.rush_type) return String(row.rush_type).toUpperCase();

    if (row?.rush_date) {
      const due = new Date(row.rush_date);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return due < today ? "RUSH" : "NON_RUSH";
    }

    return "NON_RUSH";
  };

  const loadAll = useCallback(async () => {
    try {
      setLoading(true);
      const [ordersRes, checkedRes] = await Promise.all([getOrders(), getCheckoutLog()]);

      const activeRows = (Array.isArray(ordersRes.data) ? ordersRes.data : []).filter(
        (row) => String(row?.status || "").toUpperCase() !== "CHECKED_OUT"
      );

      const checkedRows = Array.isArray(checkedRes.data) ? checkedRes.data : [];

      setOrders(activeRows);
      setCheckedLogs(checkedRows);
    } catch (error) {
      console.error(error);
      showSnack("error", "Failed to load checkout data.");
    } finally {
      setLoading(false);
    }
  }, [showSnack]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const filteredActive = useMemo(
    () => orders,
    [orders]
  );

  const filteredChecked = useMemo(
    () => checkedLogs,
    [checkedLogs]
  );

  const remainingCount = filteredActive.length;
  const sentCount = filteredChecked.length;
  const remainingRushCount = useMemo(
    () => ({
      rush: filteredActive.filter((row) => rushOf(row) === "RUSH").length,
      nonRush: filteredActive.filter((row) => rushOf(row) === "NON_RUSH").length,
    }),
    [filteredActive]
  );

  const sentRushCount = useMemo(
    () => ({
      rush: filteredChecked.filter((row) => rushOf(row) === "RUSH").length,
      nonRush: filteredChecked.filter((row) => rushOf(row) === "NON_RUSH").length,
    }),
    [filteredChecked]
  );

  const groupedRows = useMemo(() => {
    const source = viewMode === "REMAINING" ? filteredActive : filteredChecked;
    const groups = {};

    source.forEach((row) => {
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
  }, [alphaOf, filteredActive, filteredChecked, viewMode]);

  const handleAlphaToggle = (alpha) => {
    setOpenAlpha((prev) => (prev === alpha ? null : alpha));
  };

  const handleCheckout = async () => {
    if (!activeOrder) return;

    try {
      setBusy(true);
      await checkoutOrder(activeOrder.id, "FrontDesk");
      await loadAll();
      setActiveOrder(null);
      showSnack("success", `${nameOf(activeOrder)} sent to rinse.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Checkout failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (!activeChecked) return;

    try {
      setBusy(true);
      await undoCheckout(activeChecked.order_id);
      await loadAll();
      setActiveChecked(null);
      showSnack("success", `Moved back to WashPro (#${activeChecked.order_id}).`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Undo failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleFullRefresh = async () => {
    setViewMode("REMAINING");
    setOpenAlpha(null);
    setActiveOrder(null);
    setActiveChecked(null);
    await loadAll();
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "70vh" }} spacing={1.2}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">Loading...</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <Stack direction="row" spacing={0.8}>
        <Segment
          label="Remaining"
          value={remainingCount}
          rush={remainingRushCount.rush}
          nonRush={remainingRushCount.nonRush}
          active={viewMode === "REMAINING"}
          onClick={() => {
            setViewMode("REMAINING");
            setOpenAlpha(null);
          }}
          activeBg="#111827"
        />
        <Segment
          label="Sent to Rinse"
          value={sentCount}
          rush={sentRushCount.rush}
          nonRush={sentRushCount.nonRush}
          active={viewMode === "SENT_TO_RINSE"}
          onClick={() => {
            setViewMode("SENT_TO_RINSE");
            setOpenAlpha(null);
          }}
          activeBg="#0097b2"
        />
      </Stack>

      <Stack direction="row" justifyContent="flex-end" sx={{ mt: 0.8 }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<Refresh />}
          onClick={handleFullRefresh}
          disabled={loading || busy}
        >
          Full Refresh
        </Button>
      </Stack>

      {viewMode === "REMAINING" && remainingCount > 0 && remainingRushCount.rush === 0 && (
        <Alert severity="success" sx={{ mt: 0.9 }}>
          All rush bags are checked out.
        </Alert>
      )}

      <Box sx={{ mt: 1.1 }}>
        {groupedRows.keys.map((alpha, idx) => {
          const rows = groupedRows.groups[alpha] || [];
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
                      fontWeight: 900,
                      fontSize: 14,
                    }}
                  >
                    {alpha}
                  </Box>
                  <Typography sx={{ fontSize: 16, fontWeight: 800, letterSpacing: 0.2 }}>
                    {rows.length} bags
                  </Typography>
                </Stack>
                {expanded ? <ExpandLess /> : <ExpandMore />}
              </Button>

              {expanded && (
                <Box sx={{ p: 1, bgcolor: "transparent" }}>
                  {rows.length === 0 ? (
                    <Typography sx={{ color: "#6b7280", fontSize: 14, px: 0.25, py: 0.5 }}>
                      No bags in this section.
                    </Typography>
                  ) : (
                    <Stack spacing={1.05}>
                      {rows.map((row) => {
                        const service = serviceOf(row);
                        const isHD = service === "HD";
                        const isRush = rushOf(row) === "RUSH";

                        return (
                          <Paper
                            key={`${viewMode}-${row.id || row.order_id}`}
                            onClick={() => {
                              if (viewMode === "REMAINING") setActiveOrder(row);
                              else setActiveChecked(row);
                            }}
                            sx={{
                              p: 1.15,
                              borderRadius: 1.8,
                              border: isHD ? "1px solid #0097b2" : "1.5px solid #ffbd59",
                              bgcolor: isHD ? "#0097b2" : "#111827",
                              cursor: "pointer",
                            }}
                          >
                              <Stack spacing={0.62}>
                                <Stack direction="row" justifyContent="space-between" alignItems="center">
                                  <Typography sx={{ fontSize: 19, fontWeight: 900, color: "#fff" }}>
                                    {nameOf(row)}
                                  </Typography>
                                  <ChevronRight sx={{ color: "#fff" }} />
                                </Stack>

                              <Typography sx={{ color: isHD ? "#ecfeff" : "#f8fafc", fontWeight: 700, fontSize: 14 }}>
                                {formatDate(viewMode === "REMAINING" ? row.date_clean : row.rush_date)} • {measureOf(row)}
                              </Typography>

                              <Stack direction="row" spacing={0.7}>
                                <Chip
                                  size="small"
                                  label={service}
                                  sx={{
                                    height: 24,
                                    fontWeight: 700,
                                    bgcolor: isHD ? "#ffffff" : "#fff4d9",
                                    color: "#111827",
                                    border: isHD ? "1px solid #ffffff" : "1px solid #ffbd59",
                                  }}
                                />
                                <Chip
                                  size="small"
                                  label={isRush ? "RUSH" : "NON-RUSH"}
                                  icon={isRush ? <Bolt sx={{ fontSize: 14 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                                  sx={{
                                    height: 24,
                                    fontWeight: 700,
                                    bgcolor: "#ffffff",
                                    color: "#111827",
                                    border: "1px solid #e5e7eb",
                                  }}
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

      <Dialog open={Boolean(activeOrder)} onClose={() => setActiveOrder(null)} fullWidth maxWidth="xs">
        <DialogTitle>Send to Rinse</DialogTitle>
        <DialogContent dividers>
          {activeOrder && (
            <Stack spacing={1}>
              <Typography sx={{ fontWeight: 900, fontSize: 22 }}>{nameOf(activeOrder)}</Typography>
              <Typography>{formatDate(activeOrder.date_clean)}</Typography>
              <Typography>{measureOf(activeOrder)}</Typography>
              <Typography>{serviceOf(activeOrder)} • {rushOf(activeOrder).replace("_", "-")}</Typography>
              <Alert severity="warning">Confirm physical tag before sending.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActiveOrder(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={handleCheckout} startIcon={<LocalShipping />}>
            Confirm Send
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(activeChecked)} onClose={() => setActiveChecked(null)} fullWidth maxWidth="xs">
        <DialogTitle>Move Back to WashPro</DialogTitle>
        <DialogContent dividers>
          {activeChecked && (
            <Stack spacing={1}>
              <Typography sx={{ fontWeight: 900, fontSize: 22 }}>{nameOf(activeChecked)}</Typography>
              <Typography>Order #{activeChecked.order_id}</Typography>
              <Typography>{formatDate(activeChecked.rush_date)}</Typography>
              <Alert severity="info">Use this only if sent by mistake.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActiveChecked(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={handleUndo} startIcon={<Undo />}>
            Undo Send
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={2200}
        onClose={() => setSnack((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={snack.severity}
          variant="filled"
          onClose={() => setSnack((prev) => ({ ...prev, open: false }))}
        >
          {snack.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

function Segment({ label, value, rush, nonRush, active, onClick, activeBg }) {
  return (
    <Button
      fullWidth
      onClick={onClick}
      sx={{
        borderRadius: 1.8,
        py: 0.75,
        textTransform: "none",
        bgcolor: active ? activeBg : "#eef1f4",
        color: active ? "#fff" : "#111827",
        justifyContent: "space-between",
        px: 1.1,
      }}
    >
      <Stack alignItems="flex-start" spacing={0.2}>
        <Typography sx={{ fontSize: 14, fontWeight: 800 }}>{label}</Typography>
        <Stack direction="row" spacing={0.7} alignItems="center" sx={{ opacity: active ? 0.95 : 0.85 }}>
          <Bolt sx={{ fontSize: 14 }} />
          <Typography sx={{ fontSize: 13, fontWeight: 900 }}>{rush}</Typography>
          <CheckCircle sx={{ fontSize: 14 }} />
          <Typography sx={{ fontSize: 13, fontWeight: 900 }}>{nonRush}</Typography>
        </Stack>
      </Stack>
      <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{value}</Typography>
    </Button>
  );
}

export default CheckoutPage;
