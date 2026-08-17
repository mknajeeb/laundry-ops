import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  getManagementRinseWfReviewDetail,
  getManagementRinseWfReviewScans,
  postManagementRinseWfSplitDecision,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import EditBagPanel from "../shift/EditBagPanel";
import ManagementCopyableId from "./ManagementCopyableId";

function fmtTime(v) {
  if (!v) return "—";
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

function Section({ title, children }) {
  return (
    <Box sx={{ mb: 1.75 }}>
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 0.7,
          textTransform: "uppercase",
          color: "#64748b",
          mb: 0.75,
        }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function ScansBlock({ loading, error, scans, meta }) {
  return (
    <Section title="Scans">
      {loading ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}>
          <CircularProgress size={16} />
          <Typography sx={{ fontSize: 13, color: "#64748b" }}>Loading…</Typography>
        </Stack>
      ) : error ? (
        <Alert severity="warning" sx={{ py: 0.25 }}>
          {error}
        </Alert>
      ) : scans.length === 0 ? (
        <Typography sx={{ fontSize: 13, color: "#64748b" }}>No scans loaded.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              <TableCell>Purpose</TableCell>
              <TableCell>Employee</TableCell>
              <TableCell>Resource</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {scans.map((scan, idx) => (
              <TableRow key={scan.id || `${scan.scanned_at_parsed}-${idx}`}>
                <TableCell sx={{ whiteSpace: "nowrap", fontSize: 12 }}>
                  {fmtTime(scan.scanned_at_parsed || scan.scanned_at)}
                </TableCell>
                <TableCell sx={{ fontSize: 12 }}>{scan.purpose || "—"}</TableCell>
                <TableCell sx={{ fontSize: 12 }}>{scan.user_name || "—"}</TableCell>
                <TableCell sx={{ fontSize: 12 }}>{scan.rack || scan.resource || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {meta?.elapsed_ms != null ? (
        <Typography sx={{ mt: 0.75, fontSize: 10, color: "#94a3b8" }}>
          Scans {meta.elapsed_ms} ms · {scans.length} event{scans.length === 1 ? "" : "s"}
        </Typography>
      ) : null}
    </Section>
  );
}

/**
 * On-demand Review modal — core first (actions interactive), scans async.
 * Does not nest a second Dialog: EditBagPanel owns the modal chrome.
 */
export default function ManagementRinseWfReviewModal({
  open,
  bagId,
  seedBag = null,
  selectedDateEt,
  readOnly = false,
  onClose,
  onSaved,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [scansState, setScansState] = useState({
    loading: false,
    error: "",
    scans: [],
    meta: null,
  });
  const [splitSaving, setSplitSaving] = useState(false);
  const [splitMsg, setSplitMsg] = useState("");

  useEffect(() => {
    if (!open || !bagId || !selectedDateEt) {
      setDetail(null);
      setError("");
      setSplitMsg("");
      setScansState({ loading: false, error: "", scans: [], meta: null });
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      setDetail(null);
      try {
        const res = await getManagementRinseWfReviewDetail(selectedDateEt, bagId, {
          include_scans: false,
        });
        if (cancelled) return;
        const data = res?.data || {};
        if (data.ok === false) {
          setError(data.message || data.error || "Failed to load detail");
          setDetail(null);
        } else {
          const bag = {
            ...(data.bag || {}),
            _detailsLoaded: true,
          };
          setDetail({ ...data, bag });
        }
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.error || err?.message || "Failed to load detail");
          setDetail(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, bagId, selectedDateEt]);

  // Scans load after core — never block the action panel.
  useEffect(() => {
    if (!open || !bagId || !selectedDateEt || !detail?.bag) {
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setScansState({ loading: true, error: "", scans: [], meta: null });
      try {
        const res = await getManagementRinseWfReviewScans(selectedDateEt, bagId);
        if (cancelled) return;
        const data = res?.data || {};
        if (data.ok === false) {
          setScansState({
            loading: false,
            error: data.error || "Failed to load scans",
            scans: [],
            meta: data._meta || null,
          });
        } else {
          setScansState({
            loading: false,
            error: "",
            scans: Array.isArray(data.scans) ? data.scans : [],
            meta: data._meta || null,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setScansState({
            loading: false,
            error: err?.response?.data?.error || err?.message || "Failed to load scans",
            scans: [],
            meta: null,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, bagId, selectedDateEt, detail?.bag?.bag_id]);

  const bag = detail?.bag || null;
  const catalog = Array.isArray(detail?.active_bulk_workitems)
    ? detail.active_bulk_workitems
    : [];
  const isSplitReview =
    bag?.review_category === "split_order_review"
    || bag?.split_state === "REVIEW_REQUIRED";

  const saveSplitDecision = async (decision) => {
    if (!bagId || !selectedDateEt || readOnly) return;
    setSplitSaving(true);
    setSplitMsg("");
    try {
      const res = await postManagementRinseWfSplitDecision(selectedDateEt, bagId, {
        decision,
      });
      if (res?.data?.ok === false) {
        setSplitMsg(res.data.error || "Save failed");
      } else {
        setSplitMsg(decision === "split" ? "Marked as Split" : "Marked as Not Split");
        onSaved?.();
        onClose?.();
      }
    } catch (err) {
      setSplitMsg(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSplitSaving(false);
    }
  };

  const scansSection = (
    <>
      {(isSplitReview || bag?.split_state || bag?.canonical_split_evaluation) ? (
        <Section title="Split evidence">
          <Typography sx={{ fontSize: 13, mb: 0.35 }}>
            Marker: {bag.split_marker_present ? "Yes" : "No"}
            {bag.washer_load_count != null ? ` · Washer loads: ${bag.washer_load_count}` : ""}
            {bag.split_state ? ` · State: ${bag.split_state}` : ""}
          </Typography>
          {!readOnly && isSplitReview ? (
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Button
                variant="contained"
                disabled={splitSaving}
                onClick={() => saveSplitDecision("split")}
                sx={{ textTransform: "none", fontWeight: 700 }}
              >
                Mark as Split
              </Button>
              <Button
                variant="outlined"
                disabled={splitSaving}
                onClick={() => saveSplitDecision("not_split")}
                sx={{ textTransform: "none", fontWeight: 700 }}
              >
                Mark as Not Split
              </Button>
            </Stack>
          ) : null}
          {splitMsg ? (
            <Alert severity="info" sx={{ mt: 1, py: 0.25 }}>
              {splitMsg}
            </Alert>
          ) : null}
        </Section>
      ) : null}
      {detail?.portal_evidence ? (
        <Section title="Portal / Evidence">
          <Typography sx={{ fontSize: 13 }}>
            {detail.portal_evidence.portal_status || "—"}
            {detail.portal_evidence.last_seen_at
              ? ` · Last seen ${fmtTime(detail.portal_evidence.last_seen_at)}`
              : ""}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569", mt: 0.5 }}>
            {detail.portal_evidence.explanation}
          </Typography>
        </Section>
      ) : null}
      <ScansBlock
        loading={scansState.loading}
        error={scansState.error}
        scans={scansState.scans}
        meta={scansState.meta}
      />
      {detail?._meta?.elapsed_ms != null ? (
        <Typography sx={{ fontSize: 10, color: "#94a3b8" }}>
          Core {detail._meta.elapsed_ms} ms
          {detail._meta.query_count != null ? ` · ${detail._meta.query_count} queries` : ""}
          {detail._meta.scans_loaded ? " · scans in core" : " · scans separate"}
        </Typography>
      ) : null}
    </>
  );

  // Loading / error shell — opens immediately with seed header; does not wait on scans.
  if (open && (loading || error || !bag)) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="md" scroll="paper">
        <DialogTitle sx={{ pb: 0.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: 17 }}>Review WF Bag</Typography>
              <ManagementCopyableId
                value={bagId || seedBag?.bag_id}
                fontSize={13}
                fontWeight={700}
                sx={{ mt: 0.25 }}
              />
              <Typography sx={{ fontSize: 13, color: "#64748b", mt: 0.25 }}>
                {seedBag?.customer_name || "Loading…"}
                {seedBag?.rush_flag ? ` · ${seedBag.rush_flag}` : ""}
              </Typography>
            </Box>
            <Button onClick={onClose} sx={{ textTransform: "none" }}>
              Close
            </Button>
          </Stack>
        </DialogTitle>
        <DialogContent dividers>
          {loading ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
              <CircularProgress size={32} />
            </Box>
          ) : error ? (
            <Alert severity="error">{error}</Alert>
          ) : (
            <Typography sx={{ color: "#64748b" }}>No detail available.</Typography>
          )}
        </DialogContent>
      </Dialog>
    );
  }

  if (!open || !bag) return null;

  if (readOnly) {
    return (
      <Dialog open onClose={onClose} fullWidth maxWidth="md">
        <DialogTitle>Review WF Bag</DialogTitle>
        <DialogContent>
          <Alert severity="warning">Day is closed — review is read-only.</Alert>
          <Button onClick={onClose} sx={{ mt: 2 }}>
            Close
          </Button>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <EditBagPanel
      bag={bag}
      selectedDateEt={selectedDateEt}
      catalog={catalog}
      readOnly={readOnly}
      scansSection={scansSection}
      onCancel={onClose}
      onSaved={() => {
        onSaved?.();
        onClose?.();
      }}
    />
  );
}
