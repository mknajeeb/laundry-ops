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
  FormControlLabel,
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
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getManagementWfFolderPerformance,
  getManagementWfFolderSessionOrders,
  getManagementWfFolderDestinations,
  postManagementWfFolderAttributionMove,
  postManagementWfFolderAttributionReset,
  postManagementPerformanceApproveSession,
  postManagementPerformanceApproveDay,
  postManagementPerformanceApproveEmployeeDay,
  postManagementPerformanceExcludeEmployeeDay,
  postManagementPerformanceIncludeEmployeeDay,
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
import {
  PERF_TYPE,
  PERF_UI,
  PerfSeparator,
  perfKpiCellSx,
  perfKpiGridSx,
  perfKpiInlineSx,
  perfKpiStripSx,
  perfRowSx,
} from "./performance/performanceTokens";
import { fmtCount, fmtDelta, fmtHours, fmtLbs, fmtRate } from "./performance/performanceFormat";
import { displayCustomerName } from "../../utils/displayCustomerName";
import { orderDisplayIdFromRow } from "../../utils/orderDisplayId";

function apiErr(err, fallback = "Request failed") {
  const d = err?.response?.data;
  if (!d) return err?.message || fallback;
  return d.error || d.message || d.status || err?.message || fallback;
}

function dayStatusLabel(status) {
  switch (String(status || "").toUpperCase()) {
    case "APPROVED":
      return "Approved";
    case "PARTIALLY_APPROVED":
      return "Partially approved";
    case "EXCLUDED":
      return "Excluded";
    case "NEEDS_APPROVAL":
    case "UNAPPROVED":
    default:
      return "Needs approval";
  }
}

function dayStatusColor(status) {
  switch (String(status || "").toUpperCase()) {
    case "APPROVED":
      return PERF_UI.tealDark;
    case "PARTIALLY_APPROVED":
      return "#b45309";
    case "EXCLUDED":
      return "#92400e";
    default:
      return "#94a3b8";
  }
}

const GRAPH_METRICS = [
  { value: "lbs_hr", label: "Lb/hr", field: "lbs_per_hour" },
  { value: "bags_hr", label: "Bags/hr", field: "bags_per_hour" },
  { value: "pounds", label: "Pounds", field: "total_pre_lbs" },
  { value: "orders", label: "Orders", field: "orders_completed" },
];

const SORT_OPTIONS = [
  { value: "lbs_hr", label: "Highest lb/hr" },
  { value: "orders", label: "Most orders" },
  { value: "pounds", label: "Most pounds" },
  { value: "bags_hr", label: "Highest bags/hr" },
];

function sessionPublishPayload(session) {
  return {
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
    include_in_authoritative_aggregate: session.include_in_authoritative_aggregate,
  };
}

