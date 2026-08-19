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
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  getManagementWfFolderPerformance,
  getManagementWfFolderSessionOrders,
  getManagementWfFolderDestinations,
  postManagementWfFolderAttributionMove,
  postManagementWfFolderAttributionReset,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

function fmtRate(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

function fmtLbs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })} lb`;
}

function fmtDelta(pct) {
  if (pct == null || Number.isNaN(Number(pct))) return null;
  const n = Number(pct);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(0)}%`;
}

function SessionTiming({ session, employee }) {
  const target = session || employee;
  if (!target) return null;
  return (
    <>
      <Typography sx={{ mt: 1, fontSize: 12, color: "#475569", fontWeight: 600 }}>
        {target.time_range_label || "—"}
        {target.duration_label && !target.performance_through_label
          ? ` · ${target.duration_label}`
          : ""}
      </Typography>
      {target.performance_through_label ? (
        <Typography sx={{ mt: 0.25, fontSize: 11, color: "#64748b", fontWeight: 600 }}>
          {target.performance_through_label}
          {target.duration_label ? ` · ${target.duration_label}` : ""}
        </Typography>
      ) : null}
    </>
  );
}

function DeltaChip({ label, pct }) {
  const text = fmtDelta(pct);
  if (!text) return null;
  const up = Number(pct) >= 0;
  return (
    <Box
      sx={{
        px: 0.85,
        py: 0.35,
        borderRadius: 1,
        bgcolor: up ? "#ecfdf5" : "#fef2f2",
        color: up ? "#047857" : "#b91c1c",
        fontSize: 11,
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      {label} {text}
    </Box>
  );
}

function SessionCard({ session, onOpen, selectedIds, onToggle }) {
  const checked = selectedIds?.has?.(session._selectKey);
  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontSize: 16, fontWeight: 800, lineHeight: 1.15 }}>
            {session.employee}
          </Typography>
          <Typography sx={{ mt: 0.35, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            {session.orders_completed} Orders · {fmtLbs(session.total_pre_lbs)}
          </Typography>
        </Box>
        {onToggle ? (
          <Checkbox
            size="small"
            checked={!!checked}
            onChange={() => onToggle(session._selectKey)}
            sx={{ p: 0.25 }}
          />
        ) : null}
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
        <Box>
          <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1 }}>
            {fmtRate(session.bags_per_hour)}
          </Typography>
          <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
            bags/hr
          </Typography>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1 }}>
            {fmtRate(session.lbs_per_hour, 0)}
          </Typography>
          <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
            lb/hr
          </Typography>
        </Box>
      </Stack>

      <SessionTiming session={session} />

      <Button
        size="small"
        onClick={() => onOpen(session)}
        sx={{
          mt: 0.75,
          px: 0,
          minWidth: 0,
          fontWeight: 800,
          textTransform: "none",
          color: VEEWASH_DASHBOARD.primaryBlueDark,
        }}
      >
        View {session.orders_completed} Orders →
      </Button>
    </Box>
  );
}

function EmployeeCard({ employee, onOpenSession }) {
  const primary = (employee.sessions || [])[0];
  return (
    <Box
      sx={{
        p: 1.35,
        borderRadius: 2,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
      }}
    >
      <Typography sx={{ fontSize: 18, fontWeight: 800, lineHeight: 1.1 }}>
        {employee.employee}
      </Typography>
      <Typography sx={{ mt: 0.4, fontSize: 13, color: "#64748b", fontWeight: 600 }}>
        {employee.orders_completed} Orders · {fmtLbs(employee.total_pre_lbs)}
      </Typography>

      <Stack direction="row" spacing={2.5} sx={{ mt: 1.1 }}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1 }}>
            {fmtRate(employee.bags_per_hour)}
          </Typography>
          <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
            bags/hr
          </Typography>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1 }}>
            {fmtRate(employee.lbs_per_hour, 0)}
          </Typography>
          <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
            lb/hr
          </Typography>
        </Box>
      </Stack>

      <SessionTiming employee={employee} />

      {(employee.sessions || []).map((sess) => (
        <Button
          key={sess.session_id}
          size="small"
          onClick={() => onOpenSession(sess)}
          sx={{
            mt: 0.5,
            px: 0,
            display: "block",
            minWidth: 0,
            fontWeight: 800,
            textTransform: "none",
            color: VEEWASH_DASHBOARD.primaryBlueDark,
          }}
        >
          View {sess.orders_completed} Orders
          {sess.session_code ? ` · ${sess.session_code}` : ""} →
        </Button>
      ))}
    </Box>
  );
}

