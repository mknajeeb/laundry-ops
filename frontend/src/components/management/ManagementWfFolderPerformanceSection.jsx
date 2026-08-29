import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
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
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import {
  getManagementWfFolderPerformance,
  getManagementWfFolderSessionOrders,
  getManagementWfFolderDestinations,
  postManagementWfFolderAttributionMove,
  postManagementWfFolderAttributionReset,
  postVeewashStep1Correction,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import PerformanceDetailDrawer, {
  PerformanceFilterChip,
  PerformanceSortSelect,
} from "./performance/PerformanceDetailDrawer";
import { PERF_TYPE, PERF_UI, PerfSeparator, perfKpiCellSx, perfKpiGridSx, perfKpiInlineSx, perfKpiStripSx, perfRowSx } from "./performance/performanceTokens";
import { fmtCount, fmtDelta, fmtHours, fmtLbs, fmtRate } from "./performance/performanceFormat";
import { displayCustomerName } from "../../utils/displayCustomerName";

const WF_SORT_OPTIONS = [
  { value: "output", label: "Most orders" },
  { value: "pounds", label: "Most lb" },
  { value: "lbs_hr", label: "Highest lb/hr" },
  { value: "bags_hr", label: "Highest bags/hr" },
];

function SessionLink({ session, onOpenSession }) {
  const label = session.session_code
    ? `View ${session.session_code}`
    : `View ${session.orders_completed} order${session.orders_completed === 1 ? "" : "s"}`;
  return (
    <Box
      component="button"
      type="button"
      onClick={() => onOpenSession(session)}
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: 0.1,
        m: 0,
        p: 0,
        border: "none",
        bgcolor: "transparent",
        cursor: "pointer",
        fontFamily: "inherit",
        ...PERF_TYPE.link,
        minHeight: { xs: 36, md: 28 },
        WebkitTapHighlightColor: "transparent",
        "&:hover": { color: PERF_UI.teal, textDecoration: "underline" },
      }}
    >
      {label}
      <ChevronRightIcon sx={{ fontSize: 14 }} />
    </Box>
  );
}

function WfEmployeeRankCard({ rank, employee, onOpenSession }) {
  const sessions = employee.sessions || [];
  const timeRange = employee.time_range_label || sessions[0]?.time_range_label;
  const duration = employee.duration_label;
  const statsLine = `${fmtCount(employee.orders_completed)} orders · ${fmtLbs(employee.total_pre_lbs, { compact: true })} · ${fmtRate(employee.bags_per_hour)} bags/hr`;
  const metaParts = [timeRange, duration].filter(Boolean);

  return (
    <Box sx={perfRowSx()}>
      {/* Phone */}
      <Box sx={{ display: { xs: "block", md: "none" } }}>
        <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1}>
          <Typography sx={{ ...PERF_TYPE.name, minWidth: 0 }} noWrap>
            <Box component="span" sx={PERF_TYPE.rank}>
              #{rank}{" "}
            </Box>
            {employee.employee}
          </Typography>
          <Typography sx={PERF_TYPE.metricPrimary} whiteSpace="nowrap">
            {fmtRate(employee.lbs_per_hour, 0)}{" "}
            <Box component="span" sx={PERF_TYPE.metricLabel}>
              lb/hr
            </Box>
          </Typography>
        </Stack>
        <Typography sx={{ ...PERF_TYPE.body, mt: 0.2 }}>{statsLine}</Typography>
        {metaParts.length ? (
          <Typography sx={{ ...PERF_TYPE.meta, mt: 0.15 }}>{metaParts.join(" · ")}</Typography>
        ) : null}
        {sessions.length ? (
          <Stack direction="row" spacing={0.75} flexWrap="wrap" sx={{ mt: 0.35 }}>
            {sessions.map((sess) => (
              <SessionLink key={sess.session_id} session={sess} onOpenSession={onOpenSession} />
            ))}
          </Stack>
        ) : null}
      </Box>

      {/* Desktop / tablet */}
      <Box sx={{ display: { xs: "none", md: "block" } }}>
        <Stack direction="row" alignItems="baseline" spacing={0.75} useFlexGap flexWrap="wrap">
          <Typography component="span" sx={PERF_TYPE.rank}>
            #{rank}
          </Typography>
          <Typography component="span" sx={PERF_TYPE.name}>
            {employee.employee}
          </Typography>
          <Typography component="span" sx={PERF_TYPE.body}>
            {statsLine}
          </Typography>
          <Box sx={{ flex: 1, minWidth: 8 }} />
          <Typography component="span" sx={PERF_TYPE.metricPrimary}>
            {fmtRate(employee.lbs_per_hour, 0)} lb/hr
          </Typography>
        </Stack>
        <Stack
          direction="row"
          alignItems="center"
          spacing={0.5}
          useFlexGap
          flexWrap="wrap"
          sx={{ mt: 0.2 }}
        >
          {metaParts.length ? (
            <Typography component="span" sx={PERF_TYPE.meta}>
              {metaParts.join(" · ")}
            </Typography>
          ) : null}
          {metaParts.length && sessions.length ? (
            <Typography component="span" sx={PERF_TYPE.meta}>
              ·
            </Typography>
          ) : null}
          {sessions.map((sess, idx) => (
            <Stack key={sess.session_id} direction="row" alignItems="center" spacing={0.35}>
              {idx > 0 ? (
                <Typography component="span" sx={PERF_TYPE.meta}>
                  ·
                </Typography>
              ) : null}
              <SessionLink session={sess} onOpenSession={onOpenSession} />
            </Stack>
          ))}
        </Stack>
      </Box>
    </Box>
  );
}