function WfEmployeeDayRow({
  rank,
  employee,
  onReview,
  onApproveDay,
  onExcludeDay,
  onIncludeDay,
  approveBusy,
}) {
  const status = employee.day_publication_status || employee.publication_status || "NEEDS_APPROVAL";
  const excluded = status === "EXCLUDED";
  const approved = status === "APPROVED";
  const hours = employee.performance_hours ?? employee.session_hours;
  const statsLine = `${fmtCount(employee.orders_completed)} orders · ${fmtLbs(employee.total_pre_lbs, {
    compact: true,
  })} · ${fmtHours(hours)} · ${fmtRate(employee.bags_per_hour)} bags/hr`;
  const metaParts = [employee.time_range_label, employee.duration_label].filter(Boolean);
  const sessionCount = employee.session_count || (employee.sessions || []).length;

  return (
    <Box sx={perfRowSx()}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        alignItems={{ xs: "stretch", md: "baseline" }}
        spacing={0.75}
        useFlexGap
        flexWrap="wrap"
      >
        <Typography sx={{ ...PERF_TYPE.name, minWidth: 0 }} noWrap>
          <Box component="span" sx={PERF_TYPE.rank}>
            #{rank}{" "}
          </Box>
          {employee.employee}
        </Typography>
        <Typography sx={PERF_TYPE.body}>{statsLine}</Typography>
        <Box sx={{ flex: 1, minWidth: 8 }} />
        <Typography sx={PERF_TYPE.metricPrimary} whiteSpace="nowrap">
          {fmtRate(employee.lbs_per_hour, 0)}{" "}
          <Box component="span" sx={PERF_TYPE.metricLabel}>
            lb/hr
          </Box>
        </Typography>
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 0.35 }}>
        {metaParts.length ? (
          <Typography sx={PERF_TYPE.meta}>{metaParts.join(" · ")}</Typography>
        ) : null}
        {sessionCount ? (
          <Typography sx={PERF_TYPE.meta}>
            {sessionCount} session{sessionCount === 1 ? "" : "s"}
          </Typography>
        ) : null}
        <Typography sx={{ ...PERF_TYPE.meta, color: dayStatusColor(status), fontWeight: 700 }}>
          {dayStatusLabel(status)}
        </Typography>
        <Button
          size="small"
          variant="outlined"
          disabled={approveBusy}
          onClick={() => onReview?.(employee)}
          sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
        >
          Review
        </Button>
        {!excluded && !approved ? (
          <Button
            size="small"
            variant="outlined"
            disabled={approveBusy}
            onClick={() => onApproveDay?.(employee)}
            sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
          >
            Approve
          </Button>
        ) : null}
        <Button
          size="small"
          variant="text"
          disabled={approveBusy}
          onClick={() => (excluded ? onIncludeDay?.(employee) : onExcludeDay?.(employee))}
          sx={{ minHeight: 28, py: 0, px: 1, fontSize: 11, textTransform: "none" }}
        >
          {excluded ? "Include" : "Exclude"}
        </Button>
      </Stack>
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
            {orderDisplayIdFromRow(order) || order.bag_id}
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
  const [sortBy, setSortBy] = useState("lbs_hr");
  const [approveBusy, setApproveBusy] = useState(false);
  const [benchDraft, setBenchDraft] = useState("");
  const [pubMessage, setPubMessage] = useState("");
  const [editSession, setEditSession] = useState(null);
  const [editRate, setEditRate] = useState("");
  const [editReason, setEditReason] = useState("");
  const [showExcluded, setShowExcluded] = useState(false);
  const [roleKey, setRoleKey] = useState("FOLDER");
  const [employeeFilter, setEmployeeFilter] = useState("all");
  const [graphMetric, setGraphMetric] = useState("lbs_hr");
  const [reviewEmployee, setReviewEmployee] = useState(null);

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
        const nextCompare = opts.compare ?? compare;
        const nextLastN = opts.last_n ?? lastN;
        const wantBaseline =
          opts.include_baseline != null
            ? Boolean(Number(opts.include_baseline))
            : false;
        const res = await getManagementWfFolderPerformance(dateEt, {
          compare: nextCompare,
          last_n: nextLastN,
          include_baseline: wantBaseline ? 1 : 0,
        });
        setData(res.data || null);
        const b = res.data?.folder_benchmark_lbs_hr;
        if (b != null) setBenchDraft(String(b));
        // Lazy baseline deltas for Today — do not block first paint.
        if (
          nextCompare === "today" &&
          !wantBaseline &&
          !(opts && opts.skip_lazy_baseline)
        ) {
          getManagementWfFolderPerformance(dateEt, {
            compare: "today",
            last_n: nextLastN,
            include_baseline: 1,
          })
            .then((deltaRes) => {
              const deltas = deltaRes?.data?.deltas;
              if (!deltas) return;
              setData((prev) => (prev ? { ...prev, deltas } : prev));
            })
            .catch(() => {
              /* deltas optional */
            });
        }
      } catch (err) {
        setError(apiErr(err, "Unable to load Folder Performance"));
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
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Approve failed"));
    } finally {
      setApproveBusy(false);
    }
  };

  const approveEmployeeDay = async (employee) => {
    if (!employee) return;
    setApproveBusy(true);
    setPubMessage("");
    setError("");
    try {
      const res = await postManagementPerformanceApproveEmployeeDay("FOLDER", {
        date_et: dateEt,
        user_id: employee.user_id,
        employee: employee.employee,
        sessions: (employee.sessions || []).map(sessionPublishPayload),
      });
      const body = res.data || {};
      if (body.ok === false && body.status === "employee_not_found") {
        setError(body.error || "Employee not found for this day");
        return;
      }
      setPubMessage(
        `Approved ${employee.employee}: ${body.approved || 0} session(s)` +
          (body.already_approved ? ` · ${body.already_approved} already` : "")
      );
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Approve employee day failed"));
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

  const saveEdit = async () => {
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
      setEditSession(null);
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Save failed"));
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
        session: sessionPublishPayload(session),
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Exclude failed");
        return;
      }
      setPubMessage(`Excluded ${session.session_code || session.session_id}`);
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Exclude failed"));
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
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Include failed"));
    } finally {
      setApproveBusy(false);
    }
  };

  const excludeEmployeeDay = async (employee) => {
    if (!employee) return;
    setApproveBusy(true);
    setError("");
    try {
      const res = await postManagementPerformanceExcludeEmployeeDay("FOLDER", {
        date_et: dateEt,
        user_id: employee.user_id,
        employee: employee.employee,
        sessions: (employee.sessions || []).map(sessionPublishPayload),
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Exclude failed");
        return;
      }
      setPubMessage(`Excluded ${employee.employee} for ${dateEt}`);
      setReviewEmployee(null);
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Exclude failed"));
    } finally {
      setApproveBusy(false);
    }
  };

  const includeEmployeeDay = async (employee) => {
    if (!employee) return;
    setApproveBusy(true);
    setError("");
    try {
      const res = await postManagementPerformanceIncludeEmployeeDay("FOLDER", {
        user_id: employee.user_id,
        employee: employee.employee,
        sessions: employee.sessions || [],
        session_ids: (employee.sessions || []).map((s) => s.session_id).filter(Boolean),
      });
      const body = res.data || {};
      if (!body.ok) {
        setError(body.error || body.status || "Include failed");
        return;
      }
      setPubMessage(`Included ${employee.employee}`);
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Include failed"));
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
      if (s.ok === false) {
        setError(s.error || "Approve Day failed");
        return;
      }
      setPubMessage(
        `Approve Day: ${s.approved || 0} approved · ${s.already_approved || 0} already · ${s.open || 0} open · ${s.invalid_empty || 0} invalid`
      );
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Approve Day failed"));
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
      await load({ skip_lazy_baseline: true });
    } catch (err) {
      setError(apiErr(err, "Benchmark save failed"));
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
    const active = [...(data?.employees || [])];
    const excluded = [...(data?.excluded_employees || [])];
    let rows = showExcluded ? [...active, ...excluded] : active;
    if (employeeFilter !== "all") {
      rows = rows.filter(
        (e) =>
          String(e.user_id) === String(employeeFilter) ||
          String(e.employee) === String(employeeFilter)
      );
    }
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
  }, [data?.employees, data?.excluded_employees, sortBy, showExcluded, employeeFilter]);

  const employeeOptions = useMemo(() => {
    const all = [...(data?.employees || []), ...(data?.excluded_employees || [])];
    return all
      .map((e) => ({
        value: e.user_id != null ? String(e.user_id) : e.employee,
        label: e.employee,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [data?.employees, data?.excluded_employees]);

  const graphRows = useMemo(() => {
    const field = GRAPH_METRICS.find((m) => m.value === graphMetric)?.field || "lbs_per_hour";
    return employees.map((e) => ({
      name: String(e.employee || "").replace(/\s*\(.*?\)\s*/g, "").trim() || e.employee,
      value: Number(e[field]) || 0,
      full: e.employee,
    }));
  }, [employees, graphMetric]);

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
            options={SORT_OPTIONS}
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
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel id="perf-role">Role</InputLabel>
          <Select
            labelId="perf-role"
            label="Role"
            value={roleKey}
            onChange={(e) => setRoleKey(e.target.value)}
          >
            <MenuItem value="FOLDER">Folder</MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="perf-emp">Employee</InputLabel>
          <Select
            labelId="perf-emp"
            label="Employee"
            value={employeeFilter}
            onChange={(e) => setEmployeeFilter(e.target.value)}
          >
            <MenuItem value="all">All employees</MenuItem>
            {employeeOptions.map((o) => (
              <MenuItem key={o.value} value={o.value}>
                {o.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel id="perf-metric">Graph</InputLabel>
          <Select
            labelId="perf-metric"
            label="Graph"
            value={graphMetric}
            onChange={(e) => setGraphMetric(e.target.value)}
          >
            {GRAPH_METRICS.map((m) => (
              <MenuItem key={m.value} value={m.value}>
                {m.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControlLabel
          control={
            <Checkbox
              size="small"
              checked={showExcluded}
              onChange={(e) => setShowExcluded(e.target.checked)}
            />
          }
          label={<Typography sx={{ fontSize: 12 }}>Show excluded</Typography>}
        />
      </Stack>
      <Typography sx={{ ...PERF_TYPE.meta, mb: 1 }}>
        Folder is the live productivity role (lb/hr · bags/hr). Other roles are reserved until publishers exist.
        {data?.excluded_employee_count
          ? ` · ${data.excluded_employee_count} excluded employee-day(s) hidden by default.`
          : ""}
      </Typography>

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

          {employeeFilter === "all" && graphRows.length ? (
            <Box
              sx={{
                mb: 1.25,
                px: 0.5,
                py: 1,
                borderRadius: 1.25,
                bgcolor: PERF_UI.rowBg,
                border: `1px solid ${PERF_UI.rowBorder}`,
                height: Math.max(220, Math.min(480, 28 * graphRows.length + 60)),
              }}
            >
              <Typography sx={{ ...PERF_TYPE.meta, px: 1, mb: 0.5, fontWeight: 700 }}>
                All employees · {GRAPH_METRICS.find((m) => m.value === graphMetric)?.label || "Lb/hr"}
              </Typography>
              <ResponsiveContainer width="100%" height="90%">
                <BarChart
                  data={graphRows}
                  layout="vertical"
                  margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={88}
                    tick={{ fontSize: 11 }}
                    interval={0}
                  />
                  <Tooltip
                    formatter={(v) => [fmtRate(v), GRAPH_METRICS.find((m) => m.value === graphMetric)?.label]}
                    labelFormatter={(_, p) => p?.[0]?.payload?.full || ""}
                  />
                  <Bar dataKey="value" fill={PERF_UI.teal} radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Box>
          ) : null}

          <Stack spacing={0.3}>
            {employees.map((emp, idx) => (
              <WfEmployeeDayRow
                key={`${emp.user_id || emp.employee}-${idx}`}
                rank={idx + 1}
                employee={emp}
                onReview={setReviewEmployee}
                onApproveDay={approveEmployeeDay}
                onExcludeDay={excludeEmployeeDay}
                onIncludeDay={includeEmployeeDay}
                approveBusy={approveBusy}
              />
            ))}
            {!loading && !employees.length ? (
              <Typography sx={{ py: 2, ...PERF_TYPE.body, textAlign: "center" }}>
                No Wash & Fold folder employee-days for this window
                {showExcluded ? "" : " (excluded rows hidden)"}.
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

      <Dialog
        open={!!reviewEmployee}
        onClose={() => setReviewEmployee(null)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>
          Review · {reviewEmployee?.employee}
          <Typography sx={{ ...PERF_TYPE.meta, mt: 0.35 }}>
            {dayStatusLabel(
              reviewEmployee?.day_publication_status || reviewEmployee?.publication_status
            )}{" "}
            · {fmtCount(reviewEmployee?.orders_completed)} orders ·{" "}
            {fmtLbs(reviewEmployee?.total_pre_lbs, { compact: true })} ·{" "}
            {fmtRate(reviewEmployee?.lbs_per_hour)} lb/hr
          </Typography>
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.25}>
            {(reviewEmployee?.sessions || []).map((sess) => {
              const pub = sess.publication_status || sess.publication?.status || "UNAPPROVED";
              const isOpen = String(sess.role_status || "").toLowerCase() === "open";
              return (
                <Box
                  key={sess.session_id}
                  sx={{
                    p: 1,
                    borderRadius: 1,
                    border: `1px solid ${PERF_UI.rowBorder}`,
                    bgcolor: PERF_UI.rowBg,
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="baseline">
                    <Typography sx={{ fontWeight: 700, fontSize: 13 }}>
                      {sess.session_code || sess.session_id}
                    </Typography>
                    <Typography sx={{ fontSize: 12, color: dayStatusColor(pub), fontWeight: 700 }}>
                      {pub === "UNAPPROVED" ? "Unapproved" : dayStatusLabel(pub)}
                    </Typography>
                  </Stack>
                  <Typography sx={{ ...PERF_TYPE.meta, mt: 0.25 }}>
                    Calc {fmtRate(sess.lbs_per_hour)} · Pub{" "}
                    {fmtRate(sess.publication?.published_metric_value ?? sess.lbs_per_hour)} ·{" "}
                    {fmtCount(sess.orders_completed)} orders · {fmtLbs(sess.total_pre_lbs, { compact: true })} ·{" "}
                    {fmtHours(sess.performance_hours)}
                  </Typography>
                  <Stack direction="row" spacing={0.75} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
                    <Button
                      size="small"
                      sx={{ textTransform: "none" }}
                      onClick={() => openSession({ ...sess, employee: reviewEmployee.employee })}
                    >
                      Orders
                      <ChevronRightIcon sx={{ fontSize: 14 }} />
                    </Button>
                    {!isOpen && pub !== "EXCLUDED" ? (
                      <Button
                        size="small"
                        sx={{ textTransform: "none" }}
                        disabled={approveBusy}
                        onClick={() => openEdit({ ...sess, employee: reviewEmployee.employee })}
                      >
                        Edit
                      </Button>
                    ) : null}
                    {!isOpen && pub !== "APPROVED" && pub !== "EXCLUDED" ? (
                      <Button
                        size="small"
                        sx={{ textTransform: "none" }}
                        disabled={approveBusy}
                        onClick={() => approveSession({ ...sess, employee: reviewEmployee.employee })}
                      >
                        Approve
                      </Button>
                    ) : null}
                    {!isOpen ? (
                      <Button
                        size="small"
                        sx={{ textTransform: "none" }}
                        disabled={approveBusy}
                        onClick={() =>
                          pub === "EXCLUDED"
                            ? includeSession(sess)
                            : excludeSession({ ...sess, employee: reviewEmployee.employee })
                        }
                      >
                        {pub === "EXCLUDED" ? "Include" : "Exclude"}
                      </Button>
                    ) : null}
                  </Stack>
                </Box>
              );
            })}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReviewEmployee(null)}>Close</Button>
          {String(reviewEmployee?.day_publication_status) === "EXCLUDED" ? (
            <Button
              variant="contained"
              disabled={approveBusy}
              onClick={() => includeEmployeeDay(reviewEmployee)}
            >
              Include again
            </Button>
          ) : (
            <>
              <Button disabled={approveBusy} onClick={() => excludeEmployeeDay(reviewEmployee)}>
                Exclude day
              </Button>
              <Button
                variant="contained"
                disabled={approveBusy || reviewEmployee?.day_publication_status === "APPROVED"}
                onClick={() => approveEmployeeDay(reviewEmployee)}
              >
                Approve day
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>

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
          <Button onClick={() => saveEdit()} disabled={approveBusy} variant="contained">
            Save & Approve
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
