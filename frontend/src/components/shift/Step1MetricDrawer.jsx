import { useCallback, useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  CircularProgress,
  Alert,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  getBulkWorkitems,
  getVeewashStep1BagDetail,
  getVeewashStep1Drilldown,
  postVeewashStep1Correction,
} from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { PayrollDateTimeField } from "../PayrollDateTimeField";
import BulkWorkitemEntrySection from "./BulkWorkitemEntrySection";
import CopyableBagId from "../CopyableBagId";
import EditBagPanel from "./EditBagPanel";
import HdReviewPanel from "./HdReviewPanel";
import { formatWeightObservedEt, mergeBagListRow } from "./editBagHelpers";
import { actionsForBagStatus } from "./step1BagActions";
import { friendlyApiError } from "../../utils/shiftMonitorHelpers";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";

/** Session-scoped maintenance catalog (fetched once per browser session). */
let cachedBulkCatalog = null;
let cachedBulkCatalogPromise = null;

async function loadBulkCatalogOnce() {
  if (Array.isArray(cachedBulkCatalog) && cachedBulkCatalog.length) {
    return cachedBulkCatalog;
  }
  if (cachedBulkCatalogPromise) return cachedBulkCatalogPromise;
  cachedBulkCatalogPromise = getBulkWorkitems({ active_only: true })
    .then((res) => {
      const rows = res?.data?.items || res?.data?.workitems || res?.data || [];
      cachedBulkCatalog = Array.isArray(rows) ? rows : [];
      return cachedBulkCatalog;
    })
    .catch(() => {
      cachedBulkCatalogPromise = null;
      return [];
    });
  return cachedBulkCatalogPromise;
}

function defaultRackForService(service) {
  return String(service).toUpperCase() === "HD" ? "workitems-added" : "VeeWash Dirty";
}

/** Normalize API timestamps into datetime-local / dayjs-friendly ET strings. */
function toPickerValue(v) {
  if (!v) return "";
  const s = String(v).trim().replace(" ", "T");
  // Strip timezone offset / seconds for the picker value we round-trip.
  const m = s.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return m ? m[1] : s.slice(0, 16);
}

const REASON_LABELS = {
  DISAPPEARED_WITHOUT_COMPLETION: "Disappeared without completion",
  COMPLETED_WITHOUT_RECOGNIZED_ENTRY: "Completed without recognized entry",
  WF_ZERO_OR_MISSING_POST_WEIGHT: "Zero or missing WF post weight",
  WF_ZERO_OR_MISSING_WEIGHT: "Zero or missing WF post weight",
  WF_BULK_WORKITEM_REVIEW: "Bulk Workitems Require Review",
  SERVICE_CLASSIFICATION_MISMATCH: "Service classification mismatch",
  COMPLETION_DETAILS_MISSING: "Completion details missing",
  SCAN_CHRONOLOGY_STALE: "Scan chronology behind portal last-seen",
};

const PAGE_SIZE = 25;

/** Session cache: avoid refetching chronology when collapsing/reopening the same bag. */
const bagDetailCache = new Map();

function detailCacheKey(dateEt, bagId) {
  return `${dateEt || ""}::${String(bagId || "").toUpperCase()}`;
}

/** Operator-facing timestamps: America/New_York only (never raw UTC truncate). */
function fmtTs(v) {
  return formatFriendlyEtWall(v);
}

