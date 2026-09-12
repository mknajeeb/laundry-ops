import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import {
  getManagementRinseWfBagDetail,
  postManagementWfCwMoveToReview,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import { displayCustomerName } from "../../utils/displayCustomerName";
import ManagementCopyableId from "./ManagementCopyableId";
import { formatReviewApiError } from "./reviewDisplayLabels";
import { fmtLbs } from "./reviewDrawerModel";

function rushLabel(flag) {
  const raw = String(flag || "").trim().toLowerCase();
  if (!raw || raw === "non-rush" || raw === "non_rush" || raw === "nonrush") {
    return "Non-Rush";
  }
  if (raw === "rush" || raw.includes("rush")) return "Rush";
  return String(flag || "—");
}

function fmtTime(v) {
  if (!v) return "—";
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

/**
 * Lightweight Pending bag manager drawer — inspect + Send to Review only.
 * Completion fields are intentionally absent.
 */
export default function ManagementPendingBagDrawer({
  open,
  seedRow,
  selectedDateEt,
  readOnly,
  onClose,
  onSentToReview,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [editPreOpen, setEditPreOpen] = useState(false);

  const bagId = seedRow?.bag_id;

  useEffect(() => {
    if (!open || !bagId || !selectedDateEt) {
      setDetail(null);
      setError("");
      setNote("");
      setConfirmOpen(false);
      setEditPreOpen(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setDetail(null);
    (async () => {
      try {
        const res = await getManagementRinseWfBagDetail(selectedDateEt, {
          bag_id: bagId,
          order_instance_id: seedRow?.order_instance_id || undefined,
        });
        if (cancelled) return;
        const data = res?.data || {};
        if (data.ok === false) {
          // Fall back to seed row from Current Workload list.
          setDetail({
            ...seedRow,
            customer_name: seedRow?.customer_name,
            status: seedRow?.status || "pending",
            _fromSeed: true,
          });
          setError("");
          return;
        }
        setDetail({ ...(data.bag || data), ...(seedRow || {}) });
      } catch (err) {
        if (cancelled) return;
        setDetail({ ...seedRow, status: seedRow?.status || "pending", _fromSeed: true });
        setError(
          formatReviewApiError(
            err?.response?.data?.error,
            err?.response?.data?.message || err?.message || "",
          ),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, bagId, selectedDateEt, seedRow?.order_instance_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const bag = detail || seedRow || {};

  const sendToReview = async () => {
    if (readOnly || sending || !bagId) return;
    setSending(true);
    setError("");
    try {
      const res = await postManagementWfCwMoveToReview(selectedDateEt, bagId, {
        reason: String(note || "").trim() || "Manager sent for review",
        order_instance_id: bag.order_instance_id || seedRow?.order_instance_id || null,
      });
      if (!res?.data?.ok) {
        setError(
          formatReviewApiError(
            res?.data?.error,
            res?.data?.message || "Send to Review failed",
          ),
        );
        return;
      }
      setConfirmOpen(false);
      onSentToReview?.(res.data, bagId);
      onClose?.();
    } catch (err) {
      setError(
        formatReviewApiError(
          err?.response?.data?.error,
          err?.response?.data?.message || err?.message || "Send to Review failed",
        ),
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onClose={sending ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ pr: 6 }}>
        Pending order
        <Typography sx={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>
          Open / in process · inspect only
        </Typography>
        <IconButton
          aria-label="Close"
          onClick={onClose}
          disabled={sending}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 2 }}>
            <CircularProgress size={18} />
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>Loading bag…</Typography>
          </Stack>
        ) : (
          <Stack spacing={1}>
            <Typography sx={{ fontWeight: 800, fontSize: 16 }}>
              {displayCustomerName(bag.customer_name) || "Customer unavailable"}
            </Typography>
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap">
              <ManagementCopyableId value={bag.bag_id} fontSize={13} fontWeight={700} />
              <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                · OI {bag.order_instance_id ?? "—"} · {rushLabel(bag.rush_status || bag.rush_flag)}
              </Typography>
            </Stack>
            <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>
              Status: Pending (open)
            </Typography>
            <Stack direction="row" spacing={1.5} flexWrap="wrap">
              <Typography sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
                PRE {fmtLbs(bag.pre_weight_lbs) || "—"}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
                POST {fmtLbs(bag.post_weight_lbs ?? bag.post_weight_value) || "—"}
              </Typography>
            </Stack>
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              Received {fmtTime(bag.received_from_vendor_at)}
            </Typography>
            {bag.cycle_anchor_at ? (
              <Typography sx={{ fontSize: 11, color: "#94a3b8" }}>
                Cycle anchor {fmtTime(bag.cycle_anchor_at)}
              </Typography>
            ) : null}

            <Button
              size="small"
              variant="text"
              onClick={() => setEditPreOpen((v) => !v)}
              sx={{ alignSelf: "flex-start", textTransform: "none", fontWeight: 700, px: 0 }}
            >
              {editPreOpen ? "Hide corrections" : "Secondary corrections"}
            </Button>
            <Collapse in={editPreOpen}>
              <Alert severity="info" sx={{ py: 0.5 }}>
                Weight/completion corrections belong in Review after Send to Review, or via
                Completed Manage. Pending inspect does not complete orders.
              </Alert>
            </Collapse>

            {error ? (
              <Alert severity="error" onClose={() => setError("")}>
                {error}
              </Alert>
            ) : null}

            {!confirmOpen ? (
              <Button
                data-testid="pending-send-to-review"
                variant="contained"
                disabled={readOnly || sending || !bagId}
                onClick={() => setConfirmOpen(true)}
                sx={{ textTransform: "none", fontWeight: 800, mt: 1 }}
              >
                Send to Review
              </Button>
            ) : (
              <Box sx={{ mt: 1, p: 1.25, border: "1px solid #e2e8f0", borderRadius: 1 }}>
                <Typography sx={{ fontSize: 13, fontWeight: 800, mb: 0.75 }}>
                  Send to Manual Review?
                </Typography>
                <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1 }}>
                  Order stays open. Does not complete, exclude, or change PRE/POST.
                </Typography>
                <TextField
                  size="small"
                  label="Manager note (optional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  fullWidth
                  multiline
                  minRows={2}
                  disabled={sending}
                />
                <Stack direction="row" spacing={1} sx={{ mt: 1 }} justifyContent="flex-end">
                  <Button
                    size="small"
                    disabled={sending}
                    onClick={() => setConfirmOpen(false)}
                    sx={{ textTransform: "none" }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="small"
                    variant="contained"
                    disabled={sending || readOnly}
                    onClick={sendToReview}
                    startIcon={sending ? <CircularProgress size={14} color="inherit" /> : null}
                    sx={{ textTransform: "none", fontWeight: 800 }}
                  >
                    {sending ? "Sending…" : "Confirm Send to Review"}
                  </Button>
                </Stack>
              </Box>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={sending} sx={{ textTransform: "none" }}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
