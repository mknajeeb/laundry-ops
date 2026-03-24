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
  Stack,
  Typography,
} from "@mui/material";
import { Bolt, CheckCircle, LocalShipping, Refresh, Undo } from "@mui/icons-material";
import { checkoutOrder, getCheckoutLog, getOrders, undoCheckout } from "../api";
import TaOperationalBanner from "../components/TaOperationalBanner";
import { useTaOperationalGate } from "../hooks/useTaOperationalGate";

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

  const [rows, setRows] = useState([]);
  const [checkedRows, setCheckedRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [rushTab, setRushTab] = useState("RUSH");
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
    const raw = normalizeCode(r?.rush_type);
    return raw === "RUSH" ? "RUSH" : "NON-RUSH";
  };
  const serviceOf = (r) => normalizeCode(r?.service_type);
  const isHD = (r) => serviceOf(r) === "HD";
  const measureOf = (r) => {
    const n = Number(r?.weight_num ?? r?.weight ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };
  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const normalizeName = (value) => String(value || "").trim().toLowerCase();

  const queues = useMemo(() => {
    const rushRows = rows.filter((r) => rushOf(r) === "RUSH");
    const nonRushRows = rows.filter((r) => rushOf(r) === "NON-RUSH");
    return {
      RUSH: {
        WF: rushRows.filter((r) => serviceOf(r) === "WF"),
        HD: rushRows.filter((r) => serviceOf(r) === "HD"),
      },
      "NON-RUSH": {
        WF: nonRushRows.filter((r) => serviceOf(r) === "WF"),
        HD: nonRushRows.filter((r) => serviceOf(r) === "HD"),
      },
    };
  }, [rows]);

  const counters = useMemo(() => {
    const rushCount = queues.RUSH.WF.length + queues.RUSH.HD.length;
    const nonRushCount = queues["NON-RUSH"].WF.length + queues["NON-RUSH"].HD.length;
    return {
      rushCount,
      nonRushCount,
      sentCount: checkedRows.length,
    };
  }, [queues, checkedRows.length]);

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
    const sameName = rows.filter((r) => normalizeName(r?.name_clean) === key);
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
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 30, fontWeight: 500 }}>Checkout</Typography>
        <Button size="small" variant="text" startIcon={<Refresh />} onClick={load}>
          Refresh
        </Button>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
        <Button
          fullWidth
          onClick={() => setRushTab("RUSH")}
          sx={{
            textTransform: "none",
            borderRadius: 2,
            py: 0.8,
            bgcolor: rushTab === "RUSH" ? "#b91c1c" : "#f1f5f9",
            color: rushTab === "RUSH" ? "#ffffff" : "#111827",
            opacity: counters.rushCount === 0 ? 0.45 : 1,
          }}
          startIcon={<Bolt />}
        >
          RUSH {counters.rushCount}
        </Button>
        <Button
          fullWidth
          onClick={() => setRushTab("NON-RUSH")}
          sx={{
            textTransform: "none",
            borderRadius: 2,
            py: 0.8,
            bgcolor: rushTab === "NON-RUSH" ? "#0f766e" : "#f1f5f9",
            color: rushTab === "NON-RUSH" ? "#ffffff" : "#111827",
            opacity: counters.nonRushCount === 0 ? 0.45 : 1,
          }}
          startIcon={<CheckCircle />}
        >
          NON-RUSH {counters.nonRushCount}
        </Button>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 0.8, overflowX: "auto", pb: 0.2 }}>
        <Chip label={`Sent to Rinse ${counters.sentCount}`} />
        {rushTab === "RUSH" && counters.rushCount === 0 && <Chip color="success" label="Rush queue empty" />}
      </Stack>

      {rushTab === "RUSH" && counters.rushCount === 0 && (
        <Alert sx={{ mt: 1 }} severity="success">
          All rush bags are checked out.
        </Alert>
      )}

      <Stack spacing={1.2} sx={{ mt: 1.2 }}>
        {["WF", "HD"].map((svc) => {
          const list = queues[rushTab][svc];
          const isSvcHD = svc === "HD";
          return (
            <Paper
              key={svc}
              sx={{
                borderRadius: 2,
                border: "1px solid #e5e7eb",
                p: 1.1,
                opacity: list.length === 0 ? 0.45 : 1,
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.8 }}>
                <Typography sx={{ fontSize: 18, fontWeight: 500 }}>
                  {svc} • {list.length} bags
                </Typography>
              </Stack>
              {list.length === 0 ? (
                <Typography sx={{ color: "#6b7280" }}>No bags in this queue.</Typography>
              ) : (
                <Stack spacing={0.9}>
                  {list.map((r) => (
                    <Paper
                      key={r.id}
                      onClick={() => !checkoutBlocked && onSelectForCheckout(r)}
                      sx={{
                        p: 1.1,
                        borderRadius: 2,
                        cursor: checkoutBlocked ? "not-allowed" : "pointer",
                        opacity: checkoutBlocked ? 0.45 : 1,
                        bgcolor: isSvcHD ? "#0097b2" : "#0b1324",
                        border: isSvcHD ? "1px solid #52d4e4" : "1px solid #1f2d4a",
                        color: "#ffffff",
                      }}
                    >
                      <Stack spacing={0.6}>
                        <Typography sx={{ fontSize: 21, fontWeight: 500 }}>{r.name_clean}</Typography>
                        <Typography sx={{ opacity: 0.95 }}>{formatDate(r.date_clean)} • {measureOf(r)}</Typography>
                        <Stack direction="row" spacing={0.8}>
                          <Chip size="small" label={svc} sx={{ bgcolor: "#ffffff", color: "#111827" }} />
                          <Chip
                            size="small"
                            label={rushTab}
                            icon={rushTab === "RUSH" ? <Bolt sx={{ fontSize: 15 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                            sx={{ bgcolor: "#ffffff", color: "#111827" }}
                          />
                        </Stack>
                      </Stack>
                    </Paper>
                  ))}
                </Stack>
              )}
            </Paper>
          );
        })}
      </Stack>

      <Paper sx={{ mt: 1.2, p: 1.1, borderRadius: 2, border: "1px solid #e5e7eb" }}>
        <Typography sx={{ fontSize: 15, color: "#4b5563", mb: 0.7 }}>Recent sent items</Typography>
        <Stack spacing={0.8}>
          {checkedRows.slice(0, 8).map((r) => (
            <Stack
              key={`${r.id}-${r.order_id}`}
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ p: 0.7, border: "1px solid #edf2f7", borderRadius: 1.2 }}
            >
              <Typography sx={{ fontSize: 14 }}>{r.name || `#${r.order_id}`}</Typography>
              <Button size="small" variant="text" onClick={() => setUndoRow(r)} startIcon={<Undo />}>
                Undo
              </Button>
            </Stack>
          ))}
          {checkedRows.length === 0 && <Typography sx={{ color: "#6b7280" }}>No checked out bags yet.</Typography>}
        </Stack>
      </Paper>

      <Dialog open={Boolean(activeRow)} onClose={() => setActiveRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Send to Rinse</DialogTitle>
        <DialogContent dividers>
          {activeRow && (
            <Stack spacing={1}>
              <Typography sx={{ fontSize: 21 }}>{activeRow.name_clean}</Typography>
              <Typography>{formatDate(activeRow.date_clean)} • {measureOf(activeRow)}</Typography>
              <Alert severity="warning">Confirm physical tag before sending.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActiveRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={checkoutBlocked || busy}
            startIcon={<LocalShipping />}
            onClick={confirmCheckout}
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
                    <span>{formatDate(opt.date_clean)} • {measureOf(opt)}</span>
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
              <Typography>Move this bag back to Washpro queue.</Typography>
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
