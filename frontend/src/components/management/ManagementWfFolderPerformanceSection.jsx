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
  postManagementPerformanceApproveSession,
  postManagementPerformanceApproveDay,
  postManagementPerformanceOverrideSession,
  postManagementPerformanceExcludeSession,
  postManagementPerformanceIncludeSession,
  putManagementFolderBenchmark,
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

function SessionLink({
  session,
  onOpenSession,
  onApprove,
  onEdit,
  onExclude,
  onInclude,
  approveBusy,
}) {
  const label = session.session_code
    ? `View ${session.session_code}`
    : `View ${session.orders_completed} order${session.orders_completed === 1 ? "" : "s"}`;
  const pub = session.publication_status || session.publication?.status || "UNAPPROVED";
  const isOpen = String(session.role_status || "").toLowerCase() === "open";
  const approved = pub === "APPROVED";
  const excluded = pub === "EXCLUDED";
  const calc =
    session.publication?.calculated_metric_value ??
    session.lbs_per_hour ??
    null;
  const approvedVal =
    session.publication?.published_metric_value ??
    (approved ? session.lbs_per_hour : null);
  const overridden = Boolean(session.publication?.is_rate_override);
  return (
    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
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
      <Typography sx={{ ...PERF_TYPE.meta, color: "#64748b" }}>
        Calc {fmtRate(calc)}
        {approved || excluded ? ` · Pub ${fmtRate(approvedVal)}` : ""}
        {overridden ? " · Override" : ""}
      </Typography>
      <Typography
        sx={{
          ...PERF_TYPE.meta,
          color: excluded ? "#b45309" : approved ? PERF_UI.tealDark : "#94a3b8",
          fontWeight: 700,
        }}
      >
        {excluded ? "Excluded" : approved ? "Approved" : "Unapproved"}
      </Typography>
      {!isOpen && !excluded ? (
        <Button
          size="small"
          variant="outlined"
          disabled={approveBusy}
          onClick={() => onEdit?.(session)}
          sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
        >
          Edit
        </Button>
      ) : null}
      <Button
        size="small"
        variant="outlined"
        disabled={approved || isOpen || approveBusy || excluded}
        onClick={() => onApprove?.(session)}
        sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
      >
        {isOpen ? "Open" : "Approve"}
      </Button>
      {!isOpen ? (
        <Button
          size="small"
          variant="text"
          disabled={approveBusy}
          onClick={() => (excluded ? onInclude?.(session) : onExclude?.(session))}
          sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
        >
          {excluded ? "Include" : "Exclude"}
        </Button>
      ) : null}
    </Stack>
  );
}