function DeltaChip({ label, pct }) {
  const text = fmtDelta(pct);
  if (!text) return null;
  const up = Number(pct) >= 0;
  return (
    <Typography
      component="span"
      sx={{
        fontSize: 11,
        fontWeight: 500,
        color: up ? "#047857" : "#b91c1c",
      }}
    >
      {label} {text}
    </Typography>
  );
}

function OrderRow({
  order,
  selectable,
  selected,
  onToggle,
  selectedDateEt,
  onSentBack,
}) {
  const [expanded, setExpanded] = useState(false);
  const [sending, setSending] = useState(false);
  const [sentOk, setSentOk] = useState(false);

  const status = String(
    order.dashboard_status || order.effective_status || order.status || "",
  )
    .toLowerCase()
    .replace(/-/g, "_");
  const alreadyReview =
    status.includes("review") || order.review_required === true || Boolean(order.in_review);
  const showSendBack = !alreadyReview;

  const handleSendBack = async (e) => {
    e?.stopPropagation?.();
    if (!order?.bag_id || sending) return;
    const dateEt = order.selected_date_et || selectedDateEt;
    if (!dateEt) return;
    if (!window.confirm(`Send ${order.bag_id} back to Review Required?`)) return;
    setSending(true);
    setSentOk(false);
    try {
      const reasonCodes = order.manual_review_reason_codes || order.reason_codes || [];
      const reasonCode = String(reasonCodes[0] || "MANAGER_SENT_FOR_REVIEW")
        .trim()
        .toUpperCase();
      const res = await postVeewashStep1Correction({
        action: "move_to_review",
        bag_id: order.bag_id,
        selected_date_et: dateEt,
        reason_code: reasonCode,
        reason: "Manager sent bag back to review",
      });
      if (!res?.data?.ok) {
        window.alert(res?.data?.error || "Send back to review failed");
        return;
      }
      setSentOk(true);
      await onSentBack?.(order);
    } catch (err) {
      window.alert(err?.response?.data?.error || err?.message || "Send back to review failed");
    } finally {
      setSending(false);
    }
  };

  const timeLabel = formatFriendlyEtWall(order.completion_time_et) || order.completion_time_et || "—";

  return (
    <Box
      sx={{
        py: 1.15,
        borderBottom: "1px solid #f1f5f9",
        cursor: "pointer",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <Stack direction="row" spacing={1} alignItems="flex-start">
        {selectable ? (
          <Checkbox
            size="small"
            checked={selected}
            onChange={(e) => {
              e.stopPropagation();
              onToggle(order.bag_id);
            }}
            onClick={(e) => e.stopPropagation()}
            sx={{ p: 0.25, mt: 0.1 }}
          />
        ) : null}
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontSize: 14, fontWeight: 600, color: PERF_UI.navy }}>
            {displayCustomerName(order.customer_name) || "Customer unavailable"}
          </Typography>
          <Typography sx={{ mt: 0.15, fontSize: 13, color: PERF_UI.secondary, fontWeight: 400 }}>
            {order.bag_id}
            {order.pre_lbs != null ? ` · ${fmtLbs(order.pre_lbs, { compact: true })}` : ""}
          </Typography>
          <Typography sx={{ mt: 0.1, fontSize: 12, color: PERF_UI.muted, fontWeight: 400 }}>
            Fold complete · {timeLabel}
            {order.time_taken_label ? ` · ${order.time_taken_label}` : ""}
          </Typography>
          {(order.original_scanner && order.original_scanner !== order.credited_employee)
            || order.reassignment_indicator
            || order.unmapped_reason ? (
            <Typography sx={{ mt: 0.2, fontSize: 11, color: PERF_UI.muted, fontWeight: 400 }}>
              {order.credited_employee ? `Credited ${order.credited_employee}` : ""}
              {order.original_scanner && order.original_scanner !== order.credited_employee
                ? ` · Scanner ${order.original_scanner}`
                : ""}
              {order.reassignment_indicator ? " · Reassigned" : ""}
              {order.unmapped_reason ? ` · ${order.unmapped_reason.replaceAll("_", " ")}` : ""}
            </Typography>
          ) : null}
          {expanded ? (
            <Box sx={{ mt: 0.75 }} onClick={(e) => e.stopPropagation()}>
              {sentOk ? (
                <Typography sx={{ fontSize: 12, color: "#047857", fontWeight: 700 }}>
                  Sent back to Review
                </Typography>
              ) : showSendBack ? (
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  disabled={sending}
                  onClick={handleSendBack}
                  sx={{ textTransform: "none", fontWeight: 800 }}
                >
                  {sending ? "Sending…" : "Send Back to Review"}
                </Button>
              ) : (
                <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>
                  Already in Review Required
                </Typography>
              )}
            </Box>
          ) : null}
        </Box>
      </Stack>
    </Box>
  );
}