export default function Step1MetricDrawer({
  open,
  onClose,
  selectedDateEt,
  metric,
  queue = null,
  serviceFilter = "all",
  rushFilter = "all",
  title,
  onCorrected,
  readOnly = false,
  reasonCode = null,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [bags, setBags] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [snapshotUnavailable, setSnapshotUnavailable] = useState(false);
  const [snapshotMessage, setSnapshotMessage] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [detailLoading, setDetailLoading] = useState({});
  const [actionBag, setActionBag] = useState(null);
  const [editingBag, setEditingBag] = useState(null);
  const [reviewInitialOutcome, setReviewInitialOutcome] = useState(null);
  const editingBagRef = useRef(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const resolvedMetric = queue || metric;

  useEffect(() => {
    editingBagRef.current = editingBag;
  }, [editingBag]);

  const load = useCallback(
    async (nextPage = 1, signal, opts = {}) => {
      if (!open || !selectedDateEt || !resolvedMetric) return;
      const preserveExpanded = Boolean(opts.preserveExpanded);
      const openEditId = editingBagRef.current;
      const skipCacheMerge = Boolean(opts.skipCacheMerge) || Boolean(openEditId);
      setLoading(true);
      setError("");
      setSnapshotUnavailable(false);
      setSnapshotMessage("");
      if (!preserveExpanded) {
        setExpanded(null);
        setEditingBag(null);
        setBags([]);
        setTotal(0);
      }
      try {
        const res = await getVeewashStep1Drilldown({
          date: selectedDateEt,
          metric: resolvedMetric,
          queue: resolvedMetric,
          service: serviceFilter,
          rush: rushFilter,
          page: nextPage,
          page_size: PAGE_SIZE,
          include_details: false,
          reason_code: reasonCode || undefined,
          signal,
        });
        if (signal?.aborted) return;
        const data = res?.data || {};
        if (
          data.snapshot_missing
          || data.data_unavailable
          || data.snapshot_available === false
          || data.unavailable_reason === "step1_snapshot_missing"
        ) {
          setSnapshotUnavailable(true);
          setSnapshotMessage(
            data.message
              || "Shift Monitor snapshot is not available yet. Counts will appear after a successful scan refresh."
          );
          setBags([]);
          setTotal(0);
          setHasMore(false);
          setPage(1);
          return;
        }
        setBags((prev) => {
          const prevById = Object.fromEntries((prev || []).map((b) => [b.bag_id, b]));
          return (data.bags || []).map((b) =>
            mergeBagListRow({
              listBag: b,
              previousBag: prevById[b.bag_id],
              cachedDetail: bagDetailCache.get(detailCacheKey(selectedDateEt, b.bag_id)),
              editingBagId: openEditId,
              skipCacheMerge,
            })
          );
        });
        if (Array.isArray(data.active_bulk_workitems) && data.active_bulk_workitems.length) {
          setCatalog(data.active_bulk_workitems);
        } else if (resolvedMetric === "review_required" || reasonCode === "WF_BULK_WORKITEM_REVIEW") {
          loadBulkCatalogOnce().then((rows) => {
            if (!signal?.aborted && rows.length) setCatalog(rows);
          });
        }
        setPage(data.pagination?.page || nextPage);
        setTotal(data.pagination?.total ?? (data.bags || []).length);
        setHasMore(Boolean(data.pagination?.has_more));
      } catch (e) {
        if (signal?.aborted || e?.code === "ERR_CANCELED" || e?.name === "CanceledError") return;
        const fallback =
          resolvedMetric === "review_required"
            ? "Unable to load WF Review right now."
            : "Unable to load workload details.";
        setError(friendlyApiError(e?.response?.data?.error || e?.message, fallback));
        setBags([]);
        setTotal(0);
        setHasMore(false);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [open, selectedDateEt, resolvedMetric, serviceFilter, rushFilter, reasonCode]
  );

  useEffect(() => {
    const controller = new AbortController();
    load(1, controller.signal);
    return () => controller.abort();
  }, [load]);

  const loadBagDetail = async (bagId, { force = false } = {}) => {
    if (!bagId || !selectedDateEt || !resolvedMetric) return null;
    const cacheKey = detailCacheKey(selectedDateEt, bagId);
    if (!force) {
      const cached = bagDetailCache.get(cacheKey);
      if (cached) {
        // Don't clobber an open Edit Bag draft with a cache hit.
        if (editingBag === bagId) return cached;
        setBags((prev) =>
          prev.map((b) =>
            b.bag_id === bagId
              ? {
                  ...b,
                  ...cached,
                  scans: cached.scans || [],
                  corrections: cached.corrections || [],
                  bulk_workitems: cached.bulk_workitems || [],
                  _detailsLoaded: true,
                }
              : b
          )
        );
        return cached;
      }
    } else {
      bagDetailCache.delete(cacheKey);
    }
    setDetailLoading((m) => ({ ...m, [bagId]: true }));
    try {
      const res = await getVeewashStep1BagDetail({
        date: selectedDateEt,
        metric: resolvedMetric,
        queue: resolvedMetric,
        service: serviceFilter,
        rush: rushFilter,
        bag_id: bagId,
        include_details: true,
        reason_code: reasonCode || undefined,
      });
      const detail = (res?.data?.bags || [])[0];
      if (detail) {
        if (Array.isArray(res?.data?.active_bulk_workitems) && res.data.active_bulk_workitems.length) {
          setCatalog(res.data.active_bulk_workitems);
        }
        bagDetailCache.set(cacheKey, detail);
        setBags((prev) =>
          prev.map((b) => {
            if (b.bag_id !== bagId) return b;
            // After save we force-refresh; while drafting, keep local bag shell
            // but still attach scans/corrections/bulk for editor seed if first load.
            if (editingBag === bagId && !force) {
              return {
                ...b,
                scans: detail.scans || b.scans || [],
                corrections: detail.corrections || b.corrections || [],
                bulk_workitems: detail.bulk_workitems || b.bulk_workitems || [],
                updated_at: detail.updated_at || b.updated_at,
                day_bag_updated_at: detail.day_bag_updated_at || b.day_bag_updated_at,
                _detailsLoaded: true,
              };
            }
            return { ...b, ...detail, _detailsLoaded: true };
          })
        );
      }
      return detail || null;
    } catch (e) {
        const fallback =
          resolvedMetric === "review_required"
            ? "Unable to load WF Review right now."
            : "Unable to load workload details.";
        setError(friendlyApiError(e?.response?.data?.error || e?.message, fallback));
        return null;
      } finally {
      setDetailLoading((m) => ({ ...m, [bagId]: false }));
    }
  };

  const onExpand = (bagId) => {
    const next = expanded === bagId ? null : bagId;
    setExpanded(next);
    if (!next) {
      setEditingBag(null);
      return;
    }
    const bag = bags.find((b) => b.bag_id === bagId);
    if (bag && !bag._detailsLoaded) {
      loadBagDetail(bagId);
    }
  };

  const refreshBagAfterEdit = async (bagId, { closeEditor = false } = {}) => {
    bagDetailCache.delete(detailCacheKey(selectedDateEt, bagId));
    if (closeEditor) setEditingBag(null);
    // Drop completed bags from the open Review list immediately.
    if (resolvedMetric === "review_required" && bagId) {
      setBags((prev) => (prev || []).filter((b) => b.bag_id !== bagId));
      setTotal((t) => Math.max(0, Number(t || 0) - 1));
      setExpanded(null);
    } else {
      setExpanded(bagId);
    }
    // Reload drawer membership + parent Step-1 KPIs so counts match without manual refresh.
    try {
      await load(1, undefined, { preserveExpanded: true, skipCacheMerge: true });
    } catch (_) {
      /* non-blocking */
    }
    onCorrected?.();
  };

  const startAction = (bag, action) => {
    if (
      action === "edit_bag" ||
      action === "mark_completed" ||
      action === "return_pending" ||
      action === "exclude"
    ) {
      setError("");
      setActionBag(null);
      setReviewInitialOutcome(action === "edit_bag" ? null : action);
      setEditingBag(bag.bag_id);
      if (!bag._detailsLoaded) loadBagDetail(bag.bag_id, { force: true });
      return;
    }
    setEditingBag(null);
    setReviewInitialOutcome(null);
    setActionBag(bag.bag_id);
    setForm({
      action,
      bag_id: bag.bag_id,
      selected_date_et: selectedDateEt,
      reason: "",
      employee: bag.completed_by || "",
      completion_at: toPickerValue(bag.completion_at),
      entry_at: toPickerValue(bag.entry_at) || `${selectedDateEt || ""}T09:00`.slice(0, 16),
      service_type: bag.service_type || "WF",
      rack: defaultRackForService(bag.service_type || "WF"),
      weight_lbs:
        bag.post_weight_lbs != null && Number(bag.post_weight_lbs) > 0
          ? String(bag.post_weight_lbs)
          : bag.weight_lbs != null && Number(bag.weight_lbs) > 0
            ? String(bag.weight_lbs)
            : "",
      weight_at: toPickerValue(selectedDateEt ? `${selectedDateEt}T12:00` : ""),
    });
  };

  const submitCorrection = async () => {
    if (!form.reason?.trim()) {
      setError("Correction reason is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = {
        ...form,
        completion_at: form.completion_at ? form.completion_at.replace(" ", "T") : undefined,
        entry_at: form.entry_at ? form.entry_at.replace(" ", "T") : undefined,
        rack: form.action === "correct_entry" && form.service_type !== "HD" ? form.rack : undefined,
        weight_at: form.weight_at ? form.weight_at.replace(" ", "T") : undefined,
        weight_lbs: form.weight_lbs !== "" ? Number(form.weight_lbs) : undefined,
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Correction failed");
        return;
      }
      const bagId = actionBag;
      setActionBag(null);
      if (bagId) {
        bagDetailCache.delete(detailCacheKey(selectedDateEt, bagId));
        setExpanded(bagId);
        await loadBagDetail(bagId, { force: true });
      }
      onCorrected?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Correction failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: 520, md: 640 },
          p: 2,
          bgcolor: "#fff",
        },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            {title || metric}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {selectedDateEt} · filter={resolvedMetric || "—"} · service={serviceFilter} · rush={rushFilter}
            {total != null ? ` · ${total} bag${total === 1 ? "" : "s"}` : ""}
          </Typography>
        </Box>
        <Button onClick={onClose}>Close</Button>
      </Stack>
      <Divider sx={{ mb: 1.5 }} />
      {error ? (
        <Alert
          severity="error"
          sx={{ mb: 1 }}
          onClose={() => setError("")}
          action={
            <Button color="inherit" size="small" onClick={() => load(page)}>
              Retry
            </Button>
          }
        >
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : snapshotUnavailable ? (
        <Alert severity="warning" sx={{ py: 1.5 }}>
          {snapshotMessage
            || "Shift Monitor snapshot is not available yet. Counts will appear after a successful scan refresh."}
        </Alert>
      ) : (
        <Stack spacing={1}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="body2" color="text.secondary">
              {total} bag{total === 1 ? "" : "s"}
              {total > PAGE_SIZE ? ` · page ${page}` : ""}
            </Typography>
            <Button size="small" onClick={() => load(page)} disabled={loading}>
              Refresh
            </Button>
          </Stack>
          {total === 0 ? (
            <Alert severity="info" sx={{ py: 1 }}>
              No bags in this queue for the selected filters.
            </Alert>
          ) : null}
          {bags.map((bag) => {
            const openRow = expanded === bag.bag_id;
            const loadingDetail = Boolean(detailLoading[bag.bag_id]);
            return (
              <Accordion
                key={bag.bag_id}
                expanded={openRow}
                onChange={() => onExpand(bag.bag_id)}
                disableGutters
                elevation={0}
                sx={{ border: "1px solid #e2e8f0", borderRadius: 1, "&:before": { display: "none" } }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ width: "100%", pr: 1 }}>
                    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                      <CopyableBagId bagId={bag.bag_id} />
                      <Chip size="small" label={bag.service_type || "—"} />
                      <Chip size="small" label={bag.rush_flag || "—"} variant="outlined" />
                      <Chip
                        size="small"
                        label={bag.dashboard_status || "—"}
                        color="warning"
                        variant="outlined"
                      />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {bag.customer_name || "—"} · {bag.entry_class || "—"} · Pre Weight{" "}
                      {bag.pre_weight_lbs ?? "—"} · Post Weight{" "}
                      {bag.post_weight_event_exists
                        ? bag.post_weight_value ?? bag.post_weight_lbs ?? 0
                        : bag.post_weight_lbs ?? "—"}
                      {bag.post_weight_event_exists &&
                      Number(bag.post_weight_value ?? bag.post_weight_lbs) === 0
                        ? " (recorded 0)"
                        : ""}
                    </Typography>
                    {bag.specialty_quantity != null ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.25 }}>
                        {bag.specialty_item_class === "bath_mat"
                          ? "Bath-mat"
                          : bag.specialty_item_class === "comforter"
                            ? "Comforter"
                            : "Specialty"}{" "}
                        quantity: {bag.specialty_quantity}
                      </Typography>
                    ) : null}
                    {bag.rejection_status || bag.rejection_reason || bag.create_issue_at ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.25 }}>
                        Create-issue
                        {bag.create_issue_at || bag.rejection_at
                          ? ` · ${fmtTs(bag.create_issue_at || bag.rejection_at)}`
                          : ""}
                        {bag.create_issue_by || bag.rejection_by
                          ? ` · ${bag.create_issue_by || bag.rejection_by}`
                          : ""}
                      </Typography>
                    ) : null}
                    {bag.split_order || bag.split_status ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.25 }}>
                        Split: {bag.split_status || (bag.split_confirmed ? "confirmed" : "yes")}
                        {bag.washer_load_count != null ? ` · washer loads ${bag.washer_load_count}` : ""}
                        {Array.isArray(bag.washer_racks) && bag.washer_racks.length
                          ? ` · ${bag.washer_racks.join(", ")}`
                          : ""}
                      </Typography>
                    ) : null}
                    {String(bag.service_type || "").toUpperCase() === "HD" && bag.hd_review ? (
                      <Typography variant="caption" display="block" sx={{ mt: 0.25 }}>
                        HD review: {bag.hd_review.review_status || "REVIEW_REQUIRED"}
                        {bag.hd_review.item_count != null ? ` · Items ${bag.hd_review.item_count}` : ""}
                        {bag.hd_review.total_revenue != null
                          ? ` · Revenue $${Number(bag.hd_review.total_revenue).toFixed(2)}`
                          : ""}
                        {bag.hd_review.washed_by_name_snapshot
                          ? ` · Washed ${bag.hd_review.washed_by_name_snapshot}`
                          : ""}
                        {bag.hd_review.washed_date_et
                          ? ` (${bag.hd_review.washed_date_et})`
                          : ""}
                        {bag.hd_review.folded_by_name_snapshot
                          ? ` · Folded ${bag.hd_review.folded_by_name_snapshot}`
                          : ""}
                        {bag.hd_review.folded_date_et
                          ? ` (${bag.hd_review.folded_date_et})`
                          : ""}
                      </Typography>
                    ) : null}
                    {(bag.reason_codes || []).length > 0 ? (
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                        {(bag.reason_codes || []).map((c) => (
                          <Chip
                            key={c}
                            size="small"
                            label={REASON_LABELS[c] || c}
                            sx={{ height: 20, fontSize: "0.68rem" }}
                          />
                        ))}
                      </Stack>
                    ) : null}
                  </Box>
                </AccordionSummary>
                <AccordionDetails
                  sx={{
                    pt: 1,
                    position: "relative",
                    maxHeight: { xs: "70vh", sm: "65vh" },
                    overflowY: "auto",
                  }}
                >
                  <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>
                    Entry: {bag.entry_source || "—"} @ {fmtTs(bag.entry_at)} · Completion:{" "}
                    {fmtTs(bag.completion_at)} by {bag.completed_by || "—"} · Portal:{" "}
                    {bag.portal_status || "—"} · Last seen: {fmtTs(bag.last_seen_at)}
                  </Typography>

                  {String(bag.service_type || "").toUpperCase() === "HD" ? (
                    <>
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 0.5, mb: 0.25 }}>
                        HD review
                      </Typography>
                      <Typography variant="caption" display="block" sx={{ mb: 1 }}>
                        Review Status {bag.hd_review?.review_status || "REVIEW_REQUIRED"} · Items{" "}
                        {bag.hd_review?.item_count ?? "—"} · Revenue{" "}
                        {bag.hd_review?.total_revenue != null
                          ? `$${Number(bag.hd_review.total_revenue).toFixed(2)}`
                          : "—"}{" "}
                        · Washed By {bag.hd_review?.washed_by_name_snapshot || "—"}
                        {bag.hd_review?.washed_date_et ? ` (${bag.hd_review.washed_date_et})` : ""}
                        · Folded By {bag.hd_review?.folded_by_name_snapshot || "—"}
                        {bag.hd_review?.folded_date_et ? ` (${bag.hd_review.folded_date_et})` : ""}
                      </Typography>
                    </>
                  ) : null}

                  <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 0.5, mb: 0.25 }}>
                    System result
                  </Typography>
                  <Typography variant="caption" display="block" sx={{ mb: 1 }}>
                    Outcome {bag.system_result?.outcome || bag.dashboard_status || "—"} · Canonical{" "}
                    {bag.system_result?.canonical_status || "—"} · Reasons{" "}
                    {(bag.system_result?.reason_codes || bag.reason_codes || []).join(", ") || "—"}
                  </Typography>

                  {editingBag === bag.bag_id ? null : (() => {
                    const acts = actionsForBagStatus(bag.dashboard_status || bag.outcome, {
                      specialtyReviewResolved: Boolean(
                        bag.specialty_review_resolved
                          || bag.bulk_review_cleared
                          || bag.bulk_cleared,
                      ),
                      specialtyReviewUnresolved: Boolean(
                        bag.specialty_review_unresolved
                          || (bag.reason_codes || []).includes("WF_BULK_WORKITEM_REVIEW"),
                      ),
                      bulkReviewCleared: Boolean(
                        bag.bulk_review_cleared || bag.bulk_cleared,
                      ),
                      reasonCodes: bag.reason_codes || [],
                    });
                    return (
                      <Box
                        data-testid="bag-action-bar"
                        sx={{
                          position: "sticky",
                          top: 0,
                          zIndex: 2,
                          py: 1,
                          mb: 1,
                          bgcolor: "background.paper",
                          borderBottom: "1px solid",
                          borderColor: "divider",
                        }}
                      >
                        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                          {acts.statusLabel ? (
                            <Chip
                              size="small"
                              label={acts.statusLabel}
                              color={acts.isCompleted ? "success" : "default"}
                              variant="outlined"
                            />
                          ) : null}
                          {readOnly ? (
                            <Typography variant="caption" color="text.secondary">
                              Shift is closed — reopen to make corrections.
                            </Typography>
                          ) : (
                            <>
                              {acts.viewDetails ? (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  data-testid="view-details-button"
                                  onClick={() => startAction(bag, "edit_bag")}
                                >
                                  View Details
                                </Button>
                              ) : null}
                              {acts.editBag ? (
                                <Button
                                  size="small"
                                  variant="contained"
                                  data-testid="edit-bag-button"
                                  onClick={() => startAction(bag, "edit_bag")}
                                >
                                  Review
                                </Button>
                              ) : null}
                              {acts.moveToReview ? (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => startAction(bag, "move_to_review")}
                                >
                                  Move to Review Required
                                </Button>
                              ) : null}
                              {acts.correctEntry ? (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => startAction(bag, "correct_entry")}
                                >
                                  Correct entry
                                </Button>
                              ) : null}
                              {acts.correctWeight ? (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => startAction(bag, "correct_weight")}
                                >
                                  Correct weight
                                </Button>
                              ) : null}
                              {acts.correctCompletion ? (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => startAction(bag, "correct_completion")}
                                >
                                  Correct completion
                                </Button>
                              ) : null}
                            </>
                          )}
                        </Stack>
                      </Box>
                    );
                  })()}

                  {!readOnly && editingBag === bag.bag_id ? (
                    String(bag.service_type || "").toUpperCase() === "HD" ? (
                      <HdReviewPanel
                        bag={bag}
                        selectedDateEt={selectedDateEt}
                        readOnly={readOnly}
                        onCancel={() => {
                          setEditingBag(null);
                          setReviewInitialOutcome(null);
                        }}
                        onError={(msg) => setError(msg)}
                        onSaved={async () => {
                          setReviewInitialOutcome(null);
                          await refreshBagAfterEdit(bag.bag_id, { closeEditor: true });
                        }}
                        onUndo={async () => {
                          await refreshBagAfterEdit(bag.bag_id, { closeEditor: false });
                        }}
                      />
                    ) : (
                      <EditBagPanel
                        bag={bag}
                        selectedDateEt={selectedDateEt}
                        catalog={catalog}
                        readOnly={readOnly}
                        initialOutcome={reviewInitialOutcome}
                        onCancel={() => {
                          setEditingBag(null);
                          setReviewInitialOutcome(null);
                        }}
                        onError={(msg) => setError(msg)}
                        onReloadLatest={async (bagId) => loadBagDetail(bagId, { force: true })}
                        onSaved={async () => {
                          setReviewInitialOutcome(null);
                          await refreshBagAfterEdit(bag.bag_id, { closeEditor: true });
                        }}
                        onUndo={async () => {
                          await refreshBagAfterEdit(bag.bag_id, { closeEditor: false });
                        }}
                      />
                    )
                  ) : null}

                  {!readOnly && actionBag === bag.bag_id ? (
                    <Box
                      sx={{ mb: 1.5, p: 1.25, bgcolor: VEEWASH_DASHBOARD.primaryBlueLight, borderRadius: 1 }}
                    >
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                        {form.action}
                      </Typography>
                      <Stack spacing={1}>
                        {(form.action === "mark_completed" || form.action === "correct_completion") && (
                          <>
                            <FoldingUserSelect
                              label="Completed by"
                              value={form.employee || ""}
                              onChange={(name) => setForm((f) => ({ ...f, employee: name }))}
                              allowEmpty={false}
                              sx={{ width: "100%", minWidth: 0 }}
                            />
                            <PayrollDateTimeField
                              label="Completion date & time (ET)"
                              value={form.completion_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, completion_at: v }))}
                            />
                          </>
                        )}
                        {form.action === "correct_entry" && (
                          <>
                            <FormControl size="small" fullWidth>
                              <InputLabel>Service</InputLabel>
                              <Select
                                label="Service"
                                value={form.service_type || "WF"}
                                onChange={(e) => {
                                  const nextService = e.target.value;
                                  setForm((f) => ({
                                    ...f,
                                    service_type: nextService,
                                    rack:
                                      f.rack === defaultRackForService(f.service_type)
                                        ? defaultRackForService(nextService)
                                        : f.rack,
                                  }));
                                }}
                              >
                                <MenuItem value="WF">WF</MenuItem>
                                <MenuItem value="HD">HD</MenuItem>
                              </Select>
                            </FormControl>
                            <PayrollDateTimeField
                              label="Entry date & time (ET)"
                              value={form.entry_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, entry_at: v }))}
                            />
                            <TextField
                              size="small"
                              label="Rack"
                              value={form.rack || ""}
                              disabled={form.service_type === "HD"}
                              helperText={
                                form.service_type === "HD"
                                  ? "HD entries use workitems-added, not a rack"
                                  : undefined
                              }
                              onChange={(e) => setForm((f) => ({ ...f, rack: e.target.value }))}
                            />
                          </>
                        )}
                        {form.action === "correct_weight" && (
                          <>
                            <TextField
                              size="small"
                              type="number"
                              label="Post Weight lbs (>0)"
                              value={form.weight_lbs}
                              onChange={(e) => setForm((f) => ({ ...f, weight_lbs: e.target.value }))}
                              helperText={`Pre Weight: ${bag.pre_weight_lbs ?? "—"} (informational). Review Required only when Post Weight is missing or ≤0.`}
                              inputProps={{ min: 0.1, step: 0.1 }}
                            />
                            <PayrollDateTimeField
                              label="Weight date & time (ET)"
                              value={form.weight_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, weight_at: v }))}
                            />
                            <FoldingUserSelect
                              label="Weight employee"
                              value={form.employee || ""}
                              onChange={(name) => setForm((f) => ({ ...f, employee: name }))}
                              allowEmpty={false}
                              sx={{ width: "100%", minWidth: 0 }}
                            />
                          </>
                        )}
                        <TextField
                          size="small"
                          required
                          label="Correction reason"
                          value={form.reason || ""}
                          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                          multiline
                          minRows={2}
                        />
                        <Stack direction="row" spacing={1}>
                          <Button variant="contained" disabled={saving} onClick={submitCorrection}>
                            {saving ? "Saving…" : "Save correction"}
                          </Button>
                          <Button onClick={() => setActionBag(null)}>Cancel</Button>
                        </Stack>
                      </Stack>
                    </Box>
                  ) : null}

                  <BulkWorkitemEntrySection
                    bag={bag}
                    selectedDateEt={selectedDateEt}
                    catalog={catalog}
                    readOnly
                    onError={(msg) => setError(msg)}
                    onSaved={async () => {
                      bagDetailCache.delete(detailCacheKey(selectedDateEt, bag.bag_id));
                      setExpanded(bag.bag_id);
                      await loadBagDetail(bag.bag_id, { force: true });
                      onCorrected?.();
                    }}
                  />

                  <Typography
                    variant="subtitle2"
                    fontWeight={700}
                    sx={{ mt: 1, mb: 0.5 }}
                    data-testid="scan-chronology-heading"
                  >
                    Scan chronology (ET)
                  </Typography>
                  {loadingDetail ? (
                    <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                      <CircularProgress size={22} />
                    </Box>
                  ) : (
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Time</TableCell>
                          <TableCell>Purpose</TableCell>
                          <TableCell>Rack</TableCell>
                          <TableCell>Employee</TableCell>
                          <TableCell>Wt</TableCell>
                          <TableCell>Weight source</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(bag.scans || []).map((s, i) => (
                          <TableRow key={`${bag.bag_id}-${s.id || i}`}>
                            <TableCell sx={{ whiteSpace: "nowrap" }}>
                              {fmtTs(s.scanned_at_parsed)}
                            </TableCell>
                            <TableCell>{s.purpose || "—"}</TableCell>
                            <TableCell>{s.rack || "—"}</TableCell>
                            <TableCell>{s.user_name || "—"}</TableCell>
                            <TableCell>{s.weight_lbs ?? "—"}</TableCell>
                            <TableCell
                              title={
                                [
                                  s.weight_source,
                                  s.weight_attach_batch_id != null
                                    ? `Batch ${s.weight_attach_batch_id}`
                                    : "",
                                  s.weight_attach_reason,
                                ]
                                  .filter(Boolean)
                                  .join(" · ") || undefined
                              }
                            >
                              {s.weight_source
                                ? [
                                    s.weight_source === "portal_weight_num_historical"
                                      ? "Historical portal"
                                      : s.weight_source === "portal_weight_num"
                                        ? "Portal"
                                        : s.weight_source,
                                    formatWeightObservedEt(s.weight_observed_at),
                                    s.weight_attach_batch_id != null
                                      ? `Batch ${s.weight_attach_batch_id}`
                                      : "",
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                : "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                        {(bag.scans || []).length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={6}>No scans</TableCell>
                          </TableRow>
                        ) : null}
                      </TableBody>
                    </Table>
                  )}

                  {!loadingDetail &&
                  (bag.pre_weight_source ||
                    bag.post_weight_source ||
                    bag.pre_weight_observed_at ||
                    bag.post_weight_observed_at) ? (
                    <Box sx={{ mt: 1.25 }}>
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
                        Weight enrichment (audit)
                      </Typography>
                      {bag.pre_weight_lbs != null || bag.pre_weight_source ? (
                        <Typography variant="caption" display="block">
                          Pre {bag.pre_weight_lbs ?? "—"} lbs
                          {bag.pre_weight_source
                            ? ` · ${
                                bag.pre_weight_source === "portal_weight_num_historical"
                                  ? "Recovered from historical portal"
                                  : bag.pre_weight_source === "portal_weight_num"
                                    ? "Captured from portal"
                                    : bag.pre_weight_source
                              }`
                            : ""}
                          {bag.pre_weight_observed_at || bag.pre_weight_at
                            ? ` · entered ${formatWeightObservedEt(bag.pre_weight_at) || "—"} · observed ${formatWeightObservedEt(bag.pre_weight_observed_at) || "—"}`
                            : ""}
                          {bag.pre_weight_attach_batch_id != null
                            ? ` · Batch ${bag.pre_weight_attach_batch_id}`
                            : ""}
                        </Typography>
                      ) : null}
                      {(bag.post_weight_value ?? bag.post_weight_lbs) != null ||
                      bag.post_weight_source ? (
                        <Typography variant="caption" display="block">
                          Post {bag.post_weight_value ?? bag.post_weight_lbs ?? "—"} lbs
                          {bag.post_weight_source
                            ? ` · ${
                                bag.post_weight_source === "portal_weight_num_historical"
                                  ? "Recovered from historical portal"
                                  : bag.post_weight_source === "portal_weight_num"
                                    ? "Captured from portal"
                                    : bag.post_weight_source
                              }`
                            : ""}
                          {bag.post_weight_observed_at || bag.post_weight_at
                            ? ` · entered ${formatWeightObservedEt(bag.post_weight_at) || "—"} · observed ${formatWeightObservedEt(bag.post_weight_observed_at) || "—"}`
                            : ""}
                          {bag.post_weight_attach_batch_id != null
                            ? ` · Batch ${bag.post_weight_attach_batch_id}`
                            : ""}
                        </Typography>
                      ) : null}
                    </Box>
                  ) : null}

                  {!loadingDetail &&
                  (bag.last_edit_id || (bag.corrections || []).length > 0) ? (
                    <>
                      <Stack
                        direction="row"
                        alignItems="center"
                        justifyContent="space-between"
                        sx={{ mt: 1.5, mb: 0.5 }}
                      >
                        <Typography variant="subtitle2" fontWeight={700}>
                          Manager corrections / Edit history
                        </Typography>
                        {!readOnly && bag.last_edit_id && bag.last_edit_undoable !== false ? (
                          <Button
                            size="small"
                            data-testid="undo-last-change"
                            disabled={saving}
                            onClick={async () => {
                              setSaving(true);
                              setError("");
                              try {
                                const res = await postVeewashStep1Correction({
                                  action: "undo_bag_edit",
                                  bag_id: bag.bag_id,
                                  selected_date_et: selectedDateEt,
                                  edit_id: bag.last_edit_id,
                                  reason: "Undo last Edit Bag change",
                                });
                                if (!res?.data?.ok) {
                                  setError(res?.data?.error || "Undo failed");
                                  return;
                                }
                                await refreshBagAfterEdit(bag.bag_id, { closeEditor: false });
                              } catch (e) {
                                setError(
                                  e?.response?.data?.error || e?.message || "Undo failed"
                                );
                              } finally {
                                setSaving(false);
                              }
                            }}
                          >
                            Undo Last Change
                          </Button>
                        ) : null}
                      </Stack>
                      {(bag.corrections || []).slice(0, 5).map((c, i) => (
                        <Typography key={i} variant="caption" display="block">
                          {fmtTs(c.created_at)} · {c.action} · {c.actor_display_name || "—"} ·{" "}
                          {c.reason_text}
                        </Typography>
                      ))}
                      {bag.last_edit_id ? (
                        <Typography variant="caption" display="block" color="text.secondary">
                          Last Edit Bag #{bag.last_edit_id}
                          {bag.last_edit_reason ? ` · ${bag.last_edit_reason}` : ""}
                        </Typography>
                      ) : null}
                    </>
                  ) : null}
                </AccordionDetails>
              </Accordion>
            );
          })}
          {(page > 1 || hasMore) && (
            <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ pt: 1 }}>
              <Button size="small" disabled={page <= 1 || loading} onClick={() => load(page - 1)}>
                Previous
              </Button>
              <Button size="small" disabled={!hasMore || loading} onClick={() => load(page + 1)}>
                Next
              </Button>
            </Stack>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
