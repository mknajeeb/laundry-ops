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

function CheckoutPage() {
  const [rows, setRows] = useState([]);
  const [checkedRows, setCheckedRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [rushTab, setRushTab] = useState("RUSH");
  const [activeRow, setActiveRow] = useState(null);
  const [undoRow, setUndoRow] = useState(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [ordersRes, checkedRes] = await Promise.all([
        getOrders({ include_all: true }),
        getCheckoutLog(),
      ]);
      const allRows = Array.isArray(ordersRes.data) ? ordersRes.data : [];
      const active = allRows.filter((r) => {
        const l = String(r?.logistics_status || r?.status || "").toUpperCase();
        return !["SENT_TO_RINSE", "CHECKED_OUT", "FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(l);
      });
      setRows(active);
      setCheckedRows(Array.isArray(checkedRes.data) ? checkedRes.data : []);
    } catch (error) {
      console.error(error);
      setRows([]);
      setCheckedRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rushOf = (r) => {
    const raw = String(r?.rush_type || "").toUpperCase();
    return raw === "RUSH" ? "RUSH" : "NON-RUSH";
  };
  const serviceOf = (r) => String(r?.service_type || "").toUpperCase();
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
                      onClick={() => setActiveRow(r)}
                      sx={{
                        p: 1.1,
                        borderRadius: 2,
                        cursor: "pointer",
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
          <Button variant="contained" disabled={busy} startIcon={<LocalShipping />} onClick={confirmCheckout}>
            Confirm Send
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
