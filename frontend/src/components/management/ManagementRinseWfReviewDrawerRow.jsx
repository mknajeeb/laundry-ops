import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Collapse,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getManagementRinseWfReviewAction, postVeewashStep1Correction } from "../../api";
import { fetchReviewDrawerAction } from "./reviewDrawerDetailLoad";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { CompactEtDateTimeField } from "../PayrollDateTimeField";
import { authoritativeEvidencePre, parseWeightInput } from "../shift/editBagHelpers";
import ManagementCopyableId from "./ManagementCopyableId";
import {
  bagHasMissingPortal,
  bagHasSpecialtyBulk,
  catalogSpecialtyLines,
  fmtLbs,
  suggestedCompleteAudit,
  toPickerValue,
  validateMissingComplete,
  validateSpecialtySave,
} from "./reviewDrawerModel";

const NO_CHARGE_REASONS = ["Customer cancelled", "False alarm", "Duplicate scan", "Other"];

function rushLabel(flag) {
  const raw = String(flag || "").trim().toLowerCase();
  if (!raw || raw === "non-rush" || raw === "non_rush" || raw === "nonrush") {
    return "Non-Rush";
  }
  if (raw === "rush" || raw.includes("rush")) return "Rush";
  return String(flag);
}

function fmtTime(v) {
  if (!v) return null;
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function evidencePreLabel(bag) {
  const pre = authoritativeEvidencePre(bag);
  return pre == null ? "—" : fmtLbs(pre) || "—";
}

function MissingPortalInline({
  bag,
  selectedDateEt,
  readOnly,
  requiresDetailedReview,
  onDetailedReview,
  onSaved,
}) {
  const [postLbs, setPostLbs] = useState(() =>
    bag?.post_weight_lbs == null || bag?.post_weight_lbs === ""
      ? ""
      : String(bag.post_weight_lbs),
  );
  const [completedBy, setCompletedBy] = useState(
    () => bag?.completion_employee || bag?.completed_by || "",
  );
  const [completionAt, setCompletionAt] = useState(() => toPickerValue(bag?.completion_at));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPostLbs(
      bag?.post_weight_lbs == null || bag?.post_weight_lbs === ""
        ? ""
        : String(bag.post_weight_lbs),
    );
    setCompletedBy(bag?.completion_employee || bag?.completed_by || "");
    setCompletionAt(toPickerValue(bag?.completion_at));
  }, [bag?.bag_id, bag?._detailsLoaded, bag?.manager_edit_version]); // eslint-disable-line react-hooks/exhaustive-deps

  const lockReady = Boolean(bag?._detailsLoaded);
  const availability = validateMissingComplete({
    completedBy,
    completionAt,
    postWeightLbs: postLbs,
    lockReady,
    saving,
    readOnly,
  });

  const save = async () => {
    if (requiresDetailedReview) {
      onDetailedReview?.(bag);
      return;
    }
    if (!availability.enabled) {
      setError(availability.reason || "Cannot save");
      return;
    }
    const draft = {
      service_type: String(bag?.service_type || "WF").toUpperCase(),
      rush_flag: bag?.rush_flag || "NON-RUSH",
      pre_weight_lbs: authoritativeEvidencePre(bag),
      post_weight_lbs: parseWeightInput(postLbs),
      completed_by: completedBy,
      completion_at: completionAt,
    };
    const audit = suggestedCompleteAudit({ draft, baselineBag: bag });
    setSaving(true);
    setError("");
    try {
      const res = await postVeewashStep1Correction({
        action: "edit_bag",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: audit.reasonNote,
        reason_code: audit.reasonCode || "DISAPPEARED_WITHOUT_COMPLETION",
        reason_note: audit.reasonNote,
        expected_updated_at: bag.updated_at || bag.day_bag_updated_at || null,
        expected_manager_edit_version:
          bag.manager_edit_version != null ? Number(bag.manager_edit_version) : null,
        outcome_action: "mark_completed",
        draft,
      });
      if (!res?.data?.ok) {
        if (res?.data?.error === "conflict") {
          setError("This bag was updated while you were reviewing it. Close and reopen to retry.");
          return;
        }
        setError(res?.data?.message || res?.data?.error || "Save failed");
        return;
      }
      onSaved?.(res.data, { kind: "missing", bagId: bag.bag_id });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const completionEmp = bag?.completion_employee || bag?.completed_by;
  const completionTime = fmtTime(bag?.completion_at);

  return (
    <Box sx={{ mt: 0.75 }} data-testid="review-missing-inline">
      <Stack direction="row" spacing={1.25} flexWrap="wrap" sx={{ mb: 0.5 }}>
        <Typography data-testid="review-drawer-pre" sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
          PRE {evidencePreLabel(bag)}
        </Typography>
        <Typography data-testid="review-drawer-post" sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
          POST {fmtLbs(bag?.post_weight_lbs ?? bag?.post_weight_value) || "—"}
        </Typography>
      </Stack>
      {completionEmp || completionTime ? (
        <Typography sx={{ fontSize: 12, color: "#94a3b8", mb: 0.5 }}>
          Detected: {[completionEmp, completionTime].filter(Boolean).join(" · ")}
        </Typography>
      ) : null}
      {requiresDetailedReview ? (
        <Alert severity="warning" sx={{ py: 0.35, mb: 0.75 }}>
          Bulk items — Detailed Review required
        </Alert>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 0.75, py: 0.25 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {!requiresDetailedReview ? (
        <>
          <TextField
            size="small"
            type="number"
            label="POST lbs"
            value={postLbs}
            onChange={(e) => setPostLbs(e.target.value)}
            inputProps={{ step: 0.1, min: 0 }}
            fullWidth
            disabled={readOnly || saving}
          />
          <FoldingUserSelect
            label="Completion employee"
            value={completedBy}
            onChange={setCompletedBy}
            allowEmpty
            sx={{ width: "100%", minWidth: 0, mt: 1 }}
          />
          <Box sx={{ mt: 1 }}>
            <CompactEtDateTimeField
              label="Completion date & time (ET)"
              value={completionAt}
              onChange={setCompletionAt}
              disabled={readOnly || saving}
            />
          </Box>
          {!lockReady ? (
            <Typography sx={{ mt: 0.5, fontSize: 11, color: "#64748b" }}>
              Loading bag details…
            </Typography>
          ) : null}
          {!availability.enabled && availability.reason ? (
            <Typography sx={{ mt: 0.5, fontSize: 11, color: "#b45309" }}>
              {availability.reason}
            </Typography>
          ) : null}
        </>
      ) : null}
      <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        <Button
          data-testid="review-save-complete"
          size="small"
          variant="contained"
          disabled={requiresDetailedReview ? false : !availability.enabled}
          onClick={save}
          sx={{ textTransform: "none", fontWeight: 800 }}
        >
          {saving
            ? "Saving…"
            : requiresDetailedReview
              ? "Detailed Review"
              : "Save & Complete"}
        </Button>
        <Button
          data-testid="review-detailed-review"
          size="small"
          variant="outlined"
          onClick={() => onDetailedReview?.(bag)}
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          Detailed Review
        </Button>
      </Stack>
    </Box>
  );
}

function SpecialtyInline({ bag, catalog, selectedDateEt, readOnly, onSaved }) {
  const initialLines = useMemo(
    () => catalogSpecialtyLines(catalog, bag?.bulk_workitems),
    [catalog, bag?.bag_id, bag?.bulk_workitems],
  );
  const [qty, setQty] = useState(() =>
    Object.fromEntries(initialLines.map((l) => [l.workitem_id, l.quantity])),
  );
  const [noCharge, setNoCharge] = useState(
    String(bag?.bulk_resolution?.resolution_type || "") === "no_charge",
  );
  const [noChargeReason, setNoChargeReason] = useState(
    bag?.bulk_resolution?.no_charge_reason || "",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setQty(Object.fromEntries(initialLines.map((l) => [l.workitem_id, l.quantity])));
    setNoCharge(String(bag?.bulk_resolution?.resolution_type || "") === "no_charge");
    setNoChargeReason(bag?.bulk_resolution?.no_charge_reason || "");
  }, [bag?.bag_id, initialLines, bag?.bulk_resolution]);

  const lines = initialLines.map((l) => {
    const q = Number(qty[l.workitem_id] || 0);
    return {
      ...l,
      quantity: q,
      line_total: Math.round((Number(l.unit_price) || 0) * q * 100) / 100,
    };
  });
  const bulkTotal = lines.reduce((s, l) => s + (l.line_total || 0), 0);
  const availability = validateSpecialtySave({
    lines,
    noChargeable: noCharge,
    noChargeReason,
    saving,
    readOnly,
    catalogReady: Array.isArray(catalog),
  });

  const bump = (id, delta) => {
    setQty((prev) => ({ ...prev, [id]: Math.max(0, Number(prev[id] || 0) + delta) }));
  };

  const save = async () => {
    if (!availability.enabled) {
      setError(availability.reason || "Cannot save");
      return;
    }
    const reason = noCharge
      ? String(noChargeReason || "").trim()
      : "Specialty review";
    setSaving(true);
    setError("");
    try {
      const res = await postVeewashStep1Correction({
        action: "save_bulk_workitems",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason,
        no_chargeable: noCharge,
        no_charge_reason: noCharge ? reason : undefined,
        items: noCharge
          ? []
          : lines
              .filter((l) => Number(l.quantity) > 0)
              .map((l) => ({ workitem_id: l.workitem_id, quantity: l.quantity })),
      });
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Failed to save specialty");
        return;
      }
      onSaved?.(res.data, { kind: "specialty", bagId: bag.bag_id });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Failed to save specialty");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ mt: 0.75, p: 1, bgcolor: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 1 }}>
      <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.6, color: "#64748b" }}>
        Specialty items
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mt: 1, py: 0.25 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {!noCharge
        ? lines.map((line) => (
            <Box key={line.workitem_id} sx={{ mt: 1 }}>
              <Typography sx={{ fontWeight: 700, fontSize: 13 }}>{line.name}</Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.35 }}>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={readOnly || saving}
                  onClick={() => bump(line.workitem_id, -1)}
                  sx={{ minWidth: 36 }}
                >
                  −
                </Button>
                <Typography fontFamily="monospace" sx={{ minWidth: 24, textAlign: "center" }}>
                  {line.quantity}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={readOnly || saving}
                  onClick={() => bump(line.workitem_id, 1)}
                  sx={{ minWidth: 36 }}
                >
                  +
                </Button>
                <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                  ${money(line.unit_price)} · ${money(line.line_total)}
                </Typography>
              </Stack>
            </Box>
          ))
        : null}
      <FormControlLabel
        sx={{ mt: 0.5 }}
        control={
          <Checkbox
            checked={noCharge}
            disabled={readOnly || saving}
            onChange={(e) => setNoCharge(e.target.checked)}
          />
        }
        label="No chargeable bulk items"
      />
      {noCharge ? (
        <FormControl size="small" fullWidth sx={{ mt: 0.5 }}>
          <InputLabel>No-charge reason</InputLabel>
          <Select
            label="No-charge reason"
            value={NO_CHARGE_REASONS.includes(noChargeReason) ? noChargeReason : noChargeReason ? "Other" : ""}
            onChange={(e) => setNoChargeReason(e.target.value)}
            disabled={readOnly || saving}
          >
            {NO_CHARGE_REASONS.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      ) : null}
      <Button
        data-testid="review-save-specialty"
        size="small"
        variant="contained"
        disabled={!availability.enabled}
        onClick={save}
        sx={{ mt: 1, textTransform: "none", fontWeight: 800 }}
      >
        {saving ? "Saving…" : "Save Specialty"}
      </Button>
    </Box>
  );
}

