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
  IconButton,
  InputAdornment,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  CheckCircle,
  ExpandLess,
  ExpandMore,
  FlashOn,
  Person,
  Search,
  Undo,
} from "@mui/icons-material";

import {
  checkoutBulk,
  checkoutOrder,
  getCheckoutLog,
  getOrders,
  undoCheckout,
} from "../api";

const ALPHAS = ["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

function CheckoutPage() {
  const [orders, setOrders] = useState([]);
  const [checkedLogs, setCheckedLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [search, setSearch] = useState("");
  const [employee, setEmployee] = useState("FrontDesk");
  const [serviceFilter, setServiceFilter] = useState("ALL");
  const [rushFilter, setRushFilter] = useState("ALL");
  const [alphaFilter, setAlphaFilter] = useState("ALL");

  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmOrder, setConfirmOrder] = useState(null);
  const [checkedDialogOpen, setCheckedDialogOpen] = useState(false);
  const [checkedExpanded, setCheckedExpanded] = useState({});

  const [snack, setSnack] = useState({
    open: false,
    severity: "success",
    message: "",
  });

  const showSnack = useCallback((severity, message) => {
    setSnack({ open: true, severity, message });
  }, []);

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
    if (Number.isNaN(date.getTime())) {
      return String(value).split(" ")[0];
    }
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const formatMeasure = (row) => {
    const service = String(row?.service_type || row?.service || "").toUpperCase();
    const rawWeight = Number(row?.weight_num ?? row?.weight ?? 0);

    if (service === "WF") {
      return `${rawWeight.toFixed(2)} lb`;
    }

    if (service === "HD") {
      return `${Math.round(rawWeight)} pcs`;
    }

    return rawWeight ? `${rawWeight}` : "-";
  };

  const activeFiltered = useMemo(() => {
    return orders.filter((row) => {
      const name = normalizeText(getName(row));
      const svc = String(row?.service_type || "").toUpperCase();
      const rush = String(row?.rush_type || "").toUpperCase();
      const alpha = getAlpha(row);
      const q = normalizeText(search);

      const matchSearch =
        !q ||
        name.includes(q) ||
        String(row?.id || "").includes(q) ||
        svc.toLowerCase().includes(q);
      const matchService = serviceFilter === "ALL" || svc === serviceFilter;
      const matchRush = rushFilter === "ALL" || rush === rushFilter;
      const matchAlpha = alphaFilter === "ALL" || alpha === alphaFilter;

      return matchSearch && matchService && matchRush && matchAlpha;
    });
  }, [orders, getName, getAlpha, search, serviceFilter, rushFilter, alphaFilter]);

  const checkedFiltered = useMemo(() => {
    return checkedLogs.filter((row) => {
      const name = normalizeText(getName(row));
      const svc = String(row?.service || "").toUpperCase();
      const alpha = getAlpha(row);
      const q = normalizeText(search);
      const isRush = row?.rush_date && new Date(row.rush_date) < new Date(new Date().toDateString());
      const rush = isRush ? "RUSH" : "NON-RUSH";

      const matchSearch =
        !q ||
        name.includes(q) ||
        String(row?.order_id || "").includes(q) ||
        svc.toLowerCase().includes(q);
      const matchService = serviceFilter === "ALL" || svc === serviceFilter;
      const matchRush = rushFilter === "ALL" || rush === rushFilter;
      const matchAlpha = alphaFilter === "ALL" || alpha === alphaFilter;

      return matchSearch && matchService && matchRush && matchAlpha;
    });
  }, [checkedLogs, getName, getAlpha, search, serviceFilter, rushFilter, alphaFilter]);

  const groupedActive = useMemo(() => {
    const groups = {};
    activeFiltered.forEach((row) => {
      const key = getAlpha(row);
      if (!groups[key]) groups[key] = [];
      groups[key].push(row);
    });
    return groups;
  }, [activeFiltered, getAlpha]);

  const groupedChecked = useMemo(() => {
    const groups = {};
    checkedFiltered.forEach((row) => {
      const key = getAlpha(row);
      if (!groups[key]) groups[key] = [];
      groups[key].push(row);
    });
    return groups;
  }, [checkedFiltered, getAlpha]);

  const alphaKeys = useMemo(() => {
    const keys = new Set([...Object.keys(groupedActive), ...Object.keys(groupedChecked)]);
    return Array.from(keys).sort((a, b) => {
      if (a === "#") return 1;
      if (b === "#") return -1;
      return a.localeCompare(b);
    });
  }, [groupedActive, groupedChecked]);

  const visibleIds = useMemo(() => activeFiltered.map((row) => row.id), [activeFiltered]);
  const selectedVisibleIds = useMemo(
    () => selectedIds.filter((id) => visibleIds.includes(id)),
    [selectedIds, visibleIds]
  );

  const remainingCount = activeFiltered.length;
  const checkedCount = checkedFiltered.length;

  const toggleSelect = (id) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const clearFilters = () => {
    setSearch("");
    setServiceFilter("ALL");
    setRushFilter("ALL");
    setAlphaFilter("ALL");
  };

  const toggleCheckedExpand = (alpha) => {
    setCheckedExpanded((prev) => ({ ...prev, [alpha]: !prev[alpha] }));
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
    <Box
      sx={{
        minHeight: "100vh",
        background: "#f3f4f6",
        pb: 16,
      }}
    >
      <Box
        sx={{
          position: "sticky",
          top: 0,
          zIndex: 20,
          background: "#f3f4f6",
          borderBottom: "1px solid #d1d5db",
          px: 1.5,
          pt: 1,
          pb: 1.2,
        }}
      >
        <Typography sx={{ fontSize: 28, fontWeight: 800, lineHeight: 1.1 }}>Checkout</Typography>
        <Typography sx={{ color: "#16a34a", fontWeight: 700, mt: 0.5 }}>
          {remainingCount} bags remaining
        </Typography>

        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <Chip label={`${checkedCount} checked`} size="small" />
          <Chip
            label="See All Checked"
            size="small"
            color="warning"
            onClick={() => setCheckedDialogOpen(true)}
            clickable
          />
        </Stack>

        <Stack spacing={1} sx={{ mt: 1.2 }}>
          <TextField
            size="small"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or id"
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

        <Stack direction="row" spacing={1} sx={{ mt: 1.2, overflowX: "auto", pb: 0.4 }}>
          {["ALL", "WF", "HD"].map((svc) => (
            <Chip
              key={svc}
              label={svc}
              clickable
              color={serviceFilter === svc ? "warning" : "default"}
              onClick={() => setServiceFilter(svc)}
            />
          ))}
          {["ALL", "RUSH", "NON-RUSH"].map((r) => (
            <Chip
              key={r}
              label={r}
              clickable
              color={rushFilter === r ? "error" : "default"}
              onClick={() => setRushFilter(r)}
            />
          ))}
        </Stack>

        <Stack direction="row" spacing={0.7} sx={{ mt: 1, overflowX: "auto", pb: 0.2 }}>
          {ALPHAS.map((letter) => (
            <Chip
              key={letter}
              size="small"
              label={letter}
              clickable
              color={alphaFilter === letter ? "primary" : "default"}
              onClick={() => setAlphaFilter(letter)}
            />
          ))}
        </Stack>
      </Box>

      <Box sx={{ maxWidth: 560, mx: "auto", px: 1.2, pt: 1.2 }}>
        {alphaKeys.length === 0 ? (
          <Paper sx={{ p: 2.5, borderRadius: 2 }}>
            <Typography fontWeight={700}>No matching bags</Typography>
            <Button sx={{ mt: 1 }} onClick={clearFilters}>
              Clear filters
            </Button>
          </Paper>
        ) : (
          alphaKeys.map((alpha) => {
            const activeRows = groupedActive[alpha] || [];
            const checkedRows = groupedChecked[alpha] || [];
            const expanded = Boolean(checkedExpanded[alpha]);

            return (
              <Box key={alpha} sx={{ mb: 1.5 }}>
                <Paper sx={{ p: 1.2, borderRadius: 2, bgcolor: "#e5e7eb" }}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Stack direction="row" alignItems="center" spacing={1}>
                      <Chip size="small" color="primary" label={alpha} />
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        {activeRows.length} remaining
                      </Typography>
                    </Stack>
                    {checkedRows.length > 0 && (
                      <Button
                        size="small"
                        color="inherit"
                        onClick={() => toggleCheckedExpand(alpha)}
                        endIcon={expanded ? <ExpandLess /> : <ExpandMore />}
                      >
                        {checkedRows.length} checked
                      </Button>
                    )}
                  </Stack>
                </Paper>

                <Stack spacing={1} sx={{ mt: 1 }}>
                  {activeRows.map((row) => {
                    const isRush = String(row?.rush_type || "").toUpperCase() === "RUSH";
                    const selected = selectedIds.includes(row.id);

                    return (
                      <Paper
                        key={row.id}
                        sx={{
                          p: 1.4,
                          borderRadius: 2,
                          border: selected ? "2px solid #0ea5e9" : "1px solid #d1d5db",
                        }}
                      >
                        <Stack spacing={1}>
                          <Stack direction="row" alignItems="center" justifyContent="space-between">
                            <Typography sx={{ fontWeight: 800, fontSize: 20 }}>{getName(row)}</Typography>
                            <Chip label={`#${row.id}`} size="small" />
                          </Stack>

                          <Typography sx={{ color: "#4b5563", fontWeight: 600 }}>
                            {formatMeasure(row)} • {formatDateOnly(row.date_clean)}
                          </Typography>

                          <Stack direction="row" spacing={1}>
                            <Chip label={row.service_type || "-"} size="small" color="warning" />
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

                  {expanded && checkedRows.length > 0 && (
                    <Paper sx={{ p: 1.2, borderRadius: 2, bgcolor: "#111827", color: "#f9fafb" }}>
                      <Typography sx={{ fontWeight: 700, mb: 1 }}>Checked Out ({checkedRows.length})</Typography>
                      <Stack spacing={0.8}>
                        {checkedRows.map((row) => (
                          <Box key={`${alpha}-${row.order_id}-${row.id}`}>
                            <Stack direction="row" alignItems="center" justifyContent="space-between">
                              <Box>
                                <Typography sx={{ fontWeight: 700 }}>
                                  {getName(row)} #{row.order_id}
                                </Typography>
                                <Typography sx={{ color: "#d1d5db", fontSize: 13 }}>
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
                            <Divider sx={{ my: 0.8, borderColor: "#374151" }} />
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
          bottom: 0,
          borderTopLeftRadius: 16,
          borderTopRightRadius: 16,
          borderTop: "1px solid #d1d5db",
          p: 1.2,
          zIndex: 30,
        }}
      >
        <Typography sx={{ fontWeight: 700 }}>{remainingCount} remaining</Typography>
        <Typography variant="caption" color="text.secondary">
          {selectedVisibleIds.length} selected • Employee: {employee}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <Button fullWidth variant="outlined" onClick={() => setSelectedIds([])}>
            Clear
          </Button>
          <Button
            fullWidth
            variant="contained"
            disabled={busy || !selectedVisibleIds.length}
            onClick={handleCheckoutSelected}
          >
            Checkout Selected
          </Button>
        </Stack>
      </Paper>

      <Dialog open={Boolean(confirmOrder)} onClose={() => setConfirmOrder(null)} fullWidth maxWidth="xs">
        <DialogTitle>Confirm Checkout</DialogTitle>
        <DialogContent dividers>
          {confirmOrder && (
            <Stack spacing={1}>
              <Typography sx={{ fontWeight: 800, fontSize: 22 }}>{getName(confirmOrder)}</Typography>
              <Typography>{formatMeasure(confirmOrder)}</Typography>
              <Typography>Date: {formatDateOnly(confirmOrder.date_clean)}</Typography>
              <Typography>Employee: {employee}</Typography>
              <Alert severity="warning">Please verify physical tag before final checkout.</Alert>
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

      <Dialog open={checkedDialogOpen} onClose={() => setCheckedDialogOpen(false)} fullWidth>
        <DialogTitle>All Checked Out Bags ({checkedFiltered.length})</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1}>
            {checkedFiltered.map((row) => (
              <Paper key={`all-${row.id}-${row.order_id}`} sx={{ p: 1.2, borderRadius: 2 }}>
                <Stack direction="row" alignItems="center" justifyContent="space-between">
                  <Box>
                    <Typography sx={{ fontWeight: 700 }}>
                      {getName(row)} #{row.order_id}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {row.service} • {formatMeasure(row)} • {formatDateOnly(row.rush_date)}
                    </Typography>
                  </Box>
                  <Button size="small" startIcon={<Undo />} onClick={() => handleUndo(row.order_id)}>
                    Undo
                  </Button>
                </Stack>
              </Paper>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCheckedDialogOpen(false)}>Done</Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={2400}
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
