import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import IconButton from "@mui/material/IconButton";
import {
  excludeManagementRinseHdOrder,
  getManagementRinseHd,
  getManagementRinseHdDetail,
  getManagementRinseHdSummary,
  markManagementRinseHdComplete,
  permanentDeleteManagementRinseHdOrders,
  restoreManagementRinseHdOrder,
  saveManagementRinseHdProduction,
  updateManagementRinseHdAttribution,
} from "../api";
import ManagementCopyableId from "../components/management/ManagementCopyableId";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { groupOrdersByDeliveryDate } from "../components/management/hdDeliveryDateGroups";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const STATUS_CHIPS = [
  { id: "pending_wash", label: "Pending Wash" },
  { id: "awaiting_fold", label: "Awaiting Fold" },
  { id: "awaiting_entry", label: "Awaiting Entry" },
  { id: "complete", label: "Complete" },
  { id: "excluded", label: "Excluded" },
  { id: "all", label: "All" },
];

const PERIODS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
  { id: "custom", label: "Custom" },
];

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

function statusLabel(status) {
  if (status === "pending_wash") return "Pending Wash";
  if (status === "washed" || status === "awaiting_fold") return "Awaiting Fold";
  if (status === "awaiting_entry") return "Awaiting Entry";
  if (status === "complete") return "Complete";
  if (status === "excluded") return "Excluded";
  return status || "—";
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
      <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.05 }}>{value}</Typography>
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

function OrderCard({ order, onOpen, onExclude, showExclude = false }) {
  const awaiting = order.status === "awaiting_entry";
  const pending =
    order.status === "pending_wash" ||
    order.status === "washed" ||
    order.status === "awaiting_fold";
  const customer =
    String(order.customer_name || order.name_clean || order.customer || "").trim() || "Unknown Customer";
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
        borderColor: awaiting
          ? VEEWASH_DASHBOARD.pendingBorder
          : pending
            ? "#cbd5e1"
            : VEEWASH_DASHBOARD.hdBorder,
        bgcolor: "#fff",
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontSize: 16, fontWeight: 800, lineHeight: 1.2, color: "#0f172a" }}>
            {customer}
          </Typography>
          <Box sx={{ mt: 0.35 }} onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
            <ManagementCopyableId value={order.bag_id} fontSize={13} fontWeight={800} />
          </Box>
        </Box>
        <Chip
          size="small"
          label={statusLabel(order.status)}
          sx={{
            height: 22,
            fontWeight: 700,
            flexShrink: 0,
            bgcolor: awaiting
              ? VEEWASH_DASHBOARD.pendingLight
              : order.status === "complete"
                ? VEEWASH_DASHBOARD.hdBg
                : "#f1f5f9",
          }}
        />
      </Stack>
      <Typography sx={{ mt: 0.75, fontSize: 12, color: "#334155", fontWeight: 600 }}>
        Washed by {order.washed_by_name || "—"}
      </Typography>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
        {fmtTime(order.washed_at)}
      </Typography>
      <Typography sx={{ mt: 0.5, fontSize: 12, color: "#334155", fontWeight: 600 }}>
        Folded by {order.folded_by_name || "—"}
      </Typography>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
        {fmtTime(order.folded_at)}
      </Typography>
      <Stack direction="row" spacing={2} sx={{ mt: 0.75 }}>
        <Typography sx={{ fontSize: 13, fontWeight: 700 }}>Items {fmtInt(order.items)}</Typography>
        <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(order.revenue)}</Typography>
      </Stack>
      {order.completion_at ? (
        <Typography sx={{ mt: 0.35, fontSize: 11, color: "#64748b", fontWeight: 600 }}>
          Complete {fmtTime(order.completion_at)}
          {order.completion_operator ? ` · ${order.completion_operator}` : ""}
        </Typography>
      ) : null}
      {order.delivery_date_et ? (
        <Typography sx={{ mt: 0.35, fontSize: 11, color: "#64748b", fontWeight: 600 }}>
          Delivery {formatDayLabel(order.delivery_date_et)}
        </Typography>
      ) : null}
      {showExclude ? (
        <Button
          size="small"
          color="warning"
          onClick={(e) => {
            e.stopPropagation();
            onExclude?.(order);
          }}
          sx={{ mt: 0.75, textTransform: "none", fontWeight: 700 }}
        >
          Exclude
        </Button>
      ) : null}
    </Box>
  );
}