function WfEmployeeRankCard({
  rank,
  employee,
  onOpenSession,
  onApprove,
  onEdit,
  onExclude,
  onInclude,
  approveBusy,
}) {
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
              <SessionLink
                key={sess.session_id}
                session={sess}
                onOpenSession={onOpenSession}
                onApprove={onApprove}
                onEdit={onEdit}
                onExclude={onExclude}
                onInclude={onInclude}
                approveBusy={approveBusy}
              />
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
              <SessionLink
                session={sess}
                onOpenSession={onOpenSession}
                onApprove={onApprove}
                onEdit={onEdit}
                onExclude={onExclude}
                onInclude={onInclude}
                approveBusy={approveBusy}
              />
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
              {order.unmapped_reason === "OUTSIDE_FOLDER_SESSION"
                ? " · Outside recorded Folder session"
                : order.unmapped_reason
                  ? ` · ${order.unmapped_reason.replaceAll("_", " ")}`
                  : ""}
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
  const [showNeedsAttribution, setShowNeedsAttribution] = useState(false);
  const [showOutsideSession, setShowOutsideSession] = useState(false);
  const [sortBy, setSortBy] = useState("output");
  const [approveBusy, setApproveBusy] = useState(false);
  const [benchDraft, setBenchDraft] = useState("");
  const [pubMessage, setPubMessage] = useState("");
  const [editSession, setEditSession] = useState(null);
  const [editRate, setEditRate] = useState("");
  const [editReason, setEditReason] = useState("");

  const patchSessionPublication = (sessionId, publication) => {
    const sid = String(sessionId || "");
    const status = publication?.status || "UNAPPROVED";
    setData((prev) => {
      if (!prev) return prev;
      const patchOne = (s) =>
        String(s?.session_id || "") === sid
          ? {
              ...s,
              publication_status: status,
              publication: { ...(s.publication || {}), ...publication, status },
            }
          : s;
      return {
        ...prev,
        sessions: (prev.sessions || []).map(patchOne),
        employees: (prev.employees || []).map((e) => ({
          ...e,
          sessions: (e.sessions || []).map(patchOne),
        })),
      };
    });
  };

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
        const b = res.data?.folder_benchmark_lbs_hr;
        if (b != null) setBenchDraft(String(b));
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

  const sessionPublishPayload = (session) => ({
    session_id: session.session_id,
    session_code: session.session_code,
    segment_id: session.segment_id,
    user_id: session.user_id ?? session.employee_user_id,
    employee: session.employee,
    total_pre_lbs: session.total_pre_lbs,
    performance_hours: session.performance_hours,
    lbs_per_hour: session.lbs_per_hour,
    orders_completed: session.orders_completed,
    start_time: session.start_time,
    end_time: session.end_time,
    performance_end: session.performance_end,
    performance_basis: session.performance_basis,
    role_status: session.role_status,
  });

  const approveSession = async (session) => {
    if (!session?.session_id) return;
    setApproveBusy(true);
    setPubMessage("");
    setError("");
    try {
      const day = session.selected_date_et || dateEt;
      const res = await postManagementPerformanceApproveSession("FOLDER", session.session_id, {
        date_et: day,
        session: sessionPublishPayload(session),
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Approve failed");
        return;
      }
      setPubMessage(`Approved ${session.session_code || session.session_id}`);
      patchSessionPublication(
        session.session_id,
        body.publication || {
          status: "APPROVED",
          published_metric_value: body.published_metric_value,
          calculated_metric_value: body.calculated_metric_value ?? session.lbs_per_hour,
          is_rate_override: Boolean(body.is_rate_override),
          content_fingerprint: body.content_fingerprint,
        }
      );
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Approve failed");
    } finally {
      setApproveBusy(false);
    }
  };

  const openEdit = (session) => {
    const pub = session.publication || {};
    const seed =
      pub.published_metric_value ??
      pub.calculated_metric_value ??
      session.lbs_per_hour ??
      "";
    setEditSession(session);
    setEditRate(String(seed));
    setEditReason(pub.override_reason || "");
  };

  const saveEdit = async ({ andApprove = false } = {}) => {
    if (!editSession?.session_id) return;
    const rate = Number(editRate);
    if (!Number.isFinite(rate) || rate < 0) {
      setError("Manager approved rate must be a non-negative number");
      return;
    }
    setApproveBusy(true);
    setError("");
    try {
      const day = editSession.selected_date_et || dateEt;
      const res = await postManagementPerformanceOverrideSession("FOLDER", editSession.session_id, {
        date_et: day,
        published_metric_value: rate,
        reason: editReason || undefined,
        approve_if_needed: true,
        session: sessionPublishPayload(editSession),
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Save failed");
        return;
      }
      setPubMessage(`Saved manager value for ${editSession.session_code || editSession.session_id}`);
      patchSessionPublication(
        editSession.session_id,
        body.publication || {
          status: "APPROVED",
          published_metric_value: body.published_metric_value,
          calculated_metric_value: body.calculated_metric_value,
          is_rate_override: true,
        }
      );
      setEditSession(null);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setApproveBusy(false);
    }
  };

  const excludeSession = async (session) => {
    if (!session?.session_id) return;
    setApproveBusy(true);
    setError("");
    try {
      const res = await postManagementPerformanceExcludeSession("FOLDER", session.session_id, {
        date_et: session.selected_date_et || dateEt,
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Exclude failed");
        return;
      }
      setPubMessage(`Excluded ${session.session_code || session.session_id}`);
      patchSessionPublication(session.session_id, body.publication || { status: "EXCLUDED", excluded: true });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Exclude failed");
    } finally {
      setApproveBusy(false);
    }
  };

  const includeSession = async (session) => {
    if (!session?.session_id) return;
    setApproveBusy(true);
    setError("");
    try {
      const res = await postManagementPerformanceIncludeSession("FOLDER", session.session_id, {});
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Include failed");
        return;
      }
      setPubMessage(`Included ${session.session_code || session.session_id}`);
      patchSessionPublication(session.session_id, body.publication || { status: "APPROVED" });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Include failed");
    } finally {
      setApproveBusy(false);
    }
  };

  const approveDay = async () => {
    setApproveBusy(true);
    setPubMessage("");
    setError("");
    try {
      const res = await postManagementPerformanceApproveDay("FOLDER", dateEt, {});
      const s = res.data || {};
      if (!s.ok) {
        setError(s.error || "Approve Day failed");
        return;
      }
      setPubMessage(
        `Approve Day: ${s.approved || 0} approved · ${s.already_approved || 0} already · ${s.open || 0} open · ${s.invalid_empty || 0} invalid`
      );
      for (const row of s.results || []) {
        if (!row?.session_id || !row.ok) continue;
        patchSessionPublication(
          row.session_id,
          row.publication || {
            status: "APPROVED",
            published_metric_value: row.published_metric_value,
            content_fingerprint: row.content_fingerprint,
          }
        );
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Approve Day failed");
    } finally {
      setApproveBusy(false);
    }
  };

  const saveBenchmark = async () => {
    const n = Number(benchDraft);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Benchmark must be a positive number");
      return;
    }
    setApproveBusy(true);
    try {
      await putManagementFolderBenchmark({ lbs_per_hour_target: n });
      setPubMessage(`Folder benchmark set to ${n} lb/hr`);
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Benchmark save failed");
    } finally {
      setApproveBusy(false);
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
  const needsAttribution = data?.needs_attribution_orders || [];
  const needsAttributionCount = data?.needs_attribution_count || 0;
  const outsideFolderSession = data?.outside_folder_session_orders || [];
  const outsideFolderSessionCount = data?.outside_folder_session_count || 0;

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
          <Button
            size="small"
            variant="contained"
            disabled={approveBusy || loading}
            onClick={approveDay}
            sx={{ textTransform: "none", fontWeight: 700, bgcolor: PERF_UI.teal, "&:hover": { bgcolor: PERF_UI.tealDark } }}
          >
            Approve Day
          </Button>
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
      {pubMessage ? (
        <Alert severity="success" sx={{ mb: 1.25, py: 0.5 }} onClose={() => setPubMessage("")}>
          {pubMessage}
        </Alert>
      ) : null}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Typography sx={{ ...PERF_TYPE.meta, fontWeight: 700 }}>Folder Benchmark</Typography>
        <TextField
          size="small"
          value={benchDraft}
          onChange={(e) => setBenchDraft(e.target.value)}
          sx={{ width: 88 }}
          inputProps={{ "aria-label": "Folder benchmark lb/hr" }}
        />
        <Typography sx={PERF_TYPE.meta}>lb/hr</Typography>
        <Button size="small" variant="outlined" disabled={approveBusy} onClick={saveBenchmark} sx={{ textTransform: "none" }}>
          Save
        </Button>
      </Stack>

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

          {needsAttributionCount > 0 ? (
            <Box sx={{ mb: 0.85 }}>
              <Button
                fullWidth
                onClick={() => setShowNeedsAttribution((v) => !v)}
                sx={{
                  justifyContent: "space-between",
                  textTransform: "none",
                  fontWeight: 500,
                  fontSize: 12,
                  py: 0.65,
                  px: 1,
                  borderRadius: 1.25,
                  color: "#9a6700",
                  bgcolor: showNeedsAttribution ? "rgba(180, 83, 9, 0.08)" : PERF_UI.rowBg,
                  border: `1px solid ${PERF_UI.rowBorder}`,
                  boxShadow: "none",
                  "&:hover": { bgcolor: "rgba(180, 83, 9, 0.08)" },
                }}
              >
                Needs Attribution
                <Box component="span" sx={{ fontWeight: 600 }}>
                  {needsAttributionCount}
                </Box>
              </Button>
              {showNeedsAttribution ? (
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
                      Reassign orders with no provable folder employee
                    </Typography>
                    <Stack direction="row" spacing={0.5}>
                      <Button
                        size="small"
                        onClick={() => selectAllVisible(needsAttribution)}
                        sx={{ textTransform: "none" }}
                      >
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
                  {needsAttribution.map((o) => (
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

          {outsideFolderSessionCount > 0 ? (
            <Box sx={{ mb: 0.85 }}>
              <Button
                fullWidth
                onClick={() => setShowOutsideSession((v) => !v)}
                sx={{
                  justifyContent: "space-between",
                  textTransform: "none",
                  fontWeight: 500,
                  fontSize: 12,
                  py: 0.65,
                  px: 1,
                  borderRadius: 1.25,
                  color: "#475569",
                  bgcolor: showOutsideSession ? "rgba(71, 85, 105, 0.08)" : PERF_UI.rowBg,
                  border: `1px solid ${PERF_UI.rowBorder}`,
                  boxShadow: "none",
                  "&:hover": { bgcolor: "rgba(71, 85, 105, 0.08)" },
                }}
              >
                Outside Folder Session
                <Box component="span" sx={{ fontWeight: 600 }}>
                  {outsideFolderSessionCount}
                </Box>
              </Button>
              {showOutsideSession ? (
                <Box
                  sx={{
                    mt: 0.45,
                    px: 1,
                    py: 0.75,
                    borderRadius: 1.25,
                    bgcolor: "rgba(71, 85, 105, 0.05)",
                    border: `1px solid rgba(71, 85, 105, 0.12)`,
                  }}
                >
                  <Typography sx={{ fontSize: 12, fontWeight: 500, color: "#475569", mb: 0.5 }}>
                    Employee is known — fold occurred outside their recorded Folder session
                  </Typography>
                  {outsideFolderSession.map((o) => (
                    <OrderRow
                      key={o.bag_id}
                      order={{
                        ...o,
                        unmapped_reason: "OUTSIDE_FOLDER_SESSION",
                      }}
                      selectable={false}
                      selected={false}
                      onToggle={() => {}}
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
                onApprove={approveSession}
                onEdit={openEdit}
                onExclude={excludeSession}
                onInclude={includeSession}
                approveBusy={approveBusy}
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

      <Dialog open={!!editSession} onClose={() => setEditSession(null)} fullWidth maxWidth="xs">
        <DialogTitle>Manager approved value</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>
              {editSession?.employee} · {editSession?.session_code || editSession?.session_id}
            </Typography>
            <Typography sx={{ fontSize: 13 }}>
              Calculated: {fmtRate(editSession?.lbs_per_hour)} lb/hr
            </Typography>
            <TextField
              label="Manager Approved (lb/hr)"
              value={editRate}
              onChange={(e) => setEditRate(e.target.value)}
              size="small"
              type="number"
              inputProps={{ min: 0, step: 0.1 }}
            />
            <TextField
              label="Reason / note (optional)"
              value={editReason}
              onChange={(e) => setEditReason(e.target.value)}
              size="small"
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditSession(null)} disabled={approveBusy}>
            Cancel
          </Button>
          <Button onClick={() => saveEdit({ andApprove: true })} disabled={approveBusy} variant="contained">
            Save & Approve
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
