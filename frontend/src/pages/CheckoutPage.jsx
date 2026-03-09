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
import { CheckCircle, ExpandLess, ExpandMore, FlashOn, Person, Search, Undo } from "@mui/icons-material";
import { checkoutBulk, checkoutOrder, getCheckoutLog, getOrders, undoCheckout } from "../api";

const ALPHA_LIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function CheckoutPage() {
  const [orders, setOrders] = useState([]);
  const [checkedLogs, setCheckedLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [search, setSearch] = useState("");
  const [employee, setEmployee] = useState("FrontDesk");

  const [enabledServices, setEnabledServices] = useState(["WF", "HD"]);
  const [enabledRush, setEnabledRush] = useState(["RUSH", "NON-RUSH"]);
  const [alphaFilter, setAlphaFilter] = useState("ALL");
  const [viewMode, setViewMode] = useState("ACTIVE"); // ACTIVE | CHECKED | BOTH

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

  const normalizeText = (value) => String(value || "").trim().toLowerCase();

  const getName = useCallback((row) => String(row?.name_clean || row?.name || "").trim(), []);

  const getAlpha = useCallback(
    (row) => {
      const first = getName(row).charAt(0).toUpperCase();
      return /^[A-Z]$/.test(first) ? first : "#";
    },
    [getName]
  );

  const formatDateOnly = (value) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).split(" ")[0];
    return date.toLocaleDateString(undefined, {
      weekday: "short",
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

  const deriveRushType = (row) => {
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

  const loadCheckoutLog = useCallback(async () => {
    const res = await getCheckoutLog();
    return Array.isArray(res.data) ? res.data : [];
  }, []);

  const loadPage = useCallback(async () => {
    try {
      setLoading(true);
      const [activeRows, checkoutRows] = await Promise.all([loadOrders(), loadCheckoutLog()]);
      setOrders(activeRows);
      setCheckedLogs(checkoutRows);
    } catch (error) {
      console.error(error);
      showSnack("error", "Failed to load checkout data.");
    } finally {
      setLoading(false);
    }
  }, [loadCheckoutLog, loadOrders, showSnack]);

  useEffect(() => {
    loadPage();
  }, [loadPage]);

  const toggleMultiFilter = (value, list, setList) => {
    setList((prev) => {
      if (prev.includes(value)) {
        const next = prev.filter((x) => x !== value);
        return next.length ? next : prev;
      }
      return [...prev, value];
    });
  };

  const matchCommonFilters = useCallback(
    (row, { useCheckedFields = false } = {}) => {
      const service = String(useCheckedFields ? row?.service : row?.service_type || "").toUpperCase();
      const rush = deriveRushType(row);
      const alpha = getAlpha(row);
      const q = normalizeText(search);

      const searchMatch =
        !q ||
        normalizeText(getName(row)).includes(q) ||
        String(useCheckedFields ? row?.order_id : row?.id || "").includes(q);

      const serviceMatch = enabledServices.includes(service);
      const rushMatch = enabledRush.includes(rush);
      const alphaMatch = alphaFilter === "ALL" || alpha === alphaFilter;

      return searchMatch && serviceMatch && rushMatch && alphaMatch;
    },
    [alphaFilter, enabledRush, enabledServices, getAlpha, getName, search]
  );

  const activeFiltered = useMemo(
    () => orders.filter((row) => matchCommonFilters(row)),
    [orders, matchCommonFilters]
  );

  const checkedFiltered = useMemo(
    () => checkedLogs.filter((row) => matchCommonFilters(row, { useCheckedFields: true })),
    [checkedLogs, matchCommonFilters]
  );

  const alphaCounts = useMemo(() => {
    const baseRows = viewMode === "CHECKED" ? checkedFiltered : activeFiltered;
    const counts = {};

    ALPHA_LIST.forEach((letter) => {
      counts[letter] = 0;
    });

    baseRows.forEach((row) => {
      const alpha = getAlpha(row);
      if (!counts[alpha]) counts[alpha] = 0;
      counts[alpha] += 1;
    });

    return counts;
  }, [activeFiltered, checkedFiltered, getAlpha, viewMode]);

  const groupedActive = useMemo(() => {
    const groups = {};
    activeFiltered.forEach((row) => {
      const alpha = getAlpha(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });
    return groups;
  }, [activeFiltered, getAlpha]);

  const groupedChecked = useMemo(() => {
    const groups = {};
    checkedFiltered.forEach((row) => {
      const alpha = getAlpha(row);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(row);
    });
    return groups;
  }, [checkedFiltered, getAlpha]);

  const alphaKeys = useMemo(() => {
    const source = new Set([
      ...Object.keys(groupedActive),
      ...Object.keys(groupedChecked),
      ...(alphaFilter === "ALL" ? [] : [alphaFilter]),
    ]);

    const keys = Array.from(source).sort((a, b) => {
      if (a === "#") return 1;
      if (b === "#") return -1;
      return a.localeCompare(b);
    });

    if (alphaFilter !== "ALL") {
      return keys.filter((k) => k === alphaFilter);
    }

    return keys;
  }, [alphaFilter, groupedActive, groupedChecked]);

  const remainingCount = activeFiltered.length;
  const checkedCount = checkedFiltered.length;

  const visibleActiveRows = useMemo(() => {
    if (alphaFilter === "ALL") return activeFiltered;
    return activeFiltered.filter((row) => getAlpha(row) === alphaFilter);
  }, [activeFiltered, alphaFilter, getAlpha]);

  const visibleIds = useMemo(() => visibleActiveRows.map((row) => row.id), [visibleActiveRows]);
  const selectedVisibleIds = useMemo(
    () => selectedIds.filter((id) => visibleIds.includes(id)),
    [selectedIds, visibleIds]
  );

  const clearFilters = () => {
    setSearch("");
    setEnabledServices(["WF", "HD"]);
    setEnabledRush(["RUSH", "NON-RUSH"]);
    setAlphaFilter("ALL");
    setViewMode("ACTIVE");
  };

  const toggleCheckedExpand = (alpha) => {
    setCheckedExpanded((prev) => ({ ...prev, [alpha]: !prev[alpha] }));
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const refreshAfterMutation = async () => {
    const [activeRows, checkoutRows] = await Promise.all([loadOrders(), loadCheckoutLog()]);
    setOrders(activeRows);
    setCheckedLogs(checkoutRows);
    setSelectedIds((prev) => prev.filter((id) => activeRows.some((row) => row.id === id)));
  };

  const handleConfirmCheckout = async () => {
    if (!confirmOrder) return;

    try {
      setBusy(true);
      await checkoutOrder(confirmOrder.id, employee);
      await refreshAfterMutation();
      showSnack("success", `${getName(confirmOrder)} checked out.`);
      setConfirmOrder(null);
    } catch (error) {
      console.error(error);
      showSnack("error", "Checkout failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleCheckoutSelected = async () => {
    if (!selectedVisibleIds.length) {
      showSnack("warning", "Select at least one bag.");
      return;
    }

    try {
      setBusy(true);
      await checkoutBulk(selectedVisibleIds, employee);
      await refreshAfterMutation();
      showSnack("success", `${selectedVisibleIds.length} bag(s) checked out.`);
      setViewMode("ACTIVE");
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
      await refreshAfterMutation();
      showSnack("success", `Checkout reversed for #${orderId}.`);
      setViewMode("ACTIVE");
    } catch (error) {
      console.error(error);
      showSnack("error", "Undo failed.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "70vh" }} spacing={2}>
        <CircularProgress />
        <Typography>Loading checkout workflow...</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", background: "#f3f4f6", pb: 13 }}>
      <Box
        sx={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          background: "#f3f4f6",
          borderBottom: "1px solid #d1d5db",
          px: 1.2,
          pt: 1,
          pb: 1,
        }}
      >
        <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>Checkout</Typography>
        <Typography sx={{ color: "#16a34a", fontWeight: 800, mt: 0.3 }}>
          {remainingCount} bags remaining
        </Typography>

        <Stack direction="row" spacing={0.8} sx={{ mt: 1, overflowX: "auto", pb: 0.4 }}>
          <Chip
            label={`Active ${remainingCount}`}
            clickable
            color={viewMode === "ACTIVE" ? "primary" : "default"}
            onClick={() => setViewMode("ACTIVE")}
          />
          <Chip
            label={`Checked ${checkedCount}`}
            clickable
            color={viewMode === "CHECKED" ? "warning" : "default"}
            onClick={() => setViewMode("CHECKED")}
          />
          <Chip
            label="Both"
            clickable
            color={viewMode === "BOTH" ? "secondary" : "default"}
            onClick={() => setViewMode("BOTH")}
          />
          <Chip
            label={`All Remaining ${remainingCount}`}
            variant="outlined"
            clickable
            onClick={() => {
              setAlphaFilter("ALL");
              setViewMode("ACTIVE");
            }}
          />
        </Stack>

        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name or id"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ "& .MuiOutlinedInput-root": { background: "#fff", borderRadius: 2 } }}
          />
          <TextField
            size="small"
            value={employee}
            onChange={(e) => setEmployee(e.target.value)}
            placeholder="Employee"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Person fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ "& .MuiOutlinedInput-root": { background: "#fff", borderRadius: 2 } }}
          />
        </Stack>

        <Stack direction="row" spacing={0.8} sx={{ mt: 1, overflowX: "auto", pb: 0.3 }}>
          <Chip
            label={`WF ${enabledServices.includes("WF") ? "✓" : ""}`}
            clickable
            color={enabledServices.includes("WF") ? "warning" : "default"}
            onClick={() => toggleMultiFilter("WF", enabledServices, setEnabledServices)}
          />
          <Chip
            label={`HD ${enabledServices.includes("HD") ? "✓" : ""}`}
            clickable
            color={enabledServices.includes("HD") ? "warning" : "default"}
            onClick={() => toggleMultiFilter("HD", enabledServices, setEnabledServices)}
          />
          <Chip
            label={`RUSH ${enabledRush.includes("RUSH") ? "✓" : ""}`}
            clickable
            color={enabledRush.includes("RUSH") ? "error" : "default"}
            onClick={() => toggleMultiFilter("RUSH", enabledRush, setEnabledRush)}
          />
          <Chip
            label={`NON-RUSH ${enabledRush.includes("NON-RUSH") ? "✓" : ""}`}
            clickable
            color={enabledRush.includes("NON-RUSH") ? "success" : "default"}
            onClick={() => toggleMultiFilter("NON-RUSH", enabledRush, setEnabledRush)}
          />
          <Chip label="Reset" clickable variant="outlined" onClick={clearFilters} />
        </Stack>

        <Stack direction="row" spacing={0.9} sx={{ mt: 1, overflowX: "auto", pb: 0.4 }}>
          <Chip
            label={`ALL ${viewMode === "CHECKED" ? checkedCount : remainingCount}`}
            clickable
            color={alphaFilter === "ALL" ? "primary" : "default"}
            onClick={() => setAlphaFilter("ALL")}
            sx={{ height: 36, fontWeight: 800 }}
          />
          {ALPHA_LIST.map((letter) => {
            const count = alphaCounts[letter] || 0;
            return (
              <Chip
                key={letter}
                label={`${letter} ${count}`}
                clickable
                color={alphaFilter === letter ? "primary" : "default"}
                onClick={() => setAlphaFilter(letter)}
                sx={{ height: 36, fontWeight: 800 }}
              />
            );
          })}
        </Stack>
      </Box>

      <Box sx={{ px: 1.2, pt: 1 }}>
        {remainingCount === 1 && (
          <Alert severity="warning" sx={{ mb: 1 }}>
            Only 1 bag remains. Use "All Remaining" to quickly find it.
          </Alert>
        )}

        {alphaKeys.length === 0 ? (
          <Paper sx={{ p: 2, borderRadius: 2 }}>
            <Typography fontWeight={700}>No matching bags</Typography>
          </Paper>
        ) : (
          alphaKeys.map((alpha) => {
            const activeRows = groupedActive[alpha] || [];
            const checkedRows = groupedChecked[alpha] || [];
            const isExpanded = Boolean(checkedExpanded[alpha]);

            const showActive = viewMode === "ACTIVE" || viewMode === "BOTH";
            const showChecked = viewMode === "CHECKED" || viewMode === "BOTH";

            return (
              <Box key={alpha} sx={{ mb: 1.3 }}>
                <Paper sx={{ p: 1, borderRadius: 2, bgcolor: "#e5e7eb" }}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Chip size="small" label={alpha} color="primary" />
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        {activeRows.length} active
                      </Typography>
                      <Typography variant="body2" sx={{ color: "#4b5563", fontWeight: 700 }}>
                        {checkedRows.length} checked
                      </Typography>
                    </Stack>
                    {checkedRows.length > 0 && (
                      <Button
                        size="small"
                        color="inherit"
                        endIcon={isExpanded ? <ExpandLess /> : <ExpandMore />}
                        onClick={() => toggleCheckedExpand(alpha)}
                      >
                        Checked
                      </Button>
                    )}
                  </Stack>
                </Paper>

                <Stack spacing={0.9} sx={{ mt: 0.9 }}>
                  {showActive &&
                    activeRows.map((row) => {
                      const isRush = deriveRushType(row) === "RUSH";
                      const selected = selectedIds.includes(row.id);

                      return (
                        <Paper
                          key={row.id}
                          sx={{
                            p: 1.2,
                            borderRadius: 2,
                            border: selected ? "2px solid #0ea5e9" : "1px solid #d1d5db",
                          }}
                        >
                          <Stack spacing={0.8}>
                            <Stack direction="row" alignItems="center" justifyContent="space-between">
                              <Typography sx={{ fontSize: 20, fontWeight: 800 }}>{getName(row)}</Typography>
                              <Chip size="small" label={`#${row.id}`} />
                            </Stack>

                            <Typography sx={{ color: "#4b5563", fontWeight: 600 }}>
                              {formatMeasure(row)} • {formatDateOnly(row.date_clean)}
                            </Typography>

                            <Stack direction="row" spacing={0.8}>
                              <Chip size="small" label={row.service_type || "-"} color="warning" />
                              <Chip
                                size="small"
                                color={isRush ? "error" : "success"}
                                icon={isRush ? <FlashOn sx={{ fontSize: 14 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                                label={isRush ? "RUSH" : "NON-RUSH"}
                              />
                            </Stack>

                            <Stack direction="row" spacing={1}>
                              <Button
                                fullWidth
                                variant={selected ? "contained" : "outlined"}
                                onClick={() => toggleSelect(row.id)}
                              >
                                {selected ? "Selected" : "Select"}
                              </Button>
                              <Button fullWidth variant="contained" onClick={() => setConfirmOrder(row)}>
                                Checkout
                              </Button>
                            </Stack>
                          </Stack>
                        </Paper>
                      );
                    })}

                  {showChecked && isExpanded && checkedRows.length > 0 && (
                    <Paper sx={{ p: 1.1, borderRadius: 2, bgcolor: "#111827", color: "#f9fafb" }}>
                      <Typography sx={{ fontWeight: 700, mb: 1 }}>Checked Out</Typography>
                      <Stack spacing={0.6}>
                        {checkedRows.map((row) => (
                          <Box key={`${row.id}-${row.order_id}`}>
                            <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
                              <Box>
                                <Typography sx={{ fontWeight: 700 }}>
                                  {getName(row)} #{row.order_id}
                                </Typography>
                                <Typography sx={{ fontSize: 13, color: "#d1d5db" }}>
                                  {formatMeasure(row)} • {formatDateOnly(row.rush_date)}
                                </Typography>
                              </Box>
                              <Button
                                size="small"
                                variant="outlined"
                                color="inherit"
                                startIcon={<Undo />}
                                onClick={() => handleUndo(row.order_id)}
                              >
                                Undo
                              </Button>
                            </Stack>
                            <Divider sx={{ my: 0.7, borderColor: "#374151" }} />
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

      <Paper
        sx={{
          position: "fixed",
          left: 0,
          right: 0,
          bottom: 62,
          borderTop: "1px solid #d1d5db",
          p: 1,
          zIndex: 40,
        }}
      >
        <Typography sx={{ fontWeight: 800 }}>{remainingCount} remaining</Typography>
        <Typography variant="caption" color="text.secondary">
          {selectedVisibleIds.length} selected • Alpha {alphaFilter} • Employee {employee}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 0.8 }}>
          <Button fullWidth variant="outlined" onClick={() => setSelectedIds([])}>
            Clear
          </Button>
          <Button fullWidth variant="contained" disabled={busy || !selectedVisibleIds.length} onClick={handleCheckoutSelected}>
            Checkout Selected
          </Button>
        </Stack>
      </Paper>

      <Dialog open={Boolean(confirmOrder)} onClose={() => setConfirmOrder(null)} fullWidth maxWidth="xs">
        <DialogTitle>Confirm Checkout</DialogTitle>
        <DialogContent dividers>
          {confirmOrder && (
            <Stack spacing={1}>
              <Typography sx={{ fontSize: 22, fontWeight: 900 }}>{getName(confirmOrder)}</Typography>
              <Typography>{formatMeasure(confirmOrder)}</Typography>
              <Typography>Date: {formatDateOnly(confirmOrder.date_clean)}</Typography>
              <Typography>Employee: {employee}</Typography>
              <Alert severity="warning">Verify bag tag physically before confirming.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOrder(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={handleConfirmCheckout}>
            Confirm Checkout
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={2500}
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

export default CheckoutPage;
