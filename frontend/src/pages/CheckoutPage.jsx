import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Paper,
  Snackbar,
  Stack,
  Typography,
  CircularProgress,
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

  const [viewMode, setViewMode] = useState("AT_WASHPRO"); // AT_WASHPRO | SENT_TO_RINSE
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

  const alphaOf = useCallback(
    (row) => {
      const ch = nameOf(row).charAt(0).toUpperCase();
      return /^[A-Z]$/.test(ch) ? ch : "#";
    },
    []
  );

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
    return orders.filter((row) => {
      const rush = rushOf(row);
      return rushFilter === "ALL" || rush === rushFilter;
    });
  }, [orders, rushFilter]);

  const filteredChecked = useMemo(() => {
    return checkedLogs.filter((row) => {
      const rush = rushOf(row);
      return rushFilter === "ALL" || rush === rushFilter;
    });
  }, [checkedLogs, rushFilter]);

  const atWashproCount = filteredActive.length;
  const sentToRinseCount = filteredChecked.length;

  const rushCounts = useMemo(() => {
    const source = viewMode === "AT_WASHPRO" ? filteredActive : filteredChecked;
    return {
      rush: source.filter((row) => rushOf(row) === "RUSH").length,
      nonRush: source.filter((row) => rushOf(row) === "NON-RUSH").length,
    };
  }, [filteredActive, filteredChecked, viewMode]);

  const groupedRows = useMemo(() => {
    const source = viewMode === "AT_WASHPRO" ? filteredActive : filteredChecked;
    const groups = {};

    source.forEach((row) => {
      const alpha = alphaOf(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });

    const keys = [...ALPHAS, "#"].filter((key) => groups[key]?.length);

    keys.forEach((key) => {
      groups[key].sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
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
    <Box sx={{ minHeight: "100%", bgcolor: "#f4f5f7", px: { xs: 1, sm: 1.5 }, py: 0.9 }}>
      <Stack direction="row" spacing={0.7}>
        <Segment
          label="At WashPro"
          value={atWashproCount}
          active={viewMode === "AT_WASHPRO"}
          onClick={() => setViewMode("AT_WASHPRO")}
        />
        <Segment
          label="Sent to Rinse"
          value={sentToRinseCount}
          active={viewMode === "SENT_TO_RINSE"}
          onClick={() => setViewMode("SENT_TO_RINSE")}
        />
      </Stack>

      <Stack direction="row" spacing={0.7} sx={{ mt: 0.8 }}>
        <Chip
          icon={<Bolt sx={{ fontSize: 16 }} />}
          label={`Rush ${rushCounts.rush}`}
          clickable
          size="small"
          onClick={() => setRushFilter(rushFilter === "RUSH" ? "ALL" : "RUSH")}
          sx={{
            height: 30,
            bgcolor: rushFilter === "RUSH" ? "#111827" : "#e5e7eb",
            color: rushFilter === "RUSH" ? "#fff" : "#111827",
            fontWeight: 700,
          }}
        />

        <Chip
          icon={<CheckCircle sx={{ fontSize: 16 }} />}
          label={`Non-Rush ${rushCounts.nonRush}`}
          clickable
          size="small"
          onClick={() => setRushFilter(rushFilter === "NON-RUSH" ? "ALL" : "NON-RUSH")}
          sx={{
            height: 30,
            bgcolor: rushFilter === "NON-RUSH" ? "#111827" : "#e5e7eb",
            color: rushFilter === "NON-RUSH" ? "#fff" : "#111827",
            fontWeight: 700,
          }}
        />

        <Chip
          label="All"
          clickable
          size="small"
          onClick={() => setRushFilter("ALL")}
          sx={{ height: 30, fontWeight: 700 }}
        />
      </Stack>

      <Box sx={{ mt: 1 }}>
        {groupedRows.keys.length === 0 ? (
          <Paper sx={{ p: 1.4, borderRadius: 1.5 }}>
            <Typography fontWeight={700}>No bags found</Typography>
          </Paper>
        ) : (
          groupedRows.keys.map((alpha) => {
            const rows = groupedRows.groups[alpha] || [];
            const expanded = Boolean(expandedAlpha[alpha]);

            return (
              <Paper key={alpha} sx={{ mb: 0.8, borderRadius: 1.5, overflow: "hidden" }}>
                <Button
                  fullWidth
                  onClick={() => toggleAlpha(alpha)}
                  sx={{
                    px: 1,
                    py: 1,
                    justifyContent: "space-between",
                    color: "#111827",
                    textTransform: "none",
                    bgcolor: "#eceff3",
                  }}
                >
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{alpha}</Typography>
                    <Typography sx={{ fontSize: 16, fontWeight: 700 }}>{rows.length} bags</Typography>
                  </Stack>
                  {expanded ? <ExpandLess /> : <ExpandMore />}
                </Button>

                {expanded && (
                  <Box sx={{ p: 0.8, bgcolor: "#f9fafb" }}>
                    <Stack spacing={0.7}>
                      {rows.map((row) => {
                        const service = String(row?.service_type || row?.service || "").toUpperCase();
                        const isHD = service === "HD";
                        const isRush = rushOf(row) === "RUSH";

                        return (
                          <Paper
                            key={`${viewMode}-${row.id || row.order_id}`}
                            onClick={() => {
                              if (viewMode === "AT_WASHPRO") setActiveOrder(row);
                              else setActiveChecked(row);
                            }}
                            sx={{
                              p: 1,
                              borderRadius: 1.5,
                              border: "1px solid #d1d5db",
                              bgcolor: isHD ? "#d9f2f1" : "#ffffff",
                              cursor: "pointer",
                            }}
                          >
                            <Stack spacing={0.45}>
                              <Stack direction="row" justifyContent="space-between" alignItems="center">
                                <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{nameOf(row)}</Typography>
                                <ChevronRight sx={{ color: "#6b7280" }} />
                              </Stack>

                              <Typography sx={{ color: "#4b5563", fontWeight: 700, fontSize: 14 }}>
                                {formatDate(viewMode === "AT_WASHPRO" ? row.date_clean : row.rush_date)} • {measureOf(row)}
                              </Typography>

                              <Stack direction="row" spacing={0.6}>
                                <Chip size="small" label={service} sx={{ height: 24, fontWeight: 700 }} />
                                <Chip
                                  size="small"
                                  icon={isRush ? <Bolt sx={{ fontSize: 14 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                                  label={isRush ? "RUSH" : "NON-RUSH"}
                                  sx={{ height: 24, fontWeight: 700 }}
                                />
                              </Stack>
                            </Stack>
                          </Paper>
                        );
                      })}
                    </Stack>
                  </Box>
                )}
              </Paper>
            );
          })
        )}
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

function Segment({ label, value, active, onClick }) {
  return (
    <Button
      fullWidth
      onClick={onClick}
      sx={{
        borderRadius: 1.5,
        py: 0.65,
        textTransform: "none",
        bgcolor: active ? "#111827" : "#e5e7eb",
        color: active ? "#fff" : "#111827",
        justifyContent: "space-between",
        px: 1,
      }}
    >
      <Typography sx={{ fontSize: 14, fontWeight: 800 }}>{label}</Typography>
      <Typography sx={{ fontSize: 14, fontWeight: 900 }}>{value}</Typography>
    </Button>
  );
}

export default CheckoutPage;