/**
 * Missing From Portal / Specialty queue row — tap header to expand inline resolver.
 */
export default function ManagementRinseWfReviewDrawerRow({
  bag,
  selectedDateEt,
  readOnly,
  expanded,
  onToggle,
  onDetailedReview,
  onSaved,
}) {
  const [actionBag, setActionBag] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const merged = actionBag
    ? { ...bag, ...actionBag, bag_id: bag.bag_id, _detailsLoaded: true }
    : { ...bag, _detailsLoaded: false };
  const showMissing = bagHasMissingPortal(merged);
  const showSpecialty = bagHasSpecialtyBulk(merged);
  const requiresDetailedReview = showMissing && showSpecialty;

  useEffect(() => {
    if (!expanded) {
      setActionBag(null);
      setCatalog(null);
      setError("");
      setLoading(false);
      return undefined;
    }
    if (!selectedDateEt || !bag?.bag_id) return undefined;

    let cancelled = false;
    setLoading(true);
    setError("");
    setActionBag(null);
    setCatalog(null);

    (async () => {
      try {
        const result = await fetchReviewDrawerAction(
          getManagementRinseWfReviewAction,
          selectedDateEt,
          bag.bag_id,
        );
        if (cancelled) return;
        if (!result.ok) {
          setError(result.error);
          setActionBag(null);
          setCatalog([]);
          return;
        }
        setActionBag(result.bag);
        setCatalog(result.catalog);
      } catch (err) {
        if (!cancelled) {
          setError(
            err?.response?.data?.error || err?.message || "Failed to load bag details",
          );
          setActionBag(null);
          setCatalog([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [expanded, selectedDateEt, bag?.bag_id]);

  return (
    <Box
      sx={{ py: 1.1, cursor: "pointer" }}
      data-testid="review-drawer-row"
      onClick={() => onToggle?.(bag.bag_id)}
    >
      <Typography sx={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
        {merged.customer_name || "—"}
      </Typography>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.15 }} flexWrap="wrap">
        <ManagementCopyableId value={merged.bag_id} fontSize={13} fontWeight={700} />
        <Typography sx={{ fontSize: 12, color: "#64748b" }}>· {rushLabel(merged.rush_flag)}</Typography>
      </Stack>
      {!expanded ? (
        <Stack direction="row" spacing={1.25} flexWrap="wrap" sx={{ mt: 0.35 }}>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            PRE {evidencePreLabel(merged)}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            POST {fmtLbs(merged?.post_weight_lbs ?? merged?.post_weight_value) || "—"}
          </Typography>
        </Stack>
      ) : null}

      <Collapse in={expanded} onClick={(e) => e.stopPropagation()}>
        {loading ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1.5 }}>
            <CircularProgress size={16} />
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>Loading details…</Typography>
          </Stack>
        ) : error ? (
          <Alert severity="error" sx={{ mt: 1, py: 0.25 }}>
            {error}
          </Alert>
        ) : showMissing ? (
          <MissingPortalInline
            bag={merged}
            selectedDateEt={selectedDateEt}
            readOnly={readOnly}
            requiresDetailedReview={requiresDetailedReview}
            onDetailedReview={onDetailedReview}
            onSaved={onSaved}
          />
        ) : showSpecialty ? (
          <SpecialtyInline
            bag={merged}
            catalog={catalog || []}
            selectedDateEt={selectedDateEt}
            readOnly={readOnly}
            onSaved={onSaved}
          />
        ) : (
          <Stack direction="row" spacing={1} sx={{ mt: 0.75 }}>
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>Use Detailed Review for this bag.</Typography>
            <Button
              data-testid="review-detailed-review"
              size="small"
              variant="outlined"
              onClick={() => onDetailedReview?.(merged)}
              sx={{ textTransform: "none", fontWeight: 700 }}
            >
              Detailed Review
            </Button>
          </Stack>
        )}
      </Collapse>
    </Box>
  );
}
