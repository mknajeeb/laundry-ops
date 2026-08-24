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
import PerformanceDetailDrawer from "./performance/PerformanceDetailDrawer";
import {
  PerformanceFilterChip,
  PerformanceSortSelect,
} from "./performance/PerformanceDetailDrawer";
import { fmtCount, fmtDelta, fmtLbs, fmtRate } from "./performance/performanceFormat";

const WF_SORT_OPTIONS = [
  { value: "output", label: "Most orders" },
  { value: "pounds", label: "Most lb" },
  { value: "lbs_hr", label: "Highest lb/hr" },
  { value: "bags_hr", label: "Highest bags/hr" },
];

function SessionTiming({ session, employee, compact = false }) {
  const target = session || employee;
  if (!target) return null;
  const fontSize = compact ? 11 : 12;
  return (
    <>
      {employee?.duration_label ? (
        <Typography sx={{ mt: 0.5, fontSize, color: "#64748b", fontWeight: 600 }}>
          Fold time {employee.duration_label}
        </Typography>
      ) : null}
      <Typography sx={{ mt: 0.35, fontSize, color: "#94a3b8", fontWeight: 600 }}>
        {target.time_range_label || "—"}
        {target.performance_through_label ? ` · ${target.performance_through_label}` : ""}
      </Typography>
    </>
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
        fontWeight: 700,
        color: up ? "#047857" : "#b91c1c",
      }}
    >
      {label} {text}
    </Typography>
  );
}