function ExcludedOrderCard({ order, selected, onToggle, onRestore }) {
  const customer =
    String(order.customer_name || order.name_clean || order.customer || "").trim() || "Unknown Customer";
  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: "1px solid #fcd34d",
        bgcolor: "#fffbeb",
      }}
    >
      <Stack direction="row" spacing={1} alignItems="flex-start">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle?.(order.bag_id)}
          aria-label={`Select ${order.bag_id}`}
        />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontSize: 16, fontWeight: 800 }}>{customer}</Typography>
          <ManagementCopyableId value={order.bag_id} fontSize={13} fontWeight={800} />
          <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.35 }}>
            Delivery {order.delivery_date_et ? formatDayLabel(order.delivery_date_et) : "—"}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b" }}>
            Excluded {fmtTime(order.excluded_at)}
            {order.excluded_reason ? ` · ${order.excluded_reason}` : ""}
          </Typography>
          {order.excluded_note ? (
            <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>{order.excluded_note}</Typography>
          ) : null}
          {order.excluded_from_status ? (
            <Typography sx={{ fontSize: 11, color: "#94a3b8" }}>
              Prior state: {statusLabel(order.excluded_from_status)}
            </Typography>
          ) : null}
          <Button
            size="small"
            variant="outlined"
            onClick={() => onRestore?.(order)}
            sx={{ mt: 0.75, textTransform: "none", fontWeight: 700 }}
          >
            Restore
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}

