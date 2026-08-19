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
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  getManagementRinseHd,
  getManagementRinseHdDetail,
  saveManagementRinseHdProduction,
} from "../api";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";

function todayEtIso() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtTime(v) {
  if (!v) return "—";
  return formatFriendlyEtWall(v) || String(v);
}

/**
 * Thin employee PIN wrapper around Management Rinse HD production write path.
 * Same APIs/tables as /management/rinse-hd — no Management chrome, filters,
 * date picker, mark-complete, or reports.
 */
export default function HangDryFloorFlow({ onBack, onLock }) {
  const dateEt = useMemo(() => todayEtIso(), []);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [items, setItems] = useState("");
  const [revenue, setRevenue] = useState("");
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async (refresh = false) => {
    if (!refresh) setData(null);
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHd(dateEt, { status: "all" });
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load Hang Dry");
    } finally {
      setLoading(false);
    }
  }, [dateEt]);

  useEffect(() => {
    load(false);
  }, [load]);

  const orders = data?.orders || [];

  const openDetail = async (order) => {
    setActionError("");
    setDetailOpen(true);
    setDetail({ loading: true, order });
    setItems(order.items != null ? String(order.items) : "");
    setRevenue(order.revenue != null ? String(order.revenue) : "");
    try {
      const res = await getManagementRinseHdDetail(order.bag_id, { date_et: dateEt });
      setDetail(res.data || null);
      const prod = res.data?.production || res.data?.order || {};
      setItems(prod.items != null ? String(prod.items) : order.items != null ? String(order.items) : "");
      setRevenue(
        prod.revenue != null
          ? String(prod.revenue)
          : order.revenue != null
            ? String(order.revenue)
            : "",
      );
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Unable to load bag");
      setDetail({ order });
    }
  };

  const saveProduction = async () => {
    const bagId = detail?.order?.bag_id || detail?.bag_id;
    if (!bagId) return;
    setSaving(true);
    setActionError("");
    try {
      await saveManagementRinseHdProduction(bagId, {
        date_et: dateEt,
        total_items: items === "" ? null : Number(items),
        revenue: revenue === "" ? null : Number(revenue),
        version: detail?.production?.version ?? detail?.order?.production_version ?? 0,
      });
      await load(true);
      setDetailOpen(false);
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <OpsMobileShell>
      <OpsTopBar title="Hang Dry" onBack={onBack} onLock={onLock} />
      <Typography
        sx={{
          fontWeight: 700,
          fontSize: "0.95rem",
          color: OPS_MOBILE.navy,
          mt: 0.5,
          mb: 1,
        }}
      >
        Today · enter items and revenue
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : null}

      {!loading && !error && !orders.length ? (
        <Alert severity="info" sx={{ mt: 1 }}>
          No Hang Dry bags for today.
        </Alert>
      ) : null}

      <Stack spacing={1} sx={{ pb: 2 }}>
        {orders.map((order) => {
          const open = order.status === "open";
          return (
            <Box
              key={order.bag_id}
              component="button"
              type="button"
              onClick={() => openDetail(order)}
              sx={{
                display: "block",
                width: "100%",
                textAlign: "left",
                m: 0,
                p: 1.25,
                borderRadius: 2,
                border: "1px solid #e5e7eb",
                bgcolor: "#fff",
                cursor: "pointer",
                appearance: "none",
                fontFamily: "inherit",
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                <Typography sx={{ fontSize: 15, fontWeight: 800, fontFamily: "monospace" }}>
                  {order.bag_id}
                </Typography>
                <Chip
                  size="small"
                  label={open ? "In process" : "Completed"}
                  sx={{ height: 22, fontWeight: 700 }}
                />
              </Stack>
              <Typography sx={{ mt: 0.5, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                Started {fmtTime(order.started_at)} · {order.start_operator || "—"}
              </Typography>
              <Stack direction="row" spacing={2} sx={{ mt: 0.75 }}>
                <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Items {fmtInt(order.items)}</Typography>
                <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(order.revenue)}</Typography>
              </Stack>
            </Box>
          );
        })}
      </Stack>

      <Dialog open={detailOpen} onClose={() => !saving && setDetailOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>
          {detail?.order?.bag_id || detail?.bag_id || "Hang Dry"}
        </DialogTitle>
        <DialogContent>
          {detail?.loading ? (
            <Box sx={{ display: "grid", placeItems: "center", py: 3 }}>
              <CircularProgress size={24} />
            </Box>
          ) : (
            <Stack spacing={1.5} sx={{ pt: 0.5 }}>
              {actionError ? <Alert severity="error">{actionError}</Alert> : null}
              <TextField
                label="Items"
                type="number"
                value={items}
                onChange={(e) => setItems(e.target.value)}
                fullWidth
                inputProps={{ min: 0, step: 1 }}
              />
              <TextField
                label="Revenue"
                type="number"
                value={revenue}
                onChange={(e) => setRevenue(e.target.value)}
                fullWidth
                inputProps={{ min: 0, step: 0.01 }}
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 2, pb: 2 }}>
          <Button onClick={() => setDetailOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={saveProduction} disabled={saving || detail?.loading}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </OpsMobileShell>
  );
}