function WfEmployeeRankCard({ rank, employee, onOpenSession }) {
  const sessions = employee.sessions || [];
  return (
    <Box
      sx={{
        px: { xs: 1.25, sm: 1.5 },
        py: { xs: 1.15, sm: 1.35 },
        borderRadius: 2.5,
        bgcolor: "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Typography
          sx={{
            fontSize: 13,
            fontWeight: 800,
            color: VEEWASH_DASHBOARD.primaryBlue,
            minWidth: 28,
            pt: 0.15,
          }}
        >
          #{rank}
        </Typography>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="flex-start"
            spacing={1}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography
                sx={{
                  fontSize: { xs: 16, sm: 17 },
                  fontWeight: 800,
                  lineHeight: 1.2,
                  color: "#0f172a",
                }}
                noWrap
              >
                {employee.employee}
              </Typography>
              <Typography sx={{ mt: 0.35, fontSize: 13, color: "#64748b", fontWeight: 600 }}>
                {fmtCount(employee.orders_completed)} orders · {fmtLbs(employee.total_pre_lbs, { compact: true })}
              </Typography>
            </Box>
            <Box sx={{ textAlign: "right", flexShrink: 0 }}>
              <Typography
                sx={{
                  fontSize: { xs: 22, sm: 24 },
                  fontWeight: 800,
                  lineHeight: 1,
                  color: VEEWASH_DASHBOARD.primaryBlueDark,
                }}
              >
                {fmtRate(employee.lbs_per_hour, 0)}
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: 0.4 }}>
                lb/hr
              </Typography>
            </Box>
          </Stack>

          <Typography sx={{ mt: 0.65, fontSize: 13, fontWeight: 700, color: "#475569" }}>
            {fmtRate(employee.bags_per_hour)} bags/hr
          </Typography>

          <SessionTiming employee={employee} compact />

          <Stack spacing={0.15} sx={{ mt: 0.85 }}>
            {sessions.map((sess) => (
              <Box
                key={sess.session_id}
                component="button"
                type="button"
                onClick={() => onOpenSession(sess)}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 0.25,
                  m: 0,
                  p: 0,
                  border: "none",
                  bgcolor: "transparent",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: VEEWASH_DASHBOARD.primaryBlueDark,
                  fontWeight: 800,
                  fontSize: 13,
                  WebkitTapHighlightColor: "transparent",
                  "&:hover": { textDecoration: "underline" },
                }}
              >
                View {sess.orders_completed} order{sess.orders_completed === 1 ? "" : "s"}
                {sess.session_code ? ` · ${sess.session_code}` : ""}
                <ChevronRightIcon sx={{ fontSize: 16 }} />
              </Box>
            ))}
          </Stack>
        </Box>
      </Stack>
    </Box>
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
          <Typography sx={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>
            {order.customer_name || "Customer unavailable"}
          </Typography>
          <Typography sx={{ mt: 0.2, fontSize: 13, color: "#475569", fontWeight: 600 }}>
            {order.bag_id}
            {order.pre_lbs != null ? ` · ${fmtLbs(order.pre_lbs, { compact: true })}` : ""}
          </Typography>
          <Typography sx={{ mt: 0.15, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
            Fold complete · {timeLabel}
            {order.time_taken_label ? ` · ${order.time_taken_label}` : ""}
          </Typography>
          {(order.original_scanner && order.original_scanner !== order.credited_employee)
            || order.reassignment_indicator
            || order.unmapped_reason ? (
            <Typography sx={{ mt: 0.25, fontSize: 11, color: "#64748b" }}>
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

  const kpiLine = (
    <>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.orders_completed)} Orders
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtLbs(summary.total_pre_lbs, { compact: true })}
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography component="span" sx={{ fontWeight: 700, color: "#334155" }}>
        {fmtCount(summary.employee_count)} Employees
      </Typography>
      <Typography component="span" sx={{ mx: 0.75, color: "#cbd5e1" }}>
        ·
      </Typography>
      <Typography
        component="span"
        sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.primaryBlueDark, fontSize: { xs: 15, sm: 16 } }}
      >
        {fmtRate(summary.lbs_per_hour, 0)} lb/hr
      </Typography>
    </>
  );

  return (
    <Box sx={{ width: "100%", minWidth: 0, maxWidth: { md: 720 }, mx: { md: "auto" } }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        spacing={1}
        sx={{ mb: 1.25 }}
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
              border: "1px solid #e2e8f0",
              borderRadius: "50%",
              width: 32,
              height: 32,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              bgcolor: "#fff",
              cursor: "pointer",
              color: "#64748b",
            }}
          >
            <RefreshIcon sx={{ fontSize: 18 }} />
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
          <Box
            sx={{
              mb: 1.5,
              px: { xs: 1.25, sm: 1.5 },
              py: { xs: 1, sm: 1.15 },
              borderRadius: 2.5,
              bgcolor: "#fff",
              boxShadow: VEEWASH_DASHBOARD.cardShadow,
              fontSize: { xs: 13, sm: 14 },
              lineHeight: 1.5,
              flexWrap: "wrap",
            }}
          >
            {kpiLine}
            {deltas ? (
              <Stack direction="row" spacing={1.25} sx={{ mt: 0.65, flexWrap: "wrap" }}>
                <DeltaChip label="Bags/hr" pct={deltas.bags_per_hour_delta_pct} />
                <DeltaChip label="Lb/hr" pct={deltas.lbs_per_hour_delta_pct} />
              </Stack>
            ) : null}
          </Box>

          {unmappedCount > 0 ? (
            <Box sx={{ mb: 1.25 }}>
              <Button
                fullWidth
                onClick={() => setShowUnmapped((v) => !v)}
                sx={{
                  justifyContent: "space-between",
                  textTransform: "none",
                  fontWeight: 800,
                  fontSize: 13,
                  py: 1,
                  px: 1.25,
                  borderRadius: 2,
                  color: "#b45309",
                  bgcolor: showUnmapped ? "#fffbeb" : "#fff",
                  boxShadow: VEEWASH_DASHBOARD.cardShadow,
                  "&:hover": { bgcolor: "#fffbeb" },
                }}
              >
                Unmapped orders
                <Box component="span">{unmappedCount}</Box>
              </Button>
              {showUnmapped ? (
                <Box
                  sx={{
                    mt: 0.75,
                    px: 1.25,
                    py: 1,
                    borderRadius: 2,
                    bgcolor: "#fffbeb",
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                    <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#92400e" }}>
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
                        sx={{ textTransform: "none", fontWeight: 800 }}
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

          <Stack spacing={1}>
            {employees.map((emp, idx) => (
              <WfEmployeeRankCard
                key={emp.employee}
                rank={idx + 1}
                employee={emp}
                onOpenSession={openSession}
              />
            ))}
            {!loading && !employees.length ? (
              <Typography sx={{ py: 2, fontSize: 14, color: "#94a3b8", fontWeight: 600, textAlign: "center" }}>
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
            sx={{ textTransform: "none", fontWeight: 700 }}
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
