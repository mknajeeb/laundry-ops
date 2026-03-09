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
  Undo,
} from "@mui/icons-material";
import { checkoutOrder, getCheckoutLog, getOrders, undoCheckout } from "../api";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function CheckoutPage() {
  const [orders, setOrders] = useState([]);
  const [checkedLogs, setCheckedLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [viewMode, setViewMode] = useState("REMAINING"); // REMAINING | SENT_TO_RINSE
  const [rushFilter, setRushFilter] = useState("ALL"); // ALL | RUSH | NON-RUSH

  const [expandedAlpha, setExpandedAlpha] = useState({});
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

  const rushOf = (row) => {
    if (row?.rush_type) return String(row.rush_type).toUpperCase();

    if (row?.rush_date) {
      const due = new Date(row.rush_date);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return due < today ? "RUSH" : "NON-RUSH";
    }

    return "NON-RUSH";
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

  const filteredActive = useMemo(() => {
    return orders.filter((row) => rushFilter === "ALL" || rushOf(row) === rushFilter);
  }, [orders, rushFilter]);

  const filteredChecked = useMemo(() => {
    return checkedLogs.filter((row) => rushFilter === "ALL" || rushOf(row) === rushFilter);
  }, [checkedLogs, rushFilter]);

  const remainingCount = filteredActive.length;
  const sentToRinseCount = filteredChecked.length;

  const rushCounts = useMemo(() => {
    const source = viewMode === "REMAINING" ? filteredActive : filteredChecked;
    return {
      rush: source.filter((row) => rushOf(row) === "RUSH").length,
      nonRush: source.filter((row) => rushOf(row) === "NON-RUSH").length,
    };
  }, [filteredActive, filteredChecked, viewMode]);

  const groupedRows = useMemo(() => {
    const source = viewMode === "REMAINING" ? filteredActive : filteredChecked;
    const groups = {};

    source.forEach((row) => {
      const alpha = alphaOf(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });

    const keys = [...ALPHAS];
    if (groups["#"]?.length) keys.push("#");

    keys.forEach((k) => {
      if (!groups[k]) groups[k] = [];
      groups[k].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
    });

    return { keys, groups };
  }, [alphaOf, filteredActive, filteredChecked, viewMode]);

  const toggleAlpha = (alpha) => {
    setExpandedAlpha((prev) => ({ ...prev, [alpha]: !prev[alpha] }));
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
          active={viewMode === "REMAINING"}
          onClick={() => setViewMode("REMAINING")}
          activeBg="#111827"
        />
        <Segment
          label="Sent to Rinse"
          value={sentToRinseCount}
          active={viewMode === "SENT_TO_RINSE"}
          onClick={() => setViewMode("SENT_TO_RINSE")}
          activeBg="#0097b2"
        />
      </Stack>

      {viewMode === "REMAINING" && (
        <Stack direction="row" spacing={0.8} sx={{ mt: 0.9 }}>
          <Chip
            icon={<Bolt sx={{ fontSize: 16 }} />}
            label={`Rush ${rushCounts.rush}`}
            clickable
            size="small"
            onClick={() => setRushFilter(rushFilter === "RUSH" ? "ALL" : "RUSH")}
            sx={{
              height: 32,
              bgcolor: rushFilter === "RUSH" ? "#111827" : "#e5e7eb",
              color: rushFilter === "RUSH" ? "#fff" : "#111827",
              fontWeight: 800,
            }}
          />

          <Chip
            icon={<CheckCircle sx={{ fontSize: 16 }} />}
            label={`Non-Rush ${rushCounts.nonRush}`}
            clickable
            size="small"
            onClick={() => setRushFilter(rushFilter === "NON-RUSH" ? "ALL" : "NON-RUSH")}
            sx={{
              height: 32,
              bgcolor: rushFilter === "NON-RUSH" ? "#111827" : "#e5e7eb",
              color: rushFilter === "NON-RUSH" ? "#fff" : "#111827",
              fontWeight: 800,
            }}
          />
        </Stack>
      )}

      {viewMode === "REMAINING" && remainingCount > 0 && rushCounts.rush === 0 && (
        <Alert severity="success" sx={{ mt: 0.9 }}>
          All rush bags are checked out.
        </Alert>
      )}

      <Box sx={{ mt: 1.1 }}>
        {groupedRows.keys.map((alpha) => {
          const rows = groupedRows.groups[alpha] || [];
          const expanded = Boolean(expandedAlpha[alpha]);

          return (
            <Paper
              key={alpha}
              sx={{
                mb: 1.05,
                borderRadius: 2,
                overflow: "hidden",
                border: "1px solid #e5e7eb",
                boxShadow: "none",
                bgcolor: "#ffffff",
              }}
            >
              <Button
                fullWidth
                onClick={() => toggleAlpha(alpha)}
                sx={{
                  px: 1.1,
                  py: 1.05,
                  justifyContent: "space-between",
                  color: "#111827",
                  textTransform: "none",
                  bgcolor: "#ffffff",
                }}
              >
                <Stack direction="row" spacing={1.2} alignItems="center">
                  <Box
                    sx={{
                      width: 30,
                      height: 30,
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
                  <Typography sx={{ fontSize: 16, fontWeight: 800, letterSpacing: 0.1 }}>
                    {rows.length} bags
                  </Typography>
                </Stack>
                {expanded ? <ExpandLess /> : <ExpandMore />}
              </Button>

              {expanded && (
                <Box sx={{ p: 1, bgcolor: "transparent" }}>
                  {rows.length === 0 ? (
                    <Typography sx={{ color: "#6b7280", fontSize: 14, px: 0.2, py: 0.6 }}>
                      No bags in this section.
                    </Typography>
                  ) : (
                    <Stack spacing={1}>
                      {rows.map((row) => {
                        const service = String(row?.service_type || row?.service || "").toUpperCase();
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
                            <Stack spacing={0.6}>
                              <Stack direction="row" justifyContent="space-between" alignItems="center">
                                <Typography sx={{ fontSize: 19, fontWeight: 900, color: "#fff" }}>
                                  {nameOf(row)}
                                </Typography>
                                <ChevronRight sx={{ color: "#ffffff" }} />
                              </Stack>

                              <Typography sx={{ color: isHD ? "#ecfeff" : "#f8fafc", fontWeight: 700, fontSize: 14 }}>
                                {formatDate(viewMode === "REMAINING" ? row.date_clean : row.rush_date)} • {measureOf(row)}
                              </Typography>

                              <Stack direction="row" spacing={0.6}>
                                <Chip
                                  size="small"
                                  label={service}
                                  sx={{
                                    height: 24,
                                    fontWeight: 700,
                                    bgcolor: isHD ? "rgba(255,255,255,0.16)" : "rgba(255,189,89,0.17)",
                                    color: "#fff",
                                    border: isHD ? "1px solid rgba(255,255,255,0.42)" : "1px solid #ffbd59",
                                  }}
                                />
                                <Chip
                                  size="small"
                                  icon={isRush ? <Bolt sx={{ fontSize: 14 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                                  label={isRush ? "RUSH" : "NON-RUSH"}
                                  sx={{
                                    height: 24,
                                    fontWeight: 700,
                                    bgcolor: isHD ? "rgba(255,255,255,0.16)" : "rgba(255,255,255,0.14)",
                                    color: "#fff",
                                    border: isHD ? "1px solid rgba(255,255,255,0.42)" : "1px solid #d1d5db",
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
              <Typography>{String(activeOrder.service_type || "").toUpperCase()} • {rushOf(activeOrder)}</Typography>
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

function Segment({ label, value, active, onClick, activeBg }) {
  return (
    <Button
      fullWidth
      onClick={onClick}
      sx={{
        borderRadius: 1.8,
        py: 0.75,
        textTransform: "none",
        bgcolor: active ? activeBg : "#e5e7eb",
        color: active ? "#fff" : "#111827",
        justifyContent: "space-between",
        px: 1.1,
      }}
    >
      <Typography sx={{ fontSize: 14, fontWeight: 800 }}>{label}</Typography>
      <Typography sx={{ fontSize: 14, fontWeight: 900 }}>{value}</Typography>
    </Button>
  );
}

export default CheckoutPage;
