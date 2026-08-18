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
  const [scansRequested, setScansRequested] = useState(false);
  const [scansState, setScansState] = useState({
    loading: false,
    error: "",
    scans: [],
    meta: null,
  });
  const [coreMs, setCoreMs] = useState(null);

  useEffect(() => {
    if (!open || !bagId || !selectedDateEt) {
      setDetail(null);
      setError("");
      setScansRequested(false);
      setScansState({ loading: false, error: "", scans: [], meta: null });
      setCoreMs(null);
      return undefined;
    }
    let cancelled = false;
    const t0 = typeof performance !== "undefined" ? performance.now() : 0;
    (async () => {
      setLoading(true);
      setError("");
      setDetail(null);
      setScansRequested(false);
      setScansState({ loading: false, error: "", scans: [], meta: null });
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
        if (typeof performance !== "undefined") {
          setCoreMs(Math.round(performance.now() - t0));
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

  // Scans load only after VIEW SCANS — never on modal open.
  useEffect(() => {
    if (!open || !bagId || !selectedDateEt || !scansRequested) {
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
  }, [open, bagId, selectedDateEt, scansRequested]);

  const bag = detail?.bag || null;
  const catalog = Array.isArray(detail?.active_bulk_workitems)
    ? detail.active_bulk_workitems
    : [];

  // Split Order Review resolves in the drawer only — never via this modal.
  // Specialty / Missing may still show incidental split facts as read-only context.
  const scansSection = (
    <>
      {(bag?.split_state || bag?.canonical_split_evaluation || bag?.split_marker_present != null) ? (
        <Section title="Split evidence">
          <Typography sx={{ fontSize: 13, mb: 0.35 }}>
            Marker: {bag.split_marker_present ? "Yes" : "No"}
            {bag.washer_load_count != null ? ` · Washer loads: ${bag.washer_load_count}` : ""}
            {bag.split_state ? ` · State: ${bag.split_state}` : ""}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.5 }}>
            Split decisions are made in Split Order Review (drawer), not here.
          </Typography>
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
      {scansRequested ? (
        <ScansBlock
          loading={scansState.loading}
          error={scansState.error}
          scans={scansState.scans}
          meta={scansState.meta}
        />
      ) : (
        <Section title="Scans">
          <Button
            data-testid="review-view-scans"
            size="small"
            variant="outlined"
            onClick={() => setScansRequested(true)}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            VIEW SCANS
          </Button>
          <Typography sx={{ mt: 0.5, fontSize: 11, color: "#94a3b8" }}>
            Not loaded until requested
          </Typography>
        </Section>
      )}
      {detail?._meta?.elapsed_ms != null || coreMs != null ? (
        <Typography sx={{ fontSize: 10, color: "#94a3b8" }} data-testid="review-modal-perf">
          Core {coreMs ?? detail?._meta?.elapsed_ms} ms
          {detail?._meta?.query_count != null ? ` · ${detail._meta.query_count} queries` : ""}
          {scansRequested && scansState.meta?.elapsed_ms != null
            ? ` · scans ${scansState.meta.elapsed_ms} ms`
            : " · scans not fetched"}
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
