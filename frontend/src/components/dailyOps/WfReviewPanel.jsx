import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  DialogContent,
  DialogTitle,
  Divider,
  Drawer,
  FormControlLabel,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import {
  getDailyOperationsWfReviewDetail,
  getDailyOperationsWfReviewQueue,
  previewDailyOperationsWfReview,
  saveDailyOperationsWfReview,
  undoDailyOperationsWfReview,
} from "../../api";

function money(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function lbs(v) {
  if (v == null || v === "" || Number.isNaN(Number(v))) return "Not captured";
  return `${Number(v).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 })} lb`;
}

const FILTERS = [
  { value: "all", label: "All" },
  { value: "review_required", label: "Review Required" },
  { value: "missing_post", label: "Missing POST" },
  { value: "work_items_detected", label: "Work Items Detected" },
  { value: "reviewed", label: "Reviewed" },
  { value: "accepted_exceptions", label: "Accepted Exceptions" },
  { value: "corrected_post", label: "Corrected POST" },
];

function emptyDraft(detail) {
  const lines = detail?.workitems?.lines || [];
  const res = detail?.workitems?.resolution;
  const noBillable = String(res?.resolution_type || "") === "no_charge";
  return {
    corrected_post_weight_lbs:
      detail?.post_weight?.authoritative_post_weight_lbs != null
        ? String(detail.post_weight.authoritative_post_weight_lbs)
        : "",
    post_weight_correction_reason: detail?.post_weight?.correction_reason || "",
    accept_missing_post: false,
    no_billable_items: noBillable,
    no_billable_reason: res?.no_charge_reason || "",
    items: lines.map((l) => ({
      workitem_id: l.workitem_id,
      quantity: l.quantity,
      item_name: l.item_name_snapshot || l.item_name,
      unit_price: l.unit_price_snapshot ?? l.unit_price,
    })),
    notes: detail?.review?.notes || "",
    reason: "",
    version: detail?.review?.version || 1,
  };
}

function buildSaveBody(draft) {
  const correcting = String(draft.corrected_post_weight_lbs || "").trim() !== "";
  return {
    version: draft.version,
    reason: draft.reason,
    notes: draft.notes,
    accept_missing_post: Boolean(draft.accept_missing_post),
    no_billable_items: Boolean(draft.no_billable_items),
    no_billable_reason: draft.no_billable_reason,
    post_weight_correction_reason: draft.post_weight_correction_reason || draft.reason,
    ...(correcting && !draft.accept_missing_post
      ? { corrected_post_weight_lbs: Number(draft.corrected_post_weight_lbs) }
      : {}),
    items: draft.no_billable_items
      ? []
      : (draft.items || []).map((x) => ({
          workitem_id: Number(x.workitem_id),
          quantity: Number(x.quantity),
        })),
  };
}

function Row({ label, value, strong }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={strong ? 700 : 500} textAlign="right">
        {value}
      </Typography>
    </Stack>
  );
}

