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
  Divider,
  InputAdornment,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { CheckCircle, ExpandLess, ExpandMore, Search, Undo } from "@mui/icons-material";
import { checkoutBulk, checkoutOrder, getCheckoutLog, getOrders, undoCheckout } from "../api";

const ALPHAS = ["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

function CheckoutPage() {
  const [orders, setOrders] = useState([]);
  const [checkedLogs, setCheckedLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [search, setSearch] = useState("");
  const [alphaFilter, setAlphaFilter] = useState("ALL");
  const [viewMode, setViewMode] = useState("ACTIVE"); // ACTIVE | CHECKED | BOTH
  const [enabledServices, setEnabledServices] = useState(["WF", "HD"]);
  const [enabledRush, setEnabledRush] = useState(["RUSH", "NON-RUSH"]);

  const [selectedIds, setSelectedIds] = useState([]);
  const [checkedExpanded, setCheckedExpanded] = useState({});
  const [confirmOrder, setConfirmOrder] = useState(null);

  const [snack, setSnack] = useState({
    open: false,
    severity: "success",
    message: "",
  });

  const showSnack = useCallback((severity, message) => {
    setSnack({ open: true, severity, message });
  }, []);

  const getName = useCallback((row) => String(row?.name_clean || row?.name || "").trim(), []);

  const getAlpha = useCallback(
    (row) => {
      const first = getName(row).charAt(0).toUpperCase();
      return /^[A-Z]$/.test(first) ? first : "#";
    },
    [getName]
  );

  const normalizeText = (value) => String(value || "").trim().toLowerCase();

  const formatDateOnly = (value) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).split(" ")[0];
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const formatMeasure = (row) => {
    const service = String(row?.service_type || row?.service || "").toUpperCase();
    const raw = Number(row?.weight_num ?? row?.weight ?? 0);

    if (service === "WF") return `${raw.toFixed(2)} lb`;
    if (service === "HD") return `${Math.round(raw)} pcs`;
    return "-";
  };

  const rushType = (row) => {
    if (row?.rush_type) return String(row.rush_type).toUpperCase();

    if (row?.rush_date) {
      const due = new Date(row.rush_date);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return due < today ? "RUSH" : "NON-RUSH";
    }

    return "NON-RUSH";
  };

  const loadOrders = useCallback(async () => {
    const res = await getOrders();
    const rows = Array.isArray(res.data) ? res.data : [];
    return rows.filter((row) => String(row?.status || "").toUpperCase() !== "CHECKED_OUT");
  }, []);

  const loadChecked = useCallback(async () => {
    const res = await getCheckoutLog();
    return Array.isArray(res.data) ? res.data : [];
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      setLoading(true);
      const [activeRows, checkedRows] = await Promise.all([loadOrders(), loadChecked()]);
      setOrders(activeRows);
      setCheckedLogs(checkedRows);
      setSelectedIds((prev) => prev.filter((id) => activeRows.some((row) => row.id === id)));
    } catch (error) {
      console.error(error);
      showSnack("error", "Failed to load checkout data.");
    } finally {
      setLoading(false);
    }
  }, [loadChecked, loadOrders, showSnack]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const matchesFilters = useCallback(
    (row, checked = false) => {
      const name = normalizeText(getName(row));
      const q = normalizeText(search);
      const svc = String(checked ? row?.service : row?.service_type || "").toUpperCase();
      const rush = rushType(row);
      const alpha = getAlpha(row);

      const searchMatch =
        !q ||
        name.includes(q) ||
        String(checked ? row?.order_id : row?.id || "").includes(q);

      const serviceMatch = enabledServices.includes(svc);
      const rushMatch = enabledRush.includes(rush);
      const alphaMatch = alphaFilter === "ALL" || alpha === alphaFilter;

      return searchMatch && serviceMatch && rushMatch && alphaMatch;
    },
    [alphaFilter, enabledRush, enabledServices, getAlpha, getName, search]
  );

  const activeRows = useMemo(() => orders.filter((row) => matchesFilters(row, false)), [orders, matchesFilters]);
  const checkedRows = useMemo(
    () => checkedLogs.filter((row) => matchesFilters(row, true)),
    [checkedLogs, matchesFilters]
  );

  const remainingCount = activeRows.length;

  const alphaCounts = useMemo(() => {
    const source = viewMode === "CHECKED" ? checkedRows : activeRows;
    const counts = {};
    ALPHAS.forEach((a) => {
      counts[a] = 0;
    });

    source.forEach((row) => {
      const a = getAlpha(row);
      if (!counts[a]) counts[a] = 0;
      counts[a] += 1;
    });

    return counts;
  }, [activeRows, checkedRows, getAlpha, viewMode]);

  const groupedActive = useMemo(() => {
    const groups = {};
    activeRows.forEach((row) => {
      const a = getAlpha(row);
      if (!groups[a]) groups[a] = [];
      groups[a].push(row);
    });
    return groups;
  }, [activeRows, getAlpha]);

  const groupedChecked = useMemo(() => {
    const groups = {};
    checkedRows.forEach((row) => {
      const a = getAlpha(row);
      if (!groups[a]) groups[a] = [];
      groups[a].push(row);
    });
    return groups;
  }, [checkedRows, getAlpha]);

  const alphaKeys = useMemo(() => {
    if (alphaFilter !== "ALL") return [alphaFilter];

    const keys = new Set([...Object.keys(groupedActive), ...Object.keys(groupedChecked)]);
    return Array.from(keys).sort((a, b) => {
      if (a === "#") return 1;
      if (b === "#") return -1;
      return a.localeCompare(b);
    });
  }, [alphaFilter, groupedActive, groupedChecked]);

  const visibleIds = useMemo(() => {
    if (alphaFilter === "ALL") return activeRows.map((row) => row.id);
    return (groupedActive[alphaFilter] || []).map((row) => row.id);
  }, [activeRows, alphaFilter, groupedActive]);

  const selectedVisibleIds = useMemo(
    () => selectedIds.filter((id) => visibleIds.includes(id)),
    [selectedIds, visibleIds]
  );

  const toggleFilter = (value, list, setList) => {
    setList((prev) => {
      if (prev.includes(value)) {
        const next = prev.filter((v) => v !== value);
        return next.length ? next : prev;
      }
      return [...prev, value];
    });
  };

  const clearUiFilters = () => {
    setSearch("");
    setAlphaFilter("ALL");
    setEnabledServices(["WF", "HD"]);
    setEnabledRush(["RUSH", "NON-RUSH"]);
    setViewMode("ACTIVE");
  };

  const toggleCheckedExpanded = (alpha) => {
    setCheckedExpanded((prev) => ({ ...prev, [alpha]: !prev[alpha] }));
  };

  const handleConfirmCheckout = async () => {
    if (!confirmOrder) return;

    try {
      setBusy(true);
      await checkoutOrder(confirmOrder.id, "FrontDesk");
      await refreshAll();
      setConfirmOrder(null);
      showSnack("success", `${getName(confirmOrder)} checked out.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Checkout failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleBulkCheckout = async () => {
    if (!selectedVisibleIds.length) {
      showSnack("warning", "Select at least one bag.");
      return;
    }

    try {
      setBusy(true);
      await checkoutBulk(selectedVisibleIds, "FrontDesk");
      await refreshAll();
      showSnack("success", `${selectedVisibleIds.length} bag(s) checked out.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Bulk checkout failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async (orderId) => {
    try {
      setBusy(true);
      await undoCheckout(orderId);
      await refreshAll();
      showSnack("success", `Checkout reversed for #${orderId}.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Undo failed.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "70vh" }} spacing={1}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">Loading checkout...</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#f3f4f6", pb: 11 }}>
      <Box
        sx={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          px: 1,
          py: 0.8,
          bgcolor: "#f3f4f6",
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography sx={{ fontSize: 22, fontWeight: 900 }}>Checkout</Typography>
          <Typography sx={{ fontSize: 14, fontWeight: 800, color: "#166534" }}>
            {remainingCount} remaining
          </Typography>
        </Stack>

        <Stack direction="row" spacing={0.6} sx={{ mt: 0.8, overflowX: "auto", pb: 0.3 }}>
          <MiniToggle label={`Active ${activeRows.length}`} active={viewMode === "ACTIVE"} onClick={() => setViewMode("ACTIVE")} />
          <MiniToggle label={`Checked ${checkedRows.length}`} active={viewMode === "CHECKED"} onClick={() => setViewMode("CHECKED")} />
          <MiniToggle label="Both" active={viewMode === "BOTH"} onClick={() => setViewMode("BOTH")} />
        </Stack>

        <TextField
          fullWidth
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name or id"
          sx={{ mt: 0.8, "& .MuiOutlinedInput-root": { bgcolor: "#fff", borderRadius: 1.5 } }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search fontSize="small" />
              </InputAdornment>
            ),
          }}
        />

        <Stack direction="row" spacing={0.6} sx={{ mt: 0.8, overflowX: "auto", pb: 0.2 }}>
          <MiniToggle label="WF" active={enabledServices.includes("WF")} onClick={() => toggleFilter("WF", enabledServices, setEnabledServices)} />
          <MiniToggle label="HD" active={enabledServices.includes("HD")} onClick={() => toggleFilter("HD", enabledServices, setEnabledServices)} />
          <MiniToggle label="R" active={enabledRush.includes("RUSH")} onClick={() => toggleFilter("RUSH", enabledRush, setEnabledRush)} />
          <MiniToggle label="N" active={enabledRush.includes("NON-RUSH")} onClick={() => toggleFilter("NON-RUSH", enabledRush, setEnabledRush)} />
          <Chip label="Reset" size="small" variant="outlined" onClick={clearUiFilters} clickable sx={{ height: 28 }} />
        </Stack>

        <Stack direction="row" spacing={0.55} sx={{ mt: 0.75, overflowX: "auto", pb: 0.15 }}>
          {ALPHAS.map((alpha) => {
            const count = alphaCounts[alpha] || 0;
            return (
              <Chip
                key={alpha}
                label={alpha === "ALL" ? `ALL ${count}` : alpha}
                size="small"
                clickable
                onClick={() => setAlphaFilter(alpha)}
                sx={{
                  height: 30,
                  minWidth: alpha === "ALL" ? 64 : 30,
                  borderRadius: 1,
                  bgcolor: alphaFilter === alpha ? "#111827" : "#e5e7eb",
                  color: alphaFilter === alpha ? "#fff" : "#111827",
                  fontWeight: 800,
                }}
              />
            );
          })}
        </Stack>
      </Box>

      <Box sx={{ px: 1, pt: 0.8 }}>
        {remainingCount === 1 && (
          <Alert
            severity="warning"
            sx={{ mb: 0.8 }}
            action={
              <Button
                size="small"
                color="inherit"
                onClick={() => {
                  setAlphaFilter("ALL");
                  setViewMode("ACTIVE");
                }}
              >
                Find
              </Button>
            }
          >
            Only 1 bag remaining.
          </Alert>
        )}

        {alphaKeys.length === 0 ? (
          <Paper sx={{ p: 1.4, borderRadius: 1.5 }}>
            <Typography fontWeight={700}>No matching bags</Typography>
          </Paper>
        ) : (
          alphaKeys.map((alpha) => {
            const activeForAlpha = groupedActive[alpha] || [];
            const checkedForAlpha = groupedChecked[alpha] || [];
            const expanded = Boolean(checkedExpanded[alpha]);

            const showActive = viewMode === "ACTIVE" || viewMode === "BOTH";
            const showChecked = viewMode === "CHECKED" || viewMode === "BOTH";

            return (
              <Box key={alpha} sx={{ mb: 1 }}>
                <Paper sx={{ p: 0.85, borderRadius: 1.3, bgcolor: "#e5e7eb" }}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Stack direction="row" spacing={0.7} alignItems="center">
                      <Chip size="small" label={alpha} sx={{ bgcolor: "#111827", color: "#fff", height: 24 }} />
                      <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{activeForAlpha.length} active</Typography>
                      <Typography sx={{ fontWeight: 700, color: "#6b7280", fontSize: 14 }}>{checkedForAlpha.length} checked</Typography>
                    </Stack>
                    {checkedForAlpha.length > 0 && (
                      <Button
                        size="small"
                        color="inherit"
                        endIcon={expanded ? <ExpandLess /> : <ExpandMore />}
                        onClick={() => toggleCheckedExpanded(alpha)}
                        sx={{ minWidth: 30, px: 0.5 }}
                      >
                        Log
                      </Button>
                    )}
                  </Stack>
                </Paper>

                <Stack spacing={0.8} sx={{ mt: 0.7 }}>
                  {showActive &&
                    activeForAlpha.map((row) => {
                      const selected = selectedIds.includes(row.id);
                      const isRush = rushType(row) === "RUSH";

                      return (
                        <Paper key={row.id} sx={{ p: 1, borderRadius: 1.5, border: selected ? "2px solid #2563eb" : "1px solid #d1d5db" }}>
                          <Stack spacing={0.55}>
                            <Stack direction="row" alignItems="center" justifyContent="space-between">
                              <Typography sx={{ fontSize: 18, fontWeight: 900 }}>{getName(row)}</Typography>
                              <Typography sx={{ fontSize: 12, color: "#6b7280", fontWeight: 800 }}>#{row.id}</Typography>
                            </Stack>
                            <Typography sx={{ color: "#4b5563", fontWeight: 700, fontSize: 15 }}>
                              {formatMeasure(row)} • {formatDateOnly(row.date_clean)}
                            </Typography>

                            <Stack direction="row" spacing={0.6}>
                              <Chip size="small" label={row.service_type || "-"} sx={{ height: 24 }} />
                              <Chip size="small" label={isRush ? "RUSH" : "NON-RUSH"} sx={{ height: 24 }} />
                            </Stack>

                            <Stack direction="row" spacing={0.8}>
                              <Button fullWidth size="small" variant={selected ? "contained" : "outlined"} onClick={() => setSelectedIds((prev) => (prev.includes(row.id) ? prev.filter((id) => id !== row.id) : [...prev, row.id]))}>
                                {selected ? "Selected" : "Select"}
                              </Button>
                              <Button fullWidth size="small" variant="contained" onClick={() => setConfirmOrder(row)}>
                                Checkout
                              </Button>
                            </Stack>
                          </Stack>
                        </Paper>
                      );
                    })}

                  {showChecked && expanded && checkedForAlpha.length > 0 && (
                    <Paper sx={{ p: 0.9, borderRadius: 1.5, bgcolor: "#1f2937", color: "#fff" }}>
                      <Typography sx={{ fontSize: 13, fontWeight: 800, mb: 0.6 }}>Checked Out</Typography>
                      <Stack spacing={0.55}>
                        {checkedForAlpha.map((row) => (
                          <Box key={`${row.id}-${row.order_id}`}>
                            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                              <Box>
                                <Typography sx={{ fontSize: 14, fontWeight: 800 }}>
                                  {getName(row)} #{row.order_id}
                                </Typography>
                                <Typography sx={{ fontSize: 12, color: "#cbd5e1" }}>
                                  {formatMeasure(row)} • {formatDateOnly(row.rush_date)}
                                </Typography>
                              </Box>
                              <Button size="small" color="inherit" variant="outlined" startIcon={<Undo />} onClick={() => handleUndo(row.order_id)}>
                                Undo
                              </Button>
                            </Stack>
                            <Divider sx={{ borderColor: "#334155", mt: 0.6 }} />
                          </Box>
                        ))}
                      </Stack>
                    </Paper>
                  )}
                </Stack>
              </Box>
            );
          })
        )}
      </Box>

      <Paper sx={{ position: "fixed", left: 0, right: 0, bottom: 62, borderTop: "1px solid #d1d5db", p: 0.8, zIndex: 35 }}>
        <Typography sx={{ fontWeight: 900, fontSize: 16 }}>{remainingCount} remaining</Typography>
        <Typography sx={{ fontSize: 12, color: "#6b7280" }}>{selectedVisibleIds.length} selected</Typography>
        <Stack direction="row" spacing={0.8} sx={{ mt: 0.6 }}>
          <Button fullWidth size="small" variant="outlined" onClick={() => setSelectedIds([])}>
            Clear
          </Button>
          <Button fullWidth size="small" variant="contained" disabled={busy || !selectedVisibleIds.length} onClick={handleBulkCheckout}>
            Checkout Selected
          </Button>
        </Stack>
      </Paper>

      <Dialog open={Boolean(confirmOrder)} onClose={() => setConfirmOrder(null)} fullWidth maxWidth="xs">
        <DialogTitle>Confirm Checkout</DialogTitle>
        <DialogContent dividers>
          {confirmOrder && (
            <Stack spacing={0.8}>
              <Typography sx={{ fontSize: 22, fontWeight: 900 }}>{getName(confirmOrder)}</Typography>
              <Typography>{formatMeasure(confirmOrder)}</Typography>
              <Typography>Date: {formatDateOnly(confirmOrder.date_clean)}</Typography>
              <Alert severity="warning">Verify physical tag before confirm.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOrder(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={handleConfirmCheckout}>
            Confirm
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={2300}
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

function MiniToggle({ label, active, onClick }) {
  return (
    <Chip
      label={label}
      size="small"
      clickable
      onClick={onClick}
      sx={{
        height: 28,
        borderRadius: 1,
        bgcolor: active ? "#111827" : "#e5e7eb",
        color: active ? "#fff" : "#111827",
        fontWeight: 800,
      }}
    />
  );
}

export default CheckoutPage;
