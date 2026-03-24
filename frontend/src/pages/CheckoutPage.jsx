import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Box,
  Typography,
  TextField,
  InputAdornment,
  Chip,
  Card,
  CardContent,
  Button,
  IconButton,
  Checkbox,
  Stack,
  Divider,
  Paper,
  Snackbar,
  Alert,
  CircularProgress,
  Fab,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  BottomNavigation,
  BottomNavigationAction,
} from "@mui/material";
import {
  Search,
  LocalLaundryService,
  FlashOn,
  CheckCircle,
  Inventory2,
  FilterList,
  Person,
  DoneAll,
  Clear,
} from "@mui/icons-material";

import { getOrders, checkoutOrder, checkoutBulk } from "../api";
import TaOperationalBanner from "../components/TaOperationalBanner";
import { useTaOperationalGate } from "../hooks/useTaOperationalGate";

const MotionCard = motion(Card);

const ALPHAS = ["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

function CheckoutPage() {
  const {
    checkoutBlocked,
    assertCanCheckout,
    bannerMessage,
  } = useTaOperationalGate();

  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [serviceFilter, setServiceFilter] = useState("ALL");
  const [rushFilter, setRushFilter] = useState("ALL");
  const [alphaFilter, setAlphaFilter] = useState("ALL");

  const [selectedIds, setSelectedIds] = useState([]);
  const [employee, setEmployee] = useState("FrontDesk");

  const [quickDialogOpen, setQuickDialogOpen] = useState(false);
  const [activeOrder, setActiveOrder] = useState(null);
  const [processingSingleId, setProcessingSingleId] = useState(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  const [snack, setSnack] = useState({
    open: false,
    severity: "success",
    message: "",
  });

  useEffect(() => {
    loadOrders();
  }, []);

  async function loadOrders() {
    try {
      setLoading(true);
      const res = await getOrders();
      setOrders(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      showSnack("error", "Could not load checkout orders.");
    } finally {
      setLoading(false);
    }
  }

  function showSnack(severity, message) {
    setSnack({
      open: true,
      severity,
      message,
    });
  }

  function normalizeText(value) {
    return String(value || "").trim().toLowerCase();
  }

  function getOrderName(order) {
    return String(order?.name_clean || "").trim();
  }

  function getAlpha(order) {
    const first = getOrderName(order).charAt(0).toUpperCase();
    return /^[A-Z]$/.test(first) ? first : "#";
  }

  const filteredOrders = useMemo(() => {
    return orders.filter((order) => {
      const name = normalizeText(order.name_clean);
      const searchValue = normalizeText(search);

      const matchesSearch =
        !searchValue ||
        name.includes(searchValue) ||
        String(order.id || "").includes(searchValue) ||
        normalizeText(order.service_type).includes(searchValue) ||
        normalizeText(order.rush_type).includes(searchValue);

      const matchesService =
        serviceFilter === "ALL" || order.service_type === serviceFilter;

      const matchesRush =
        rushFilter === "ALL" || order.rush_type === rushFilter;

      const matchesAlpha =
        alphaFilter === "ALL" || getAlpha(order) === alphaFilter;

      return matchesSearch && matchesService && matchesRush && matchesAlpha;
    });
  }, [orders, search, serviceFilter, rushFilter, alphaFilter]);

  const groupedOrders = useMemo(() => {
    const groups = {};

    filteredOrders.forEach((order) => {
      const alpha = getAlpha(order);
      if (!groups[alpha]) groups[alpha] = [];
      groups[alpha].push(order);
    });

    const sortedKeys = Object.keys(groups).sort((a, b) => {
      if (a === "#") return 1;
      if (b === "#") return -1;
      return a.localeCompare(b);
    });

    return sortedKeys.map((key) => ({
      alpha: key,
      items: groups[key].sort((a, b) =>
        getOrderName(a).localeCompare(getOrderName(b))
      ),
    }));
  }, [filteredOrders]);

  const visibleIds = useMemo(
    () => filteredOrders.map((order) => order.id),
    [filteredOrders]
  );

  const selectedVisibleIds = useMemo(
    () => selectedIds.filter((id) => visibleIds.includes(id)),
    [selectedIds, visibleIds]
  );

  const selectedCount = selectedVisibleIds.length;
  const totalVisible = visibleIds.length;

  function isSelected(orderId) {
    return selectedIds.includes(orderId);
  }

  function toggleSelect(orderId) {
    setSelectedIds((prev) =>
      prev.includes(orderId)
        ? prev.filter((id) => id !== orderId)
        : [...prev, orderId]
    );
  }

  function selectAllVisible() {
    setSelectedIds((prev) => {
      const merged = new Set([...prev, ...visibleIds]);
      return Array.from(merged);
    });
  }

  function clearVisibleSelection() {
    setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
  }

  function clearAllFilters() {
    setSearch("");
    setServiceFilter("ALL");
    setRushFilter("ALL");
    setAlphaFilter("ALL");
  }

  function openQuickCheckout(order) {
    setActiveOrder(order);
    setQuickDialogOpen(true);
  }

  function closeQuickCheckout() {
    setQuickDialogOpen(false);
    setActiveOrder(null);
  }

  async function handleSingleCheckout(order) {
    const gate = await assertCanCheckout();
    if (!gate.ok) {
      const detail = gate.reasons?.length ? gate.reasons.join(", ") : "Time & attendance rules not met.";
      showSnack("error", `Checkout blocked: ${detail}`);
      return;
    }
    try {
      setProcessingSingleId(order.id);
      await checkoutOrder(order.id, employee);

      setOrders((prev) => prev.filter((item) => item.id !== order.id));
      setSelectedIds((prev) => prev.filter((id) => id !== order.id));

      closeQuickCheckout();
      showSnack("success", `${getOrderName(order)} checked out.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Single checkout failed.");
    } finally {
      setProcessingSingleId(null);
    }
  }

  async function handleBulkCheckout(ids) {
    if (!ids.length) {
      showSnack("warning", "No bags selected.");
      return;
    }

    const gate = await assertCanCheckout();
    if (!gate.ok) {
      const detail = gate.reasons?.length ? gate.reasons.join(", ") : "Time & attendance rules not met.";
      showSnack("error", `Checkout blocked: ${detail}`);
      return;
    }

    try {
      setBulkLoading(true);
      await checkoutBulk(ids, employee);

      const idSet = new Set(ids);
      setOrders((prev) => prev.filter((item) => !idSet.has(item.id)));
      setSelectedIds((prev) => prev.filter((id) => !idSet.has(id)));

      showSnack("success", `${ids.length} bag(s) checked out.`);
    } catch (error) {
      console.error(error);
      showSnack("error", "Bulk checkout failed.");
    } finally {
      setBulkLoading(false);
    }
  }

  function serviceColor(service) {
    if (service === "WF") return "primary";
    if (service === "HD") return "warning";
    return "default";
  }

  function rushChipProps(rushType) {
    if (rushType === "RUSH") {
      return {
        label: "RUSH",
        color: "error",
        icon: <FlashOn sx={{ fontSize: 16 }} />,
      };
    }

    return {
      label: "NON-RUSH",
      color: "success",
      icon: <CheckCircle sx={{ fontSize: 16 }} />,
    };
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "#f5f7fb",
        pb: selectedCount > 0 || totalVisible > 0 ? 14 : 6,
      }}
    >
      <Box sx={{ px: 2, pt: 2, maxWidth: 1200, mx: "auto" }}>
        <TaOperationalBanner message={bannerMessage} />
      </Box>
      <Box
        sx={{
          position: "sticky",
          top: 0,
          zIndex: 40,
          bgcolor: "rgba(245,247,251,0.92)",
          backdropFilter: "blur(10px)",
          borderBottom: "1px solid rgba(15,23,42,0.06)",
        }}
      >
        <Box sx={{ px: 2, pt: 2, pb: 1.5 }}>
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            spacing={1}
            sx={{ mb: 1.5 }}
          >
            <Box>
              <Typography variant="h5" sx={{ fontWeight: 800, lineHeight: 1.1 }}>
                Checkout
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {loading ? "Loading..." : `${totalVisible} visible bag(s)`}
              </Typography>
            </Box>

            <Chip
              icon={<Inventory2 />}
              label={`${orders.length} active`}
              variant="outlined"
              sx={{ fontWeight: 700, borderRadius: 999 }}
            />
          </Stack>

          <Stack spacing={1.25}>
            <TextField
              fullWidth
              size="small"
              placeholder="Search by name, service, rush, or id"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              sx={{
                "& .MuiOutlinedInput-root": {
                  bgcolor: "white",
                  borderRadius: 3,
                },
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search fontSize="small" />
                  </InputAdornment>
                ),
                endAdornment: search ? (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setSearch("")}>
                      <Clear fontSize="small" />
                    </IconButton>
                  </InputAdornment>
                ) : null,
              }}
            />

            <TextField
              fullWidth
              size="small"
              placeholder="Employee name"
              value={employee}
              onChange={(e) => setEmployee(e.target.value)}
              sx={{
                "& .MuiOutlinedInput-root": {
                  bgcolor: "white",
                  borderRadius: 3,
                },
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Person fontSize="small" />
                  </InputAdornment>
                ),
              }}
            />
          </Stack>
        </Box>

        <Box sx={{ px: 2, pb: 1 }}>
          <Stack spacing={1}>
            <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
              Service
            </Typography>
            <Stack direction="row" spacing={1} sx={{ overflowX: "auto", pb: 0.5 }}>
              {["ALL", "WF", "HD"].map((item) => (
                <Chip
                  key={item}
                  label={item}
                  color={serviceFilter === item ? "primary" : "default"}
                  variant={serviceFilter === item ? "filled" : "outlined"}
                  onClick={() => setServiceFilter(item)}
                  sx={{ borderRadius: 999, fontWeight: 700 }}
                />
              ))}
            </Stack>

            <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
              Delivery
            </Typography>
            <Stack direction="row" spacing={1} sx={{ overflowX: "auto", pb: 0.5 }}>
              {["ALL", "RUSH", "NON-RUSH"].map((item) => (
                <Chip
                  key={item}
                  label={item}
                  color={rushFilter === item ? "secondary" : "default"}
                  variant={rushFilter === item ? "filled" : "outlined"}
                  onClick={() => setRushFilter(item)}
                  sx={{ borderRadius: 999, fontWeight: 700 }}
                />
              ))}
            </Stack>

            <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
              Alphabet
            </Typography>
            <Box
              sx={{
                display: "flex",
                gap: 0.75,
                overflowX: "auto",
                pb: 0.5,
              }}
            >
              {ALPHAS.map((letter) => (
                <Chip
                  key={letter}
                  label={letter}
                  size="small"
                  clickable
                  color={alphaFilter === letter ? "primary" : "default"}
                  variant={alphaFilter === letter ? "filled" : "outlined"}
                  onClick={() => setAlphaFilter(letter)}
                  sx={{
                    minWidth: letter === "ALL" ? 52 : 34,
                    borderRadius: 999,
                    fontWeight: 800,
                  }}
                />
              ))}
            </Box>

            <Stack direction="row" spacing={1} sx={{ pt: 0.25 }}>
              <Button
                size="small"
                variant="text"
                startIcon={<FilterList />}
                onClick={clearAllFilters}
              >
                Clear filters
              </Button>

              <Button
                size="small"
                variant="text"
                startIcon={<DoneAll />}
                onClick={selectAllVisible}
                disabled={!visibleIds.length}
              >
                Select visible
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Box>

      <Box sx={{ px: 2, pt: 2 }}>
        {loading ? (
          <Stack alignItems="center" justifyContent="center" sx={{ py: 10 }} spacing={2}>
            <CircularProgress />
            <Typography color="text.secondary">Loading checkout bags...</Typography>
          </Stack>
        ) : groupedOrders.length === 0 ? (
          <Paper
            elevation={0}
            sx={{
              p: 3,
              borderRadius: 4,
              textAlign: "center",
              bgcolor: "white",
              border: "1px solid rgba(15,23,42,0.06)",
            }}
          >
            <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
              No bags found
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              Try adjusting search or filters.
            </Typography>
            <Button variant="contained" onClick={clearAllFilters}>
              Reset filters
            </Button>
          </Paper>
        ) : (
          <Stack spacing={2.5}>
            {groupedOrders.map((group) => (
              <Box key={group.alpha}>
                <Stack
                  direction="row"
                  alignItems="center"
                  spacing={1}
                  sx={{ mb: 1.25 }}
                >
                  <Chip
                    label={group.alpha}
                    color="primary"
                    sx={{ fontWeight: 800, borderRadius: 2 }}
                  />
                  <Typography variant="body2" color="text.secondary">
                    {group.items.length} bag(s)
                  </Typography>
                </Stack>

                <Stack spacing={1.25}>
                  <AnimatePresence>
                    {group.items.map((order) => {
                      const selected = isSelected(order.id);
                      const rushProps = rushChipProps(order.rush_type);

                      return (
                        <MotionCard
                          key={order.id}
                          layout
                          initial={{ opacity: 0, y: 12 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, scale: 0.96 }}
                          whileTap={{ scale: 0.985 }}
                          elevation={0}
                          sx={{
                            borderRadius: 4,
                            border: selected
                              ? "2px solid"
                              : "1px solid rgba(15,23,42,0.08)",
                            borderColor: selected ? "primary.main" : "rgba(15,23,42,0.08)",
                            bgcolor: "white",
                            overflow: "hidden",
                          }}
                        >
                          <CardContent sx={{ p: 1.5 }}>
                            <Stack direction="row" spacing={1.25} alignItems="flex-start">
                              <Checkbox
                                checked={selected}
                                onChange={() => toggleSelect(order.id)}
                                sx={{ mt: -0.5, ml: -0.5 }}
                              />

                              <Box sx={{ flex: 1, minWidth: 0 }}>
                                <Stack
                                  direction="row"
                                  alignItems="center"
                                  justifyContent="space-between"
                                  spacing={1}
                                >
                                  <Typography
                                    variant="subtitle1"
                                    sx={{
                                      fontWeight: 800,
                                      lineHeight: 1.15,
                                      wordBreak: "break-word",
                                    }}
                                  >
                                    {order.name_clean || "Unnamed"}
                                  </Typography>

                                  <Chip
                                    size="small"
                                    label={`#${order.id}`}
                                    variant="outlined"
                                    sx={{ borderRadius: 999, fontWeight: 700 }}
                                  />
                                </Stack>

                                <Typography
                                  variant="body2"
                                  color="text.secondary"
                                  sx={{ mt: 0.5, mb: 1.25 }}
                                >
                                  {order.weight_num ? `${order.weight_num} lb` : "No weight"}
                                  {order.date_clean ? ` • Due ${order.date_clean}` : ""}
                                </Typography>

                                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                  <Chip
                                    size="small"
                                    label={order.service_type || "N/A"}
                                    color={serviceColor(order.service_type)}
                                    icon={<LocalLaundryService sx={{ fontSize: 16 }} />}
                                    sx={{ fontWeight: 700, borderRadius: 999 }}
                                  />

                                  <Chip
                                    size="small"
                                    label={rushProps.label}
                                    color={rushProps.color}
                                    icon={rushProps.icon}
                                    sx={{ fontWeight: 700, borderRadius: 999 }}
                                  />

                                  {order.status && (
                                    <Chip
                                      size="small"
                                      label={order.status}
                                      variant="outlined"
                                      sx={{ fontWeight: 700, borderRadius: 999 }}
                                    />
                                  )}
                                </Stack>

                                <Divider sx={{ my: 1.5 }} />

                                <Stack direction="row" spacing={1}>
                                  <Button
                                    fullWidth
                                    variant="outlined"
                                    onClick={() => toggleSelect(order.id)}
                                    sx={{ borderRadius: 3, fontWeight: 800 }}
                                  >
                                    {selected ? "Selected" : "Select"}
                                  </Button>

                                  <Button
                                    fullWidth
                                    variant="contained"
                                    onClick={() => openQuickCheckout(order)}
                                    disabled={checkoutBlocked || processingSingleId === order.id}
                                    sx={{
                                      borderRadius: 3,
                                      fontWeight: 800,
                                      boxShadow: "none",
                                    }}
                                  >
                                    Checkout
                                  </Button>
                                </Stack>
                              </Box>
                            </Stack>
                          </CardContent>
                        </MotionCard>
                      );
                    })}
                  </AnimatePresence>
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
      </Box>

      {totalVisible > 0 && (
        <Fab
          color="primary"
          variant="extended"
          onClick={() => handleBulkCheckout(visibleIds)}
          disabled={checkoutBlocked || bulkLoading}
          sx={{
            position: "fixed",
            right: 16,
            bottom: selectedCount > 0 ? 98 : 20,
            zIndex: 60,
            borderRadius: 999,
            fontWeight: 800,
          }}
        >
          <DoneAll sx={{ mr: 1 }} />
          {bulkLoading ? "Processing..." : "Checkout All Visible"}
        </Fab>
      )}

      <AnimatePresence>
        {(selectedCount > 0 || totalVisible > 0) && (
          <motion.div
            initial={{ y: 120 }}
            animate={{ y: 0 }}
            exit={{ y: 120 }}
            transition={{ type: "spring", stiffness: 240, damping: 24 }}
            style={{
              position: "fixed",
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 70,
            }}
          >
            <Paper
              elevation={8}
              sx={{
                borderTopLeftRadius: 18,
                borderTopRightRadius: 18,
                px: 1,
                pt: 1,
                pb: 1.25,
                borderTop: "1px solid rgba(15,23,42,0.08)",
              }}
            >
              <Box sx={{ px: 1.25, pb: 0.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                  {selectedCount > 0
                    ? `${selectedCount} selected`
                    : `${totalVisible} visible`}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Employee: {employee || "Not set"}
                </Typography>
              </Box>

              <BottomNavigation showLabels sx={{ bgcolor: "transparent" }}>
                <BottomNavigationAction
                  label="Clear"
                  icon={<Clear />}
                  onClick={clearVisibleSelection}
                  disabled={!selectedCount}
                />
                <BottomNavigationAction
                  label="Select All"
                  icon={<DoneAll />}
                  onClick={selectAllVisible}
                  disabled={!totalVisible}
                />
                <BottomNavigationAction
                  label="Checkout Selected"
                  icon={<CheckCircle />}
                  onClick={() => handleBulkCheckout(selectedVisibleIds)}
                  disabled={checkoutBlocked || !selectedCount || bulkLoading}
                />
              </BottomNavigation>
            </Paper>
          </motion.div>
        )}
      </AnimatePresence>

      <Dialog
        open={quickDialogOpen}
        onClose={closeQuickCheckout}
        fullWidth
        maxWidth="xs"
        PaperProps={{
          sx: {
            borderRadius: 4,
          },
        }}
      >
        <DialogTitle sx={{ fontWeight: 800 }}>Confirm Checkout</DialogTitle>

        <DialogContent dividers>
          {activeOrder && (
            <Stack spacing={1.25}>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>
                {activeOrder.name_clean}
              </Typography>

              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  label={activeOrder.service_type || "N/A"}
                  color={serviceColor(activeOrder.service_type)}
                  sx={{ fontWeight: 700, borderRadius: 999 }}
                />
                <Chip
                  label={activeOrder.rush_type || "N/A"}
                  color={activeOrder.rush_type === "RUSH" ? "error" : "success"}
                  sx={{ fontWeight: 700, borderRadius: 999 }}
                />
              </Stack>

              <Typography color="text.secondary">
                Weight: {activeOrder.weight_num ? `${activeOrder.weight_num} lb` : "No weight"}
              </Typography>

              <Typography color="text.secondary">
                Employee: {employee || "Not set"}
              </Typography>
            </Stack>
          )}
        </DialogContent>

        <DialogActions sx={{ p: 2 }}>
          <Button onClick={closeQuickCheckout} variant="outlined" sx={{ borderRadius: 3 }}>
            Cancel
          </Button>
          <Button
            onClick={() => activeOrder && handleSingleCheckout(activeOrder)}
            variant="contained"
            disabled={checkoutBlocked || !activeOrder || processingSingleId === activeOrder.id}
            sx={{ borderRadius: 3, fontWeight: 800 }}
          >
            {processingSingleId === activeOrder?.id ? "Processing..." : "Checkout"}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={2600}
        onClose={() => setSnack((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={snack.severity}
          variant="filled"
          onClose={() => setSnack((prev) => ({ ...prev, open: false }))}
          sx={{ width: "100%" }}
        >
          {snack.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

export default CheckoutPage;