function MoveDialog({
  open,
  onClose,
  destinations,
  selectedCount,
  onConfirm,
  busy,
}) {
  const [employee, setEmployee] = useState("");
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    if (!open) return;
    setEmployee("");
    setSessionId("");
  }, [open]);

  const sessions = useMemo(() => {
    const match = (destinations || []).find((d) => d.employee === employee);
    return match?.sessions || [];
  }, [destinations, employee]);

  useEffect(() => {
    if (sessions.length === 1) {
      setSessionId(sessions[0].session_id || "");
    } else {
      setSessionId("");
    }
  }, [sessions]);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontWeight: 800, fontSize: 16 }}>
        Move {selectedCount} order{selectedCount === 1 ? "" : "s"}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ mt: 0.5 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Employee</InputLabel>
            <Select label="Employee" value={employee} onChange={(e) => setEmployee(e.target.value)}>
              {(destinations || []).map((d) => (
                <MenuItem key={d.employee} value={d.employee}>
                  {d.employee_label || d.employee}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth size="small" disabled={!employee}>
            <InputLabel>Folder session</InputLabel>
            <Select
              label="Folder session"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
            >
              {sessions.map((s) => (
                <MenuItem key={s.session_id} value={s.session_id}>
                  {s.session_code || "Session"} · {s.time_range_label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 2, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={busy || !employee || !sessionId}
          onClick={() => {
            const sess = sessions.find((s) => s.session_id === sessionId);
            onConfirm({
              to_employee: employee,
              to_session_id: sessionId,
              to_segment_id: sess?.segment_id,
            });
          }}
        >
          {busy ? "Moving…" : "Move"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function ManagementWfFolderPerformanceSection({ dateEt }) {
  const [compare, setCompare] = useState("today");
  const [lastN, setLastN] = useState(10);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sessionModal, setSessionModal] = useState(null);
  const [sessionOrders, setSessionOrders] = useState([]);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [selectedBagIds, setSelectedBagIds] = useState(() => new Set());
  const [moveOpen, setMoveOpen] = useState(false);
  const [destinations, setDestinations] = useState([]);
  const [actionBusy, setActionBusy] = useState(false);
  const [showUnmapped, setShowUnmapped] = useState(false);
  const [sortBy, setSortBy] = useState("output");

  const load = useCallback(
    async (opts = {}) => {
      setLoading(true);
      setError("");
      try {
        const res = await getManagementWfFolderPerformance(dateEt, {
          compare: opts.compare ?? compare,
          last_n: opts.last_n ?? lastN,
        });
        setData(res.data || null);
      } catch (err) {
        setError(err?.response?.data?.error || err?.message || "Unable to load Folder Performance");
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [dateEt, compare, lastN],
  );

  useEffect(() => {
    load();
  }, [load]);

  const openSession = async (session) => {
    setSessionModal(session);
    setSessionOrders([]);
    setSelectedBagIds(new Set());
    setSessionLoading(true);
    try {
      const day = session.selected_date_et || dateEt;
      const res = await getManagementWfFolderSessionOrders(session.session_id, day);
      setSessionOrders(res.data?.orders || []);
    } catch (err) {
      setSessionOrders([]);
      setError(err?.response?.data?.error || err?.message || "Unable to load orders");
    } finally {
      setSessionLoading(false);
    }
  };

  const toggleBag = (bagId) => {
    setSelectedBagIds((prev) => {
      const next = new Set(prev);
      if (next.has(bagId)) next.delete(bagId);
      else next.add(bagId);
      return next;
    });
  };

  const selectAllVisible = (orders) => {
    setSelectedBagIds(new Set((orders || []).map((o) => o.bag_id).filter(Boolean)));
  };

  const openMove = async () => {
    try {
      const res = await getManagementWfFolderDestinations(dateEt);
      setDestinations(res.data?.destinations || []);
      setMoveOpen(true);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load destinations");
    }
  };

  const confirmMove = async (dest) => {
    const bagIds = [...selectedBagIds];
    if (!bagIds.length) return;
    setActionBusy(true);
    try {
      const res = await postManagementWfFolderAttributionMove({
        date_et: dateEt,
        bag_ids: bagIds,
        ...dest,
      });
      if (res.data?.dashboard) setData(res.data.dashboard);
      else await load();
      setMoveOpen(false);
      setSelectedBagIds(new Set());
      if (sessionModal) {
        await openSession({
          ...sessionModal,
          selected_date_et: sessionModal.selected_date_et || dateEt,
        });
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Move failed");
    } finally {
      setActionBusy(false);
    }
  };

  const resetSelected = async () => {
    const bagIds = [...selectedBagIds];
    if (!bagIds.length) return;
    setActionBusy(true);
    try {
      const res = await postManagementWfFolderAttributionReset({
        date_et: dateEt,
        bag_ids: bagIds,
      });
      if (res.data?.dashboard) setData(res.data.dashboard);
      else await load();
      setSelectedBagIds(new Set());
      if (sessionModal) {
        await openSession({
          ...sessionModal,
          selected_date_et: sessionModal.selected_date_et || dateEt,
        });
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Reset failed");
    } finally {
      setActionBusy(false);
    }
  };

  const handleOrderSentBack = async (order) => {
    await load();
    if (sessionModal) {
      await openSession({
        ...sessionModal,
        selected_date_et: order?.selected_date_et || sessionModal.selected_date_et || dateEt,
      });
    }
  };

  const presets = data?.ui_presets || [
    { key: "today", label: "Today" },
    { key: "same_weekday_last_week", label: "Same day last week" },
    { key: "7d", label: "7D" },
    { key: "30d", label: "30D" },
    { key: "last_n", label: "Last N" },
  ];

  const summary = data?.summary || {};
  const deltas = data?.deltas;
  const unmapped = data?.unmapped_orders || [];
  const unmappedCount = data?.unmapped_count || 0;

  const employees = useMemo(() => {
    const rows = [...(data?.employees || [])];
    if (sortBy === "lbs_hr") {
      rows.sort((a, b) => (b.lbs_per_hour || 0) - (a.lbs_per_hour || 0));
    } else if (sortBy === "bags_hr") {
      rows.sort((a, b) => (b.bags_per_hour || 0) - (a.bags_per_hour || 0));
    } else if (sortBy === "pounds") {
      rows.sort((a, b) => (b.total_pre_lbs || 0) - (a.total_pre_lbs || 0));
    } else {
      rows.sort((a, b) => (b.orders_completed || 0) - (a.orders_completed || 0));
    }
    return rows;
  }, [data?.employees, sortBy]);

  const totalHours = summary.total_hours ?? summary.session_hours;
  const kpiItems = [
    { value: fmtCount(summary.orders_completed), label: "Orders", accent: false },
    {
      value: fmtLbs(summary.total_pre_lbs, { compact: true }).replace(/ lb$/, ""),
      label: "Pounds",
      accent: false,
    },
    { value: fmtCount(summary.employee_count), label: "Employees", accent: false },
    { value: fmtHours(totalHours), label: "Total Hours", accent: false },
    { value: fmtRate(summary.bags_per_hour), label: "Avg Bags/hr", accent: false },
    { value: fmtRate(summary.lbs_per_hour, 0), label: "Avg lb/hr", accent: true },
  ];

  const kpiInline = (
    <Typography sx={{ ...PERF_TYPE.kpi, ...perfKpiInlineSx() }}>
      {kpiItems.map((item, idx) => (
        <Box component="span" key={item.label}>
          {idx > 0 ? <PerfSeparator /> : null}
          <Box component="span" sx={item.accent ? PERF_TYPE.kpiAccent : PERF_TYPE.kpiValue}>
            {item.value} {item.label}
          </Box>
        </Box>
      ))}
    </Typography>
  );

  const kpiGrid = (
    <Box sx={perfKpiGridSx()}>
      {kpiItems.map((item) => (
        <Box key={item.label} sx={perfKpiCellSx()}>
          <Typography
            sx={{
              ...PERF_TYPE.kpiCellValue,
              ...(item.accent ? { color: PERF_UI.tealDark } : null),
            }}
          >
            {item.value}
          </Typography>
          <Typography sx={PERF_TYPE.kpiCellLabel}>{item.label}</Typography>
        </Box>
      ))}
    </Box>
  );

  return (
    <Box sx={{ width: "100%", minWidth: 0 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        spacing={0.75}
        sx={{ mb: 0.65 }}
      >
        <Box
          sx={{
            display: "flex",
            gap: 0.5,
            overflowX: "auto",
            flex: 1,
            minWidth: 0,
            WebkitOverflowScrolling: "touch",
            "&::-webkit-scrollbar": { display: "none" },
          }}
        >
          {presets.map((p) => (
            <PerformanceFilterChip
              key={p.key}
              active={compare === p.key}
              onClick={() => {
                setCompare(p.key);
                load({ compare: p.key });
              }}
            >
              {p.label}
            </PerformanceFilterChip>
          ))}
        </Box>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ flexShrink: 0 }}>
          <PerformanceSortSelect
            value={sortBy}
            options={WF_SORT_OPTIONS}
            onChange={setSortBy}
            aria-label="Sort employees"
          />
          <Box
            component="button"
            type="button"
            onClick={() => load()}
            aria-label="Refresh"
            sx={{
              appearance: "none",
              border: `1px solid ${PERF_UI.rowBorder}`,
              borderRadius: "50%",
              width: 28,
              height: 28,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              bgcolor: PERF_UI.rowBg,
              cursor: "pointer",
              color: PERF_UI.muted,
            }}
          >
            <RefreshIcon sx={{ fontSize: 16 }} />
          </Box>
        </Stack>
      </Stack>

      {compare === "last_n" ? (
        <TextField
          size="small"
          type="number"
          label="Last N sessions"
          value={lastN}
          onChange={(e) => setLastN(Math.max(1, Number(e.target.value) || 1))}
          onBlur={() => load({ compare: "last_n", last_n: lastN })}
          sx={{ mb: 1.25, width: { xs: "100%", sm: 160 } }}
          inputProps={{ min: 1, max: 100 }}
        />
      ) : null}

      {error ? (
        <Alert severity="error" sx={{ mb: 1.25, py: 0.5 }}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ py: 5, textAlign: "center" }}>
          <CircularProgress size={28} sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
        </Box>
      ) : (
        <>
          <Box sx={perfKpiStripSx()}>
            {kpiInline}
            {kpiGrid}
            {deltas ? (
              <Stack direction="row" spacing={1} sx={{ mt: 0.35, flexWrap: "wrap" }}>
                <DeltaChip label="Bags/hr" pct={deltas.bags_per_hour_delta_pct} />
                <DeltaChip label="Lb/hr" pct={deltas.lbs_per_hour_delta_pct} />
              </Stack>
            ) : null}
          </Box>

          {unmappedCount > 0 ? (
            <Box sx={{ mb: 0.85 }}>
              <Button
                fullWidth
                onClick={() => setShowUnmapped((v) => !v)}
                sx={{
                  justifyContent: "space-between",
                  textTransform: "none",
                  fontWeight: 500,
                  fontSize: 12,
                  py: 0.65,
                  px: 1,
                  borderRadius: 1.25,
                  color: "#9a6700",
                  bgcolor: showUnmapped ? "rgba(180, 83, 9, 0.08)" : PERF_UI.rowBg,
                  border: `1px solid ${PERF_UI.rowBorder}`,
                  boxShadow: "none",
                  "&:hover": { bgcolor: "rgba(180, 83, 9, 0.08)" },
                }}
              >
                Unmapped orders
                <Box component="span" sx={{ fontWeight: 600 }}>
                  {unmappedCount}
                </Box>
              </Button>
              {showUnmapped ? (
                <Box
                  sx={{
                    mt: 0.45,
                    px: 1,
                    py: 0.75,
                    borderRadius: 1.25,
                    bgcolor: "rgba(180, 83, 9, 0.06)",
                    border: `1px solid rgba(180, 83, 9, 0.12)`,
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.35 }}>
                    <Typography sx={{ fontSize: 12, fontWeight: 500, color: "#92400e" }}>
                      Reassign unattributed orders
                    </Typography>
                    <Stack direction="row" spacing={0.5}>
                      <Button size="small" onClick={() => selectAllVisible(unmapped)} sx={{ textTransform: "none" }}>
                        All
                      </Button>
                      <Button
                        size="small"
                        disabled={!selectedBagIds.size}
                        onClick={openMove}
                        sx={{ textTransform: "none", fontWeight: 600 }}
                      >
                        Move
                      </Button>
                    </Stack>
                  </Stack>
                  {unmapped.map((o) => (
                    <OrderRow
                      key={o.bag_id}
                      order={o}
                      selectable
                      selected={selectedBagIds.has(o.bag_id)}
                      onToggle={toggleBag}
                      selectedDateEt={o.selected_date_et || dateEt}
                      onSentBack={handleOrderSentBack}
                    />
                  ))}
                </Box>
              ) : null}
            </Box>
          ) : null}

          <Stack spacing={0.3}>
            {employees.map((emp, idx) => (
              <WfEmployeeRankCard
                key={emp.employee}
                rank={idx + 1}
                employee={emp}
                onOpenSession={openSession}
              />
            ))}
            {!loading && !employees.length ? (
              <Typography sx={{ py: 2, ...PERF_TYPE.body, textAlign: "center" }}>
                No Wash & Fold folder sessions for this window.
              </Typography>
            ) : null}
          </Stack>
        </>
      )}

      <PerformanceDetailDrawer
        open={!!sessionModal}
        onClose={() => {
          setSessionModal(null);
          setSelectedBagIds(new Set());
        }}
        title={sessionModal?.employee || "Orders"}
        subtitle={sessionModal?.time_range_label || undefined}
        footer={
          <Button
            fullWidth
            variant="outlined"
            onClick={() => {
              setSessionModal(null);
              setSelectedBagIds(new Set());
            }}
            sx={{ textTransform: "none", fontWeight: 500 }}
          >
            Close
          </Button>
        }
      >
        <Stack direction="row" spacing={0.75} sx={{ mb: 1, flexWrap: "wrap" }}>
          <Button size="small" onClick={() => selectAllVisible(sessionOrders)} sx={{ textTransform: "none" }}>
            Select all
          </Button>
          <Button
            size="small"
            disabled={!selectedBagIds.size}
            onClick={openMove}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            Move
          </Button>
          <Button
            size="small"
            disabled={!selectedBagIds.size || actionBusy}
            onClick={resetSelected}
            sx={{ textTransform: "none" }}
          >
            Reset
          </Button>
        </Stack>
        {sessionLoading ? (
          <Box sx={{ py: 4, textAlign: "center" }}>
            <CircularProgress size={24} />
          </Box>
        ) : sessionOrders.length ? (
          sessionOrders.map((o) => (
            <OrderRow
              key={o.bag_id}
              order={o}
              selectable
              selected={selectedBagIds.has(o.bag_id)}
              onToggle={toggleBag}
              selectedDateEt={o.selected_date_et || sessionModal?.selected_date_et || dateEt}
              onSentBack={handleOrderSentBack}
            />
          ))
        ) : (
          <Typography sx={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>
            No orders in this session.
          </Typography>
        )}
      </PerformanceDetailDrawer>

      <MoveDialog
        open={moveOpen}
        onClose={() => setMoveOpen(false)}
        destinations={destinations}
        selectedCount={selectedBagIds.size}
        onConfirm={confirmMove}
        busy={actionBusy}
      />
    </Box>
  );
}