function OrderRow({ order, selectable, selected, onToggle }) {
  return (
    <Box
      sx={{
        py: 1,
        borderBottom: "1px solid #f1f5f9",
      }}
    >
      <Stack direction="row" spacing={1} alignItems="flex-start">
        {selectable ? (
          <Checkbox
            size="small"
            checked={selected}
            onChange={() => onToggle(order.bag_id)}
            sx={{ p: 0.25, mt: 0.1 }}
          />
        ) : null}
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" justifyContent="space-between" spacing={1}>
            <Typography sx={{ fontSize: 13, fontWeight: 800 }}>{order.bag_id}</Typography>
            <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>
              {fmtLbs(order.pre_lbs)}
            </Typography>
          </Stack>
          <Typography sx={{ fontSize: 12, color: "#64748b" }}>{order.customer_name}</Typography>
          <Typography sx={{ mt: 0.25, fontSize: 11, color: "#475569" }}>
            {formatFriendlyEtWall(order.completion_time_et) || order.completion_time_et || "—"}
            {order.time_taken_label ? ` · ${order.time_taken_label}` : ""}
          </Typography>
          <Typography sx={{ mt: 0.2, fontSize: 11, color: "#64748b" }}>
            Credited: {order.credited_employee || "—"}
            {order.original_scanner && order.original_scanner !== order.credited_employee
              ? ` · Scanner: ${order.original_scanner}`
              : ""}
            {order.reassignment_indicator ? " · Reassigned" : ""}
          </Typography>
          {order.unmapped_reason ? (
            <Typography sx={{ mt: 0.2, fontSize: 11, color: "#b45309", fontWeight: 700 }}>
              {order.unmapped_reason.replaceAll("_", " ")}
            </Typography>
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
            <Select
              label="Employee"
              value={employee}
              onChange={(e) => setEmployee(e.target.value)}
            >
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

/**
 * Management → Performance → WF Folder Performance (mobile-first).
 */
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

  const openMove = async (ordersSource) => {
    const ids = [...selectedBagIds];
    if (!ids.length && ordersSource?.length) {
      // no-op guard
    }
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

  const presets = data?.ui_presets || [
    { key: "today", label: "Today" },
    { key: "same_weekday_last_week", label: "Same Day Last Week" },
    { key: "7d", label: "7 Days" },
    { key: "30d", label: "30 Days" },
    { key: "last_n", label: "Last N" },
  ];

  const summary = data?.summary || {};
  const deltas = data?.deltas;
  const unmapped = data?.unmapped_orders || [];
  const unmappedCount = data?.unmapped_count || 0;

  return (
    <Box sx={{ maxWidth: 430, mx: "auto", width: "100%" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Box>
          <Typography sx={{ fontSize: 18, fontWeight: 800 }}>WF Folder Performance</Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            PRE lb · RINSE_WF / FOLDER sessions
          </Typography>
        </Box>
        <IconButton size="small" onClick={() => load()} aria-label="Refresh">
          <RefreshIcon fontSize="small" />
        </IconButton>
      </Stack>

      <Box
        sx={{
          display: "flex",
          gap: 0.5,
          overflowX: "auto",
          pb: 0.5,
          mb: 1,
          WebkitOverflowScrolling: "touch",
          "&::-webkit-scrollbar": { display: "none" },
        }}
      >
        {presets.map((p) => {
          const active = compare === p.key;
          return (
            <Box
              key={p.key}
              component="button"
              type="button"
              onClick={() => {
                setCompare(p.key);
                load({ compare: p.key });
              }}
              sx={{
                flex: "0 0 auto",
                appearance: "none",
                border: "1px solid",
                borderColor: active ? VEEWASH_DASHBOARD.primaryBlue : "#e5e7eb",
                bgcolor: active ? VEEWASH_DASHBOARD.primaryBlueLight : "#fff",
                color: active ? VEEWASH_DASHBOARD.primaryBlueDark : "#334155",
                borderRadius: 999,
                px: 1.1,
                py: 0.55,
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              {p.label}
            </Box>
          );
        })}
      </Box>

      {compare === "last_n" ? (
        <TextField
          size="small"
          type="number"
          label="Last N sessions"
          value={lastN}
          onChange={(e) => setLastN(Math.max(1, Number(e.target.value) || 1))}
          onBlur={() => load({ compare: "last_n", last_n: lastN })}
          sx={{ mb: 1, width: 160 }}
          inputProps={{ min: 1, max: 100 }}
        />
      ) : null}

      {error ? (
        <Alert severity="error" sx={{ mb: 1, py: 0.5 }}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 0.75,
              mb: 1,
            }}
          >
            <Box sx={{ p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb", bgcolor: "#fff" }}>
              <Typography sx={{ fontSize: 20, fontWeight: 800 }}>{fmtRate(summary.bags_per_hour)}</Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
                Bags/hr
              </Typography>
            </Box>
            <Box sx={{ p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb", bgcolor: "#fff" }}>
              <Typography sx={{ fontSize: 20, fontWeight: 800 }}>{fmtRate(summary.lbs_per_hour, 0)}</Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
                Lb/hr
              </Typography>
            </Box>
            <Box sx={{ p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb", bgcolor: "#fff" }}>
              <Typography sx={{ fontSize: 20, fontWeight: 800 }}>
                {summary.orders_completed ?? 0}
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
                Orders
              </Typography>
            </Box>
            <Box sx={{ p: 1, borderRadius: 1.5, border: "1px solid #e5e7eb", bgcolor: "#fff" }}>
              <Typography sx={{ fontSize: 20, fontWeight: 800 }}>
                {summary.employee_count ?? 0}
              </Typography>
              <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
                Employees
              </Typography>
            </Box>
          </Box>

          {deltas ? (
            <Stack direction="row" spacing={0.75} sx={{ mb: 1.25, flexWrap: "wrap" }}>
              <DeltaChip label="Bags/hr" pct={deltas.bags_per_hour_delta_pct} />
              <DeltaChip label="Lb/hr" pct={deltas.lbs_per_hour_delta_pct} />
            </Stack>
          ) : null}

          <Button
            fullWidth
            variant="outlined"
            onClick={() => setShowUnmapped((v) => !v)}
            sx={{
              mb: 1.25,
              justifyContent: "space-between",
              textTransform: "none",
              fontWeight: 800,
              borderColor: unmappedCount ? "#f59e0b" : "#e5e7eb",
              color: unmappedCount ? "#b45309" : "#334155",
              bgcolor: unmappedCount ? "#fffbeb" : "#fff",
            }}
          >
            Unmapped Orders
            <Box component="span">{unmappedCount}</Box>
          </Button>

          {showUnmapped ? (
            <Box
              sx={{
                mb: 1.5,
                p: 1.1,
                borderRadius: 2,
                border: "1px solid #fde68a",
                bgcolor: "#fffbeb",
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                <Typography sx={{ fontSize: 13, fontWeight: 800 }}>Investigate / reassign</Typography>
                <Stack direction="row" spacing={0.5}>
                  <Button size="small" onClick={() => selectAllVisible(unmapped)} sx={{ textTransform: "none" }}>
                    Select All
                  </Button>
                  <Button
                    size="small"
                    disabled={!selectedBagIds.size}
                    onClick={() => openMove(unmapped)}
                    sx={{ textTransform: "none", fontWeight: 800 }}
                  >
                    Move
                  </Button>
                </Stack>
              </Stack>
              {unmapped.length === 0 ? (
                <Typography sx={{ fontSize: 12, color: "#78716c" }}>None</Typography>
              ) : (
                unmapped.map((o) => (
                  <OrderRow
                    key={o.bag_id}
                    order={o}
                    selectable
                    selected={selectedBagIds.has(o.bag_id)}
                    onToggle={toggleBag}
                  />
                ))
              )}
            </Box>
          ) : null}

          <Stack spacing={1.1}>
            {(data?.employees || []).map((emp) => (
              <EmployeeCard key={emp.employee} employee={emp} onOpenSession={openSession} />
            ))}
            {!loading && !(data?.employees || []).length ? (
              <Typography sx={{ py: 2, textAlign: "center", color: "#64748b", fontSize: 13 }}>
                No WF Folder sessions for this window.
              </Typography>
            ) : null}
          </Stack>
        </>
      )}

      <Dialog
        open={!!sessionModal}
        onClose={() => {
          setSessionModal(null);
          setSelectedBagIds(new Set());
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ fontWeight: 800, fontSize: 16, pb: 0.5 }}>
          {sessionModal?.employee}
        </DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600, mb: 1 }}>
            {sessionModal?.time_range_label || "—"}
          </Typography>
          {sessionModal?.performance_through_label ? (
            <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600, mb: 1 }}>
              {sessionModal.performance_through_label}
              {sessionModal.duration_label ? ` · ${sessionModal.duration_label}` : ""}
            </Typography>
          ) : sessionModal?.duration_label ? (
            <Typography sx={{ fontSize: 11, color: "#64748b", fontWeight: 600, mb: 1 }}>
              {sessionModal.duration_label}
            </Typography>
          ) : null}
          <Stack direction="row" spacing={0.75} sx={{ mb: 1, flexWrap: "wrap" }}>
            <Button size="small" onClick={() => selectAllVisible(sessionOrders)} sx={{ textTransform: "none" }}>
              Select All
            </Button>
            <Button
              size="small"
              disabled={!selectedBagIds.size}
              onClick={() => openMove(sessionOrders)}
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
            <Box sx={{ py: 3, textAlign: "center" }}>
              <CircularProgress size={24} />
            </Box>
          ) : (
            sessionOrders.map((o) => (
              <OrderRow
                key={o.bag_id}
                order={o}
                selectable
                selected={selectedBagIds.has(o.bag_id)}
                onToggle={toggleBag}
              />
            ))
          )}
          {!sessionLoading && !sessionOrders.length ? (
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>No orders in this session.</Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setSessionModal(null);
              setSelectedBagIds(new Set());
            }}
          >
            Close
          </Button>
        </DialogActions>
      </Dialog>

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