function DeliveryDateGroups({
  groups,
  statusFilter,
  onOpen,
  onExclude,
  onRestore,
  selectedExcluded,
  onToggleExcluded,
}) {
  const isExcluded = statusFilter === "excluded";
  const showExclude = !isExcluded && statusFilter !== "all" && statusFilter !== "complete";
  return (
    <Stack spacing={1.25}>
      {groups.map((group) => (
        <Box key={group.label}>
          <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ mb: 0.5 }}>
            <Typography sx={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.6, color: "#0f172a" }}>
              {group.label}
            </Typography>
            <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#64748b" }}>{group.count}</Typography>
          </Stack>
          <Stack spacing={0.75}>
            {group.orders.map((order) =>
              isExcluded ? (
                <ExcludedOrderCard
                  key={order.bag_id}
                  order={order}
                  selected={selectedExcluded.has(order.bag_id)}
                  onToggle={onToggleExcluded}
                  onRestore={onRestore}
                />
              ) : (
                <OrderCard
                  key={`${order.bag_id}-${order.status}`}
                  order={order}
                  onOpen={onOpen}
                  onExclude={onExclude}
                  showExclude={showExclude}
                />
              ),
            )}
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}

function toDatetimeLocalValue(v) {
  if (!v) return "";
  const raw = String(v).replace("T", " ").slice(0, 19);
  const d = new Date(raw.includes("Z") || raw.includes("+") ? v : `${raw.replace(" ", "T")}`);
  if (Number.isNaN(d.getTime())) {
    return raw.slice(0, 16).replace(" ", "T");
  }
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromDatetimeLocalValue(v) {
  if (!v) return null;
  return String(v).replace("T", " ") + ":00";
}

export default function ManagementRinseHdPage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [statusFilter, setStatusFilter] = useState("awaiting_entry");
  const [period, setPeriod] = useState("today");
  const [customStart, setCustomStart] = useState(todayEtIso);
  const [customEnd, setCustomEnd] = useState(todayEtIso);
  const [data, setData] = useState(null);
  const [rangeSummary, setRangeSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [items, setItems] = useState("");
  const [revenue, setRevenue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveState, setSaveState] = useState("");
  const [actionError, setActionError] = useState("");
  const [attrEdit, setAttrEdit] = useState(false);
  const [attrForm, setAttrForm] = useState({
    washed_by_user_id: "",
    washed_at: "",
    folded_by_user_id: "",
    folded_at: "",
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedExcluded, setSelectedExcluded] = useState(() => new Set());
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const autosaveTimer = useRef(null);

  const load = useCallback(async (day, status, refresh = false) => {
    if (!refresh) setData(null);
    setLoading(true);
    setError("");
    try {
      const res = await getManagementRinseHd(day, { status });
      setData(res.data || null);
    } catch (err) {
      setData(null);
      setError(err?.response?.data?.error || err?.message || "Unable to load Rinse HD");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const params = { period };
      if (period === "custom") {
        params.start_et = customStart;
        params.end_et = customEnd;
      }
      const res = await getManagementRinseHdSummary(params);
      setRangeSummary(res.data || null);
    } catch {
      setRangeSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  }, [period, customStart, customEnd]);

  useEffect(() => {
    load(dateEt, statusFilter, false);
  }, [dateEt, statusFilter, load]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const summary = rangeSummary || data?.summary || {};
  const orders = data?.orders || [];
  const filteredOrders = useMemo(() => {
    const q = String(searchQuery || "").trim().toLowerCase();
    if (!q) return orders;
    return orders.filter((order) => {
      const bag = String(order.bag_id || "").toLowerCase();
      const customer = String(
        order.customer_name || order.name_clean || order.customer || "",
      ).toLowerCase();
      return bag.includes(q) || customer.includes(q);
    });
  }, [orders, searchQuery]);

  const deliveryGroups = useMemo(
    () => groupOrdersByDeliveryDate(filteredOrders, dateEt),
    [filteredOrders, dateEt],
  );

  const openDetail = async (order) => {
    setActionError("");
    setSaveState("");
    setAttrEdit(false);
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
      setAttrForm({
        washed_by_user_id: prod.washed_by_user_id ?? "",
        washed_at: toDatetimeLocalValue(prod.washed_at),
        folded_by_user_id: prod.folded_by_user_id ?? "",
        folded_at: toDatetimeLocalValue(prod.folded_at),
      });
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Unable to load order");
      setDetail({ order });
    }
  };

  const flushSave = async () => {
    const bagId = detail?.order?.bag_id || detail?.bag_id;
    if (!bagId) return;
    const status = detail?.order?.status;
    if (status !== "awaiting_entry" && status !== "complete") return;
    setSaving(true);
    setSaveState("saving");
    setActionError("");
    try {
      const res = await saveManagementRinseHdProduction(bagId, {
        date_et: dateEt,
        total_items: items === "" ? null : Number(items),
        revenue: revenue === "" ? null : Number(revenue),
        version: detail?.production?.version ?? detail?.order?.production_version ?? 0,
      });
      setSaveState("saved");
      setDetail((d) => ({
        ...d,
        production: {
          ...(d?.production || {}),
          version: res.data?.version,
          items: res.data?.total_items,
          revenue: res.data?.revenue,
          workflow_status: res.data?.workflow_status,
        },
        order: {
          ...(d?.order || {}),
          production_version: res.data?.version,
          items: res.data?.total_items,
          revenue: res.data?.revenue,
          status: res.data?.workflow_status || d?.order?.status,
        },
      }));
      await load(dateEt, statusFilter, true);
    } catch (err) {
      setSaveState("error");
      setActionError(err?.response?.data?.message || err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const scheduleAutosave = () => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      flushSave();
    }, 650);
  };

  const markComplete = async () => {
    const bagId = detail?.order?.bag_id || detail?.bag_id;
    if (!bagId) return;
    if (autosaveTimer.current) {
      clearTimeout(autosaveTimer.current);
      await flushSave();
    }
    setSaving(true);
    setActionError("");
    try {
      await markManagementRinseHdComplete(bagId, {
        date_et: dateEt,
        version: detail?.production?.version ?? detail?.order?.production_version ?? 0,
      });
      await load(dateEt, statusFilter, true);
      setDetailOpen(false);
    } catch (err) {
      setActionError(
        err?.response?.data?.message || err?.response?.data?.error || err?.message || "Complete failed",
      );
    } finally {
      setSaving(false);
    }
  };

  const saveAttribution = async () => {
    const bagId = detail?.order?.bag_id || detail?.bag_id;
    if (!bagId) return;
    setSaving(true);
    setActionError("");
    try {
      await updateManagementRinseHdAttribution(bagId, {
        date_et: dateEt,
        version: detail?.production?.version ?? detail?.order?.production_version ?? 0,
        washed_by_user_id: attrForm.washed_by_user_id === "" ? null : Number(attrForm.washed_by_user_id),
        washed_at: fromDatetimeLocalValue(attrForm.washed_at),
        folded_by_user_id: attrForm.folded_by_user_id === "" ? null : Number(attrForm.folded_by_user_id),
        folded_at: fromDatetimeLocalValue(attrForm.folded_at),
      });
      setAttrEdit(false);
      await openDetail({ bag_id: bagId });
      await load(dateEt, statusFilter, true);
    } catch (err) {
      setActionError(err?.response?.data?.error || err?.message || "Attribution save failed");
    } finally {
      setSaving(false);
    }
  };

  const excludeOrder = async (order) => {
    if (!order?.bag_id) return;
    const note = window.prompt("Exclude reason (optional)", "") ?? "";
    try {
      await excludeManagementRinseHdOrder(order.bag_id, { date_et: dateEt, note });
      await load(dateEt, statusFilter, true);
      await loadSummary();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Exclude failed");
    }
  };

  const restoreOrder = async (order) => {
    if (!order?.bag_id) return;
    try {
      await restoreManagementRinseHdOrder(order.bag_id, { date_et: dateEt });
      setSelectedExcluded(new Set());
      await load(dateEt, statusFilter, true);
      await loadSummary();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Restore failed");
    }
  };

  const toggleExcluded = (bagId) => {
    setSelectedExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(bagId)) next.delete(bagId);
      else next.add(bagId);
      return next;
    });
  };

  const deleteSelectedExcluded = async () => {
    const bagIds = [...selectedExcluded];
    if (!bagIds.length) return;
    try {
      await permanentDeleteManagementRinseHdOrders({ bag_ids: bagIds });
      setSelectedExcluded(new Set());
      setConfirmDeleteOpen(false);
      await load(dateEt, statusFilter, true);
      await loadSummary();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Delete failed");
    }
  };

  const canEnter =
    detail?.order?.status === "awaiting_entry" || detail?.order?.status === "complete";
  const employees = detail?.employees || [];

  const periodLabel = useMemo(() => {
    if (period === "custom") return `${formatDayLabel(customStart)} – ${formatDayLabel(customEnd)}`;
    return PERIODS.find((p) => p.id === period)?.label || "Today";
  }, [period, customStart, customEnd]);

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
            {formatDayLabel(dateEt)} · wash → fold → entry → Complete
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
          <IconButton
            aria-label="Refresh"
            onClick={() => {
              load(dateEt, statusFilter, true);
              loadSummary();
            }}
            disabled={loading}
            size="small"
          >
            {loading ? <CircularProgress size={18} /> : <RefreshIcon />}
          </IconButton>
        </Stack>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}

      <Stack direction="row" spacing={0.5} sx={{ mb: 1, flexWrap: "wrap", gap: 0.5 }}>
        {PERIODS.map((p) => (
          <Chip
            key={p.id}
            size="small"
            label={p.label}
            onClick={() => setPeriod(p.id)}
            sx={{
              fontWeight: 700,
              bgcolor: period === p.id ? VEEWASH_DASHBOARD.hdTeal : "#fff",
              color: period === p.id ? "#fff" : "#334155",
              border: "1px solid",
              borderColor: period === p.id ? VEEWASH_DASHBOARD.hdTeal : "#e5e7eb",
            }}
          />
        ))}
      </Stack>
      {period === "custom" ? (
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <TextField size="small" type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
          <TextField size="small" type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
        </Stack>
      ) : null}

      <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b", mb: 0.5 }}>
        Summary · {periodLabel}
        {summaryLoading ? " · …" : ""}
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 0.75,
          mb: 1.25,
        }}
      >
        <SummaryCard label="Pending Wash" value={fmtInt(summary.pending_wash)} />
        <SummaryCard
          label="Awaiting Fold"
          value={fmtInt(summary.awaiting_fold ?? summary.washed)}
        />
        <SummaryCard label="Awaiting Entry" value={fmtInt(summary.awaiting_entry)} />
        <SummaryCard label="Complete" value={fmtInt(summary.complete ?? summary.completed_today)} />
        <SummaryCard label="Excluded" value={fmtInt(summary.excluded)} />
        <SummaryCard label="Items" value={fmtInt(summary.items ?? summary.items_completed_today)} />
        <SummaryCard label="Revenue" value={fmtMoney(summary.revenue ?? summary.revenue_completed_today)} />
      </Box>

      <FormControl size="small" fullWidth sx={{ mb: 1.25, display: { xs: "flex", sm: "none" } }}>
        <InputLabel id="hd-status-label">Queue</InputLabel>
        <Select
          labelId="hd-status-label"
          label="Queue"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_CHIPS.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.label}
              {data?.counts?.[c.id] != null ? ` (${data.counts[c.id]})` : ""}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Stack
        direction="row"
        spacing={0.75}
        sx={{ mb: 1.25, display: { xs: "none", sm: "flex" }, flexWrap: "wrap", gap: 0.5 }}
      >
        {STATUS_CHIPS.map((chip) => {
          const selected = statusFilter === chip.id;
          const count = data?.counts?.[chip.id];
          return (
            <Chip
              key={chip.id}
              size="small"
              label={count != null ? `${chip.label} ${count}` : chip.label}
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

      <TextField
        size="small"
        fullWidth
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search customer or Order/Bag ID"
        sx={{ mb: 1.25 }}
        inputProps={{ "aria-label": "Search customer or Order/Bag ID" }}
      />

      {statusFilter === "excluded" && selectedExcluded.size > 0 ? (
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Button
            size="small"
            color="error"
            variant="contained"
            onClick={() => setConfirmDeleteOpen(true)}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            Delete Permanently ({selectedExcluded.size})
          </Button>
        </Stack>
      ) : null}

      {loading && !data ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={22} />
        </Box>
      ) : (
        <Stack spacing={1}>
          {filteredOrders.length === 0 ? (
            <Typography sx={{ color: "#94a3b8", fontWeight: 600, fontSize: 13 }}>
              {orders.length === 0 ? "No HD orders in this view." : "No matches for this search."}
            </Typography>
          ) : (
            <DeliveryDateGroups
              groups={deliveryGroups}
              statusFilter={statusFilter}
              onOpen={openDetail}
              onExclude={excludeOrder}
              onRestore={restoreOrder}
              selectedExcluded={selectedExcluded}
              onToggleExcluded={toggleExcluded}
            />
          )}
        </Stack>
      )}

      <Dialog open={confirmDeleteOpen} onClose={() => setConfirmDeleteOpen(false)}>
        <DialogTitle sx={{ fontWeight: 800 }}>Permanently delete excluded HD orders?</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 14 }}>
            Permanently delete {selectedExcluded.size} excluded HD order
            {selectedExcluded.size === 1 ? "" : "s"}? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDeleteOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={deleteSelectedExcluded}>
            Delete Permanently
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 800, pb: 1 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.2 }}>
            {detail?.order?.customer_name ||
              detail?.order?.name_clean ||
              detail?.order?.customer ||
              "HD Order"}
          </Typography>
          <Box sx={{ mt: 0.5 }}>
            <ManagementCopyableId
              value={detail?.order?.bag_id || detail?.bag_id}
              fontSize={14}
              fontWeight={800}
            />
          </Box>
        </DialogTitle>
        <DialogContent>
          {actionError ? (
            <Alert severity="error" sx={{ mb: 1.5 }}>
              {actionError}
            </Alert>
          ) : null}
          {detail?.loading ? (
            <Box sx={{ py: 3, textAlign: "center" }}>
              <CircularProgress size={22} />
            </Box>
          ) : (
            <Stack spacing={1.25} sx={{ pt: 0.5 }}>
              <Chip size="small" label={statusLabel(detail?.order?.status)} sx={{ alignSelf: "flex-start", fontWeight: 700 }} />
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>
                Washed by {detail?.order?.washed_by_name || detail?.production?.washed_by_name || "—"}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                {fmtTime(detail?.order?.washed_at || detail?.production?.washed_at)}
              </Typography>
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>
                Folded by {detail?.order?.folded_by_name || detail?.production?.folded_by_name || "—"}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                {fmtTime(detail?.order?.folded_at || detail?.production?.folded_at)}
              </Typography>
              {detail?.production?.revenue_date_et ? (
                <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                  Revenue date (fold): {detail.production.revenue_date_et}
                </Typography>
              ) : null}

              <Button
                size="small"
                onClick={() => setAttrEdit((v) => !v)}
                sx={{ alignSelf: "flex-start", textTransform: "none", fontWeight: 700 }}
              >
                {attrEdit ? "Cancel attribution edit" : "Edit attribution"}
              </Button>
              {attrEdit ? (
                <Stack spacing={1} sx={{ p: 1, border: "1px solid #e5e7eb", borderRadius: 1.5 }}>
                  <FormControl size="small" fullWidth>
                    <InputLabel>Washed by</InputLabel>
                    <Select
                      label="Washed by"
                      value={attrForm.washed_by_user_id}
                      onChange={(e) => setAttrForm((f) => ({ ...f, washed_by_user_id: e.target.value }))}
                    >
                      <MenuItem value="">—</MenuItem>
                      {employees.map((emp) => (
                        <MenuItem key={emp.id || emp.user_id} value={emp.user_id ?? ""}>
                          {emp.display_name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    size="small"
                    label="Washed at (ET)"
                    type="datetime-local"
                    value={attrForm.washed_at}
                    onChange={(e) => setAttrForm((f) => ({ ...f, washed_at: e.target.value }))}
                    InputLabelProps={{ shrink: true }}
                  />
                  <FormControl size="small" fullWidth>
                    <InputLabel>Folded by</InputLabel>
                    <Select
                      label="Folded by"
                      value={attrForm.folded_by_user_id}
                      onChange={(e) => setAttrForm((f) => ({ ...f, folded_by_user_id: e.target.value }))}
                    >
                      <MenuItem value="">—</MenuItem>
                      {employees.map((emp) => (
                        <MenuItem key={`f-${emp.id || emp.user_id}`} value={emp.user_id ?? ""}>
                          {emp.display_name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    size="small"
                    label="Folded at (ET)"
                    type="datetime-local"
                    value={attrForm.folded_at}
                    onChange={(e) => setAttrForm((f) => ({ ...f, folded_at: e.target.value }))}
                    InputLabelProps={{ shrink: true }}
                  />
                  <Button variant="contained" disabled={saving} onClick={saveAttribution} sx={{ textTransform: "none", fontWeight: 800 }}>
                    Save attribution
                  </Button>
                </Stack>
              ) : null}

              {canEnter ? (
                <>
                  <TextField
                    label="Items"
                    type="number"
                    value={items}
                    onChange={(e) => {
                      setItems(e.target.value);
                      scheduleAutosave();
                    }}
                    fullWidth
                    size="small"
                  />
                  <TextField
                    label="Revenue"
                    type="number"
                    value={revenue}
                    onChange={(e) => {
                      setRevenue(e.target.value);
                      scheduleAutosave();
                    }}
                    fullWidth
                    size="small"
                    inputProps={{ step: "0.01" }}
                  />
                  <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                    {saveState === "saving"
                      ? "Saving…"
                      : saveState === "saved"
                        ? "Saved ✓ (draft — not Complete)"
                        : saveState === "error"
                          ? "Save failed"
                          : "Autosave draft · Complete required"}
                  </Typography>
                </>
              ) : (
                <Alert severity="info">Items / revenue entry unlocks after Folded / Awaiting Entry.</Alert>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setDetailOpen(false)} sx={{ textTransform: "none" }}>
            Close
          </Button>
          {canEnter && detail?.order?.status !== "complete" ? (
            <Button
              variant="contained"
              disabled={saving}
              onClick={markComplete}
              sx={{ textTransform: "none", fontWeight: 800 }}
            >
              Complete
            </Button>
          ) : null}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
