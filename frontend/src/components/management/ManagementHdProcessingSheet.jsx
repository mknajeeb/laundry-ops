import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
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
import {
  applyManagementRinseHdProcessing,
  getManagementRinseHdDetail,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";

function todayEtDatetimeLocal() {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date());
    const get = (type) => parts.find((p) => p.type === type)?.value || "";
    return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
  } catch {
    return new Date().toISOString().slice(0, 16);
  }
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
  return `${String(v).replace("T", " ")}:00`;
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
  return status || "—";
}

function ChronologyRow({ label, name, at }) {
  return (
    <Box sx={{ py: 0.5 }}>
      <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#334155", textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{name || "—"}</Typography>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{fmtTime(at)}</Typography>
    </Box>
  );
}

export default function ManagementHdProcessingSheet({
  open,
  onClose,
  order,
  dateEt,
  onSuccess,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [employeeUserId, setEmployeeUserId] = useState("");
  const [operationalAt, setOperationalAt] = useState(todayEtDatetimeLocal());
  const [confirmAction, setConfirmAction] = useState(null);

  const bagId = order?.bag_id;
  const status = detail?.order?.status || order?.status || "";
  const employees = detail?.employees || [];
  const version = detail?.production?.version ?? order?.production_version ?? 0;

  const canMarkWashed = status === "pending_wash";
  const canMarkFolded = status === "washed" || status === "awaiting_fold";
  const canMarkComplete =
    status === "awaiting_entry" &&
    detail?.production?.items != null &&
    detail?.production?.revenue != null;
  const canBackToFold = status === "awaiting_entry" || status === "complete";
  const canBackToWash =
    status === "washed" ||
    status === "awaiting_fold" ||
    status === "awaiting_entry" ||
    status === "complete";
  const canReopen = status === "complete";

  useEffect(() => {
    if (!open || !bagId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setEmployeeUserId("");
    setOperationalAt(todayEtDatetimeLocal());
    setConfirmAction(null);
    (async () => {
      try {
        const res = await getManagementRinseHdDetail(bagId, { date_et: dateEt });
        if (!cancelled) setDetail(res.data || null);
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.error || err?.message || "Unable to load order");
          setDetail({ order });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, bagId, dateEt, order]);

  const orderView = useMemo(() => detail?.order || order || {}, [detail, order]);

  const runAction = async (action, { confirmRemove = false } = {}) => {
    if (!bagId) return;
    setSaving(true);
    setError("");
    try {
      const body = {
        action,
        date_et: dateEt,
        version,
        confirm_remove: confirmRemove,
      };
      if (action === "mark_washed" || action === "mark_folded") {
        body.employee_user_id = employeeUserId;
        body.operational_at = fromDatetimeLocalValue(operationalAt);
      }
      const res = await applyManagementRinseHdProcessing(bagId, body);
      setConfirmAction(null);
      onSuccess?.(res.data);
      onClose?.();
    } catch (err) {
      const data = err?.response?.data || {};
      setError(data.message || data.error || err?.message || "Action failed");
      if (data.error === "confirmation_required") {
        setConfirmAction(action);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 800, pb: 1 }}>
          Manage processing
          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#64748b", mt: 0.5 }}>
            {bagId}
          </Typography>
        </DialogTitle>
        <DialogContent>
          {error ? (
            <Alert severity="error" sx={{ mb: 1.5 }}>
              {error}
            </Alert>
          ) : null}
          {loading ? (
            <Typography sx={{ py: 2, color: "#64748b", fontWeight: 600 }}>Loading…</Typography>
          ) : (
            <Stack spacing={1.5}>
              <Box sx={{ p: 1.25, borderRadius: 1.5, border: "1px solid #e5e7eb", bgcolor: "#f8fafc" }}>
                <Typography sx={{ fontSize: 12, fontWeight: 800, color: "#64748b", mb: 0.5 }}>
                  Current status: {statusLabel(status)}
                </Typography>
                <ChronologyRow
                  label="Wash"
                  name={orderView.washed_by_name}
                  at={orderView.washed_at}
                />
                <ChronologyRow
                  label="Fold"
                  name={orderView.folded_by_name}
                  at={orderView.folded_at}
                />
                <ChronologyRow
                  label="Complete"
                  name={orderView.completion_operator || detail?.production?.management_completed_by_name}
                  at={orderView.completion_at || detail?.production?.management_completed_at}
                />
              </Box>

              {canMarkWashed || canMarkFolded ? (
                <Stack spacing={1} sx={{ p: 1, border: "1px solid #e5e7eb", borderRadius: 1.5 }}>
                  <FormControl size="small" fullWidth>
                    <InputLabel>Employee</InputLabel>
                    <Select
                      label="Employee"
                      value={employeeUserId}
                      onChange={(e) => setEmployeeUserId(e.target.value)}
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
                    label="Date & time (ET)"
                    type="datetime-local"
                    value={operationalAt}
                    onChange={(e) => setOperationalAt(e.target.value)}
                    InputLabelProps={{ shrink: true }}
                    fullWidth
                  />
                </Stack>
              ) : null}

              {canMarkWashed ? (
                <Button
                  variant="contained"
                  disabled={saving || !employeeUserId}
                  onClick={() => runAction("mark_washed")}
                  sx={{ textTransform: "none", fontWeight: 800 }}
                >
                  Mark Washed
                </Button>
              ) : null}

              {canMarkFolded ? (
                <Button
                  variant="contained"
                  disabled={saving || !employeeUserId}
                  onClick={() => runAction("mark_folded")}
                  sx={{ textTransform: "none", fontWeight: 800 }}
                >
                  Mark Folded
                </Button>
              ) : null}

              {canMarkComplete ? (
                <Button
                  variant="contained"
                  color="success"
                  disabled={saving}
                  onClick={() => runAction("mark_complete")}
                  sx={{ textTransform: "none", fontWeight: 800 }}
                >
                  Mark Entry Complete
                </Button>
              ) : null}

              {canReopen ? (
                <Button
                  variant="outlined"
                  color="warning"
                  disabled={saving}
                  onClick={() => setConfirmAction("reopen")}
                  sx={{ textTransform: "none", fontWeight: 700 }}
                >
                  Reopen / Correct Processing
                </Button>
              ) : null}

              {canBackToFold ? (
                <Button
                  variant="outlined"
                  color="warning"
                  disabled={saving}
                  onClick={() => setConfirmAction("back_to_awaiting_fold")}
                  sx={{ textTransform: "none", fontWeight: 700 }}
                >
                  Move Back to Awaiting Fold
                </Button>
              ) : null}

              {canBackToWash ? (
                <Button
                  variant="outlined"
                  color="error"
                  disabled={saving}
                  onClick={() => setConfirmAction("back_to_pending_wash")}
                  sx={{ textTransform: "none", fontWeight: 700 }}
                >
                  Move Back to Pending Wash
                </Button>
              ) : null}
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} sx={{ textTransform: "none" }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(confirmAction)} onClose={() => setConfirmAction(null)}>
        <DialogTitle sx={{ fontWeight: 800 }}>Remove processing events?</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 14 }}>
            This will remove downstream processing evidence and employee performance credit for this
            order. Continue?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmAction(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            disabled={saving}
            onClick={() => runAction(confirmAction, { confirmRemove: true })}
          >
            Confirm
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
