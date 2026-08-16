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
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  getManagementRinseHd,
  getManagementRinseHdDetail,
  markManagementRinseHdComplete,
  saveManagementRinseHdProduction,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

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

function formatDayLabel(iso) {
  const parts = String(iso || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !n && n !== 0)) return iso || "";
  const [year, month, day] = parts;
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
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

function SummaryCard({ label, value }) {
  return (
    <Box
      sx={{
        px: 1,
        py: 0.85,
        borderRadius: 1.5,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
        minWidth: 0,
      }}
    >
      <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.05 }}>{value}</Typography>
      <Typography
        sx={{
          mt: 0.35,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {label}
      </Typography>
    </Box>
  );
}

function OrderCard({ order, onOpen }) {
  const open = order.status === "open";
  return (
    <Box
      component="button"
      type="button"
      onClick={() => onOpen(order)}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        p: 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: open ? VEEWASH_DASHBOARD.pendingBorder : VEEWASH_DASHBOARD.hdBorder,
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
          sx={{
            height: 22,
            fontWeight: 700,
            bgcolor: open ? VEEWASH_DASHBOARD.pendingLight : VEEWASH_DASHBOARD.hdBg,
          }}
        />
      </Stack>
      <Typography sx={{ mt: 0.5, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
        Started {fmtTime(order.started_at)} · {order.start_operator || "—"}
      </Typography>
      {open ? null : (
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
          Completed {fmtTime(order.completion_at)} · {order.completion_operator || "—"}
          {order.completion_source === "MANAGEMENT_OVERRIDE" ? " · manual" : ""}
        </Typography>
      )}
      <Stack direction="row" spacing={2} sx={{ mt: 0.75 }}>
        <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Items {fmtInt(order.items)}</Typography>
        <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(order.revenue)}</Typography>
      </Stack>
    </Box>
  );
}

export default function ManagementRinseHdPage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [statusFilter, setStatusFilter] = useState("all");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [items, setItems] = useState("");
  const [revenue, setRevenue] = useState("");
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async (day, refresh = false) => {
    if (!refresh) setData(null);
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHd(day, { status: "all" });
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load Rinse HD");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(dateEt, false);
  }, [dateEt, load]);

  const summary = data?.summary || {};
  const orders = useMemo(() => {
    const rows = data?.orders || [];
    if (statusFilter === "open") return rows.filter((r) => r.status === "open");
    if (statusFilter === "completed") return rows.filter((r) => r.status === "completed");
    return rows;
  }, [data?.orders, statusFilter]);

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
      setActionError(err?.response?.data?.error || err?.message || "Unable to load order");
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
      await load(dateEt, true);
      await openDetail({ bag_id: bagId, items, revenue, status: detail?.order?.status });
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const markComplete = async () => {
    const bagId = detail?.order?.bag_id || detail?.bag_id;
    if (!bagId) return;
    setSaving(true);
    setActionError("");
    try {
      await markManagementRinseHdComplete(bagId, {
        date_et: dateEt,
        version: detail?.production?.version ?? detail?.order?.production_version ?? 0,
      });
      await load(dateEt, true);
      setDetailOpen(false);
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Mark complete failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box
      className="page"
      sx={{
        maxWidth: 720,
        mx: "auto",
        width: "100%",
        px: { xs: 1.5, sm: 2 },
        pb: 3,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <ManagementHubNav activeId="rinse_hd" />

      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 1.5, mb: 1 }} spacing={1}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>Rinse HD</Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            {formatDayLabel(dateEt)}
          </Typography>
        </Box>
        <Stack direction="row" alignItems="center" spacing={0.5}>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: 150 }}
          />
          <IconButton aria-label="Refresh" onClick={() => load(dateEt, true)} disabled={loading} size="small">
            {loading ? <CircularProgress size={18} /> : <RefreshIcon />}
          </IconButton>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 0.75,
          mb: 1.25,
        }}
      >
        <SummaryCard label="Open" value={fmtInt(summary.open_orders)} />
        <SummaryCard label="Completed" value={fmtInt(summary.completed_today)} />
        <SummaryCard label="Items" value={fmtInt(summary.items_completed_today)} />
        <SummaryCard label="Revenue" value={fmtMoney(summary.revenue_completed_today)} />
      </Box>

      <Stack direction="row" spacing={0.75} sx={{ mb: 1.25 }}>
        {[
          { id: "all", label: "All" },
          { id: "open", label: "Open" },
          { id: "completed", label: "Completed" },
        ].map((chip) => {
          const selected = statusFilter === chip.id;
          return (
            <Chip
              key={chip.id}
              size="small"
              label={chip.label}
              onClick={() => setStatusFilter(chip.id)}
              sx={{
                fontWeight: 700,
                bgcolor: selected ? VEEWASH_DASHBOARD.hdTeal : "#fff",
                color: selected ? "#fff" : "#334155",
                border: "1px solid",
                borderColor: selected ? VEEWASH_DASHBOARD.hdTeal : "#e5e7eb",
              }}
            />
          );
        })}
      </Stack>

      {loading && !data ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={22} />
        </Box>
      ) : (
        <Stack spacing={1}>
          {orders.length === 0 ? (
            <Typography sx={{ color: "#94a3b8", fontWeight: 600, fontSize: 13 }}>
              No HD orders in this view.
            </Typography>
          ) : (
            orders.map((order) => (
              <OrderCard key={`${order.bag_id}-${order.status}-${order.completion_at || "open"}`} order={order} onOpen={openDetail} />
            ))
          )}
        </Stack>
      )}

      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 800 }}>
          {detail?.order?.bag_id || detail?.bag_id || "HD order"}
        </DialogTitle>
        <DialogContent>
          {actionError ? <Alert severity="error" sx={{ mb: 1 }}>{actionError}</Alert> : null}
          <Typography sx={{ fontSize: 13, color: "#64748b", mb: 1.5 }}>
            Enter items and total order revenue only.
          </Typography>
          <Stack spacing={1.25}>
            <TextField
              label="Number of items"
              type="number"
              size="small"
              value={items}
              onChange={(e) => setItems(e.target.value)}
              inputProps={{ min: 0, step: 1 }}
            />
            <TextField
              label="Total order revenue"
              type="number"
              size="small"
              value={revenue}
              onChange={(e) => setRevenue(e.target.value)}
              inputProps={{ min: 0, step: 0.01 }}
            />
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              Started {fmtTime(detail?.order?.started_at || detail?.entry?.at)} ·{" "}
              {detail?.order?.start_operator || detail?.entry?.user_name || "—"}
            </Typography>
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              Completion {fmtTime(detail?.order?.completion_at || detail?.completion?.at)} ·{" "}
              {detail?.order?.completion_operator || detail?.completion?.user_name || "—"}
              {detail?.order?.completion_source
                ? ` · ${detail.order.completion_source}`
                : ""}
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDetailOpen(false)} disabled={saving}>
            Close
          </Button>
          {detail?.order?.status === "open" && !detail?.completion?.at ? (
            <Button onClick={markComplete} disabled={saving}>
              Mark complete
            </Button>
          ) : null}
          <Button variant="contained" onClick={saveProduction} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