export default function WfReviewPanel({ dateEt, onSaved }) {
  const isMobile = useMediaQuery("(max-width:900px)");
  const [filter, setFilter] = useState("review_required");
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedBag, setSelectedBag] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [preview, setPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [undoReason, setUndoReason] = useState("");

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = (await getDailyOperationsWfReviewQueue(dateEt, { filter })).data;
      setQueue(payload);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load WF review queue");
      setQueue(null);
    } finally {
      setLoading(false);
    }
  }, [dateEt, filter]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const openBag = async (bagId) => {
    setError("");
    setPreview(null);
    setSelectedBag(bagId);
    try {
      const payload = (await getDailyOperationsWfReviewDetail(dateEt, bagId)).data;
      setDetail(payload);
      setDraft(emptyDraft(payload));
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load bag review");
      setDetail(null);
      setDraft(null);
    }
  };

  const closeDetail = () => {
    setSelectedBag(null);
    setDetail(null);
    setDraft(null);
    setPreview(null);
    setUndoReason("");
  };

  const catalog = detail?.workitems?.catalog || [];
  const labels = detail?.labels || {};

  const addItem = () => {
    const first = catalog[0];
    if (!first) return;
    setDraft((d) => ({
      ...d,
      no_billable_items: false,
      items: [
        ...(d.items || []),
        {
          workitem_id: first.id,
          quantity: 1,
          item_name: first.item_name,
          unit_price: first.current_unit_price,
        },
      ],
    }));
  };

  const runPreview = async () => {
    if (!draft || !selectedBag) return;
    setError("");
    try {
      const body = buildSaveBody(draft);
      const payload = (await previewDailyOperationsWfReview(dateEt, selectedBag, body)).data;
      setPreview(payload);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Preview failed");
    }
  };

  const saveReview = async () => {
    if (!draft || !selectedBag) return;
    setSaving(true);
    setError("");
    try {
      const body = buildSaveBody(draft);
      const payload = (await saveDailyOperationsWfReview(dateEt, selectedBag, body)).data;
      if (!payload?.ok) {
        if (payload?.error === "conflict") {
          setError("Conflict — another manager changed this bag. Reloading…");
          await openBag(selectedBag);
        } else {
          setError(payload?.error || (payload?.errors || []).join(", ") || "Save failed");
        }
        return;
      }
      setDetail(payload.detail);
      setDraft(emptyDraft(payload.detail));
      setPreview(null);
      await loadQueue();
      onSaved?.();
    } catch (e) {
      const data = e?.response?.data;
      if (e?.response?.status === 409 || data?.error === "conflict") {
        setError("Conflict — reload required");
        if (data?.current) {
          setDetail(data.current);
          setDraft(emptyDraft(data.current));
        }
      } else {
        setError(data?.error || (data?.errors || []).join(", ") || e?.message || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  const undoLatest = async () => {
    if (!selectedBag || !undoReason.trim()) {
      setError("Undo reason required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = (
        await undoDailyOperationsWfReview(dateEt, selectedBag, { reason: undoReason.trim() })
      ).data;
      if (!payload?.ok) {
        setError(payload?.error || "Undo failed");
        return;
      }
      setDetail(payload.detail);
      setDraft(emptyDraft(payload.detail));
      setUndoReason("");
      await loadQueue();
      onSaved?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Undo failed");
    } finally {
      setSaving(false);
    }
  };

  const items = queue?.items || [];

  const detailBody =
    detail && draft ? (
      <Stack spacing={2} sx={{ pb: isMobile ? 10 : 2 }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={700}>
            Bag {detail.bag?.bag_id}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Service = WF · Completed {detail.bag?.canonical_completion_timestamp || "—"}
            {detail.bag?.rush_status ? ` · ${detail.bag.rush_status}` : ""}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Day membership: {detail.bag?.membership_source}
          </Typography>
          <Chip size="small" sx={{ mt: 0.5 }} label={detail.review?.status || "REVIEW_REQUIRED"} />
        </Box>

        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            PRE / POST Weight
          </Typography>
          <Stack spacing={0.75}>
            <Row
              label={labels.evidence_pre || "Evidence PRE Weight"}
              value={lbs(detail.pre_weight?.weight_lbs ?? detail.weight_summary?.pre_weight)}
            />
            <Row
              label="PRE timestamp"
              value={detail.pre_weight?.timestamp || detail.weight_summary?.pre_timestamp || "—"}
            />
            <Row label="PRE source" value={detail.pre_weight?.source || detail.weight_summary?.pre_source || "—"} />
            <Typography variant="caption" color="text.secondary">
              {labels.pre_immutable || "PRE is evidence-only and not editable"}
            </Typography>
            <Divider />
            <Row
              label={labels.evidence_post || "Evidence POST Weight"}
              value={lbs(detail.post_weight?.evidence_post_weight_lbs)}
            />
            <Row label="Evidence POST source" value={detail.post_weight?.evidence_source || "Not captured"} />
            <Row label="Scan event ID" value={detail.post_weight?.scan_event_id ?? "—"} />
            <Row
              label="Presence Run"
              value={
                detail.post_weight?.presence_run_id != null
                  ? `#${detail.post_weight.presence_run_id}${
                      detail.post_weight.presence_run_row_id != null
                        ? ` / row ${detail.post_weight.presence_run_row_id}`
                        : ""
                    }`
                  : "—"
              }
            />
            <Row
              label={labels.manager_corrected_post || "Manager-Corrected POST"}
              value={
                detail.post_weight?.manager_corrected
                  ? lbs(detail.post_weight?.authoritative_post_weight_lbs)
                  : "—"
              }
            />
            <Row
              label="Authoritative POST"
              value={
                detail.post_weight?.authoritative_post_weight_lbs != null ||
                detail.weight_summary?.post_weight != null
                  ? lbs(
                      detail.post_weight?.authoritative_post_weight_lbs ??
                        detail.weight_summary?.post_weight
                    )
                  : "—"
              }
            />
            <Row
              label="Authoritative POST source"
              value={detail.post_weight?.source || detail.weight_summary?.post_source || "—"}
            />
            {String(detail.post_weight?.source || "").includes("canonical") ? (
              <Typography variant="caption" color="text.secondary">
                Authoritative POST uses canonical fallback — not a captured Evidence POST.
              </Typography>
            ) : null}
            <TextField
              label="Corrected POST Weight (lbs)"
              size="small"
              type="number"
              value={draft.corrected_post_weight_lbs}
              onChange={(e) => setDraft((d) => ({ ...d, corrected_post_weight_lbs: e.target.value }))}
              inputProps={{ step: "0.01", min: "0" }}
              disabled={draft.accept_missing_post}
            />
            <TextField
              label="Correction reason"
              size="small"
              value={draft.post_weight_correction_reason}
              onChange={(e) =>
                setDraft((d) => ({ ...d, post_weight_correction_reason: e.target.value }))
              }
              disabled={draft.accept_missing_post}
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={draft.accept_missing_post}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      accept_missing_post: e.target.checked,
                      corrected_post_weight_lbs: e.target.checked ? "" : d.corrected_post_weight_lbs,
                    }))
                  }
                />
              }
              label="Accept missing POST (exception)"
            />
          </Stack>
        </Paper>

        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            Detected evidence
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Bulk scans: {detail.workitems?.detected_evidence?.count || 0}
            {detail.workitems?.detected_evidence?.last_at
              ? ` · last ${detail.workitems.detected_evidence.last_at}`
              : ""}
          </Typography>
        </Paper>

        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Billable work items
            </Typography>
            <Button size="small" onClick={addItem} disabled={draft.no_billable_items || !catalog.length}>
              Add item
            </Button>
          </Stack>
          <FormControlLabel
            control={
              <Checkbox
                checked={draft.no_billable_items}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    no_billable_items: e.target.checked,
                    items: e.target.checked ? [] : d.items,
                  }))
                }
              />
            }
            label="Confirm no billable items"
          />
          {draft.no_billable_items ? (
            <TextField
              label="No-billable reason"
              size="small"
              fullWidth
              value={draft.no_billable_reason}
              onChange={(e) => setDraft((d) => ({ ...d, no_billable_reason: e.target.value }))}
              sx={{ mt: 1 }}
            />
          ) : (
            <Stack spacing={1} sx={{ mt: 1 }}>
              {(draft.items || []).map((row, idx) => (
                <Stack key={`${row.workitem_id}-${idx}`} direction={{ xs: "column", sm: "row" }} spacing={1}>
                  <TextField
                    select
                    size="small"
                    label="Item"
                    value={row.workitem_id}
                    onChange={(e) => {
                      const wid = Number(e.target.value);
                      const cat = catalog.find((c) => Number(c.id) === wid);
                      setDraft((d) => {
                        const next = [...d.items];
                        next[idx] = {
                          ...next[idx],
                          workitem_id: wid,
                          item_name: cat?.item_name,
                          unit_price: cat?.current_unit_price,
                        };
                        return { ...d, items: next };
                      });
                    }}
                    sx={{ minWidth: 180, flex: 1 }}
                  >
                    {catalog.map((c) => (
                      <MenuItem key={c.id} value={c.id}>
                        {c.item_name} ({money(c.current_unit_price)})
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    size="small"
                    type="number"
                    label="Qty"
                    value={row.quantity}
                    onChange={(e) => {
                      const q = Number(e.target.value);
                      setDraft((d) => {
                        const next = [...d.items];
                        next[idx] = { ...next[idx], quantity: q };
                        return { ...d, items: next };
                      });
                    }}
                    sx={{ width: 90 }}
                  />
                  <Button
                    size="small"
                    color="inherit"
                    onClick={() =>
                      setDraft((d) => ({
                        ...d,
                        items: d.items.filter((_, i) => i !== idx),
                      }))
                    }
                  >
                    Remove
                  </Button>
                </Stack>
              ))}
            </Stack>
          )}
        </Paper>

        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            Revenue preview
          </Typography>
          <Stack spacing={0.5}>
            <Row
              label={labels.estimated_bag_weight_revenue || "Estimated Bag Weight Revenue"}
              value={money(preview?.estimated_bag_weight_revenue ?? detail.review?.estimated_weight_revenue)}
            />
            <Typography variant="caption" color="text.secondary">
              Estimated allocation for reporting only
            </Typography>
            <Row
              label={labels.workitem_revenue || "Work-Item Revenue"}
              value={money(preview?.workitem_subtotal ?? detail.workitems?.workitem_revenue)}
            />
            <Row
              label={labels.estimated_bag_total || "Estimated Bag Total"}
              value={money(preview?.estimated_bag_total_revenue ?? detail.review?.estimated_total_revenue)}
              strong
            />
          </Stack>
          {preview ? (
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
                {labels.day_level_impact || "Day-Level Revenue Impact"}
              </Typography>
              <Stack spacing={0.5}>
                <Row
                  label="Day WF pounds"
                  value={`${lbs(preview.day_pounds?.current)} → ${lbs(preview.day_pounds?.projected)} (${lbs(
                    preview.day_pounds?.delta
                  )})`}
                />
                <Row
                  label="Day WF weight revenue"
                  value={`${money(preview.day_weight_revenue?.current)} → ${money(
                    preview.day_weight_revenue?.projected
                  )}`}
                />
              </Stack>
            </Box>
          ) : null}
          <Button size="small" sx={{ mt: 1 }} onClick={runPreview}>
            Refresh day-level preview
          </Button>
        </Paper>

        <TextField
          label="Review notes"
          size="small"
          fullWidth
          multiline
          minRows={2}
          value={draft.notes}
          onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
        />
        <TextField
          label="Save reason"
          size="small"
          fullWidth
          required
          value={draft.reason}
          onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
        />

        {(detail.audits || []).length > 0 ? (
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Audit history
            </Typography>
            <Stack spacing={0.75}>
              {detail.audits.slice(0, 8).map((a) => (
                <Typography key={a.id} variant="caption" color="text.secondary">
                  v{a.version_before}→{a.version_after} {a.action}
                  {a.is_undo ? " (undo)" : ""} · {a.actor_display_name || a.actor_user_id || "—"} ·{" "}
                  {a.created_at}
                </Typography>
              ))}
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
              <TextField
                size="small"
                label="Undo reason"
                value={undoReason}
                onChange={(e) => setUndoReason(e.target.value)}
                sx={{ flex: 1 }}
              />
              <Button size="small" variant="outlined" color="warning" onClick={undoLatest} disabled={saving}>
                Undo latest
              </Button>
            </Stack>
          </Paper>
        ) : null}

        {!isMobile ? (
          <Button variant="contained" onClick={saveReview} disabled={saving}>
            {saving ? "Saving…" : "Save Review"}
          </Button>
        ) : null}
      </Stack>
    ) : (
      <Box sx={{ py: 4, textAlign: "center" }}>
        <CircularProgress size={28} />
      </Box>
    );

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ flex: 1 }}>
          WF Review
        </Typography>
        <TextField
          select
          size="small"
          label="Filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          sx={{ minWidth: 180 }}
        >
          {FILTERS.map((f) => (
            <MenuItem key={f.value} value={f.value}>
              {f.label}
            </MenuItem>
          ))}
        </TextField>
        <Button size="small" variant="outlined" onClick={loadQueue} disabled={loading}>
          Refresh queue
        </Button>
        {loading ? <CircularProgress size={18} /> : null}
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}

      {queue && !queue.available ? (
        <Alert severity="info">{queue.message || "WF Review unavailable"}</Alert>
      ) : isMobile ? (
        <Stack spacing={1}>
          {items.map((it) => (
            <Paper
              key={it.bag_id}
              variant="outlined"
              sx={{ p: 1.25, cursor: "pointer" }}
              onClick={() => openBag(it.bag_id)}
            >
              <Typography fontWeight={700}>{it.bag_id}</Typography>
              <Typography variant="body2" color="text.secondary">
                {it.review_status} · {lbs(it.post_weight_lbs)}
              </Typography>
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: "wrap", gap: 0.5 }}>
                {it.flags?.missing_post ? <Chip size="small" label="Missing POST" /> : null}
                {it.flags?.work_items_detected ? <Chip size="small" label="WI detected" /> : null}
                {it.flags?.post_corrected ? <Chip size="small" label="Corrected" /> : null}
              </Stack>
            </Paper>
          ))}
          {!items.length && !loading ? (
            <Typography variant="body2" color="text.secondary">
              No bags in this filter.
            </Typography>
          ) : null}
        </Stack>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: selectedBag ? "minmax(280px, 1fr) minmax(360px, 1.2fr)" : "1fr",
            gap: 2,
          }}
        >
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Bag</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">POST</TableCell>
                  <TableCell>Flags</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((it) => (
                  <TableRow
                    key={it.bag_id}
                    hover
                    selected={selectedBag === it.bag_id}
                    sx={{ cursor: "pointer" }}
                    onClick={() => openBag(it.bag_id)}
                  >
                    <TableCell>{it.bag_id}</TableCell>
                    <TableCell>{it.review_status}</TableCell>
                    <TableCell align="right">{lbs(it.post_weight_lbs)}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        {it.flags?.review_required ? <Chip size="small" label="Required" /> : null}
                        {it.flags?.missing_post ? <Chip size="small" label="No POST" /> : null}
                        {it.flags?.work_items_detected ? <Chip size="small" label="WI" /> : null}
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
                {!items.length && !loading ? (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Typography variant="body2" color="text.secondary">
                        No bags in this filter.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </Box>
          {selectedBag ? (
            <Box>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2" fontWeight={700}>
                  Review detail
                </Typography>
                <IconButton size="small" onClick={closeDetail}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Stack>
              {detailBody}
            </Box>
          ) : null}
        </Box>
      )}

      {isMobile ? (
        <Drawer
          anchor="bottom"
          open={Boolean(selectedBag)}
          onClose={closeDetail}
          PaperProps={{ sx: { maxHeight: "92vh" } }}
        >
          <Box sx={{ p: 2, position: "relative" }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <DialogTitle sx={{ p: 0, fontSize: "1.1rem" }}>WF Review</DialogTitle>
              <IconButton onClick={closeDetail}>
                <CloseIcon />
              </IconButton>
            </Stack>
            <DialogContent sx={{ p: 0 }}>{detailBody}</DialogContent>
            <Box
              sx={{
                position: "sticky",
                bottom: 0,
                left: 0,
                right: 0,
                pt: 1.5,
                pb: 1,
                bgcolor: "background.paper",
                borderTop: "1px solid",
                borderColor: "divider",
              }}
            >
              <Button fullWidth variant="contained" onClick={saveReview} disabled={saving || !draft}>
                {saving ? "Saving…" : "Save Review"}
              </Button>
            </Box>
          </Box>
        </Drawer>
      ) : null}
    </Paper>
  );
}
