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
import {
  getManagementRinseWfReviewAction,
  getManagementRinseWfReviewScans,
  postVeewashStep1Correction,
} from "../../api";
import { fetchReviewDrawerAction } from "./reviewDrawerDetailLoad";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { CompactEtDateTimeField } from "../PayrollDateTimeField";
import { authoritativeEvidencePre, parseWeightInput } from "../shift/editBagHelpers";
import ManagementCopyableId from "./ManagementCopyableId";
import { displayCustomerName } from "../../utils/displayCustomerName";
import {
  bagBulkReviewUnresolved,
  bagHasMissingPortal,
  bagHasSpecialtyBulk,
  resolveReviewDrawerInlineVariant,
  bulkItemsDraft,
  catalogSpecialtyLines,
  fmtLbs,
  suggestedCompleteAudit,
  toPickerValue,
  validateMissingComplete,
  validateSpecialtyComplete,
  validateSpecialtySave,
} from "./reviewDrawerModel";
import { formatReviewApiError } from "./reviewDisplayLabels";

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

function BulkWorkitemFields({ catalog, bag, readOnly, saving, qty, setQty, noCharge, setNoCharge, noChargeReason, setNoChargeReason }) {
  const initialLines = useMemo(
    () => catalogSpecialtyLines(catalog, bag?.bulk_workitems),
    [catalog, bag?.bulk_workitems],
  );
  const lines = initialLines.map((l) => {
    const q = Number(qty[l.workitem_id] || 0);
    return {
      ...l,
      quantity: q,
      line_total: Math.round((Number(l.unit_price) || 0) * q * 100) / 100,
    };
  });

  const bump = (id, delta) => {
    setQty((prev) => ({ ...prev, [id]: Math.max(0, Number(prev[id] || 0) + delta) }));
  };

  return (
    <Box sx={{ mt: 1, p: 1, bgcolor: "#fffbeb", border: "1px solid #fde68a", borderRadius: 1 }}>
      <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.6, color: "#92400e" }}>
        Bulk items require review
      </Typography>
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
            value={
              NO_CHARGE_REASONS.includes(noChargeReason)
                ? noChargeReason
                : noChargeReason
                  ? "Other"
                  : ""
            }
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
    </Box>
  );
}

function ScanChronology({ selectedDateEt, bagId, open }) {
  const [scans, setScans] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !selectedDateEt || !bagId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError("");
    setScans([]);
    (async () => {
      try {
        const res = await getManagementRinseWfReviewScans(selectedDateEt, bagId);
        if (cancelled) return;
        if (!res?.data?.ok) {
          setError(formatReviewApiError(res?.data?.error, res?.data?.message || "Failed to load scans"));
          return;
        }
        setScans(Array.isArray(res.data.scans) ? res.data.scans : []);
      } catch (err) {
        if (!cancelled) {
          setError(
            formatReviewApiError(
              err?.response?.data?.error,
              err?.response?.data?.message || err?.message || "Failed to load scans",
            ),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, selectedDateEt, bagId]);

  if (!open) return null;
  if (loading) {
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
        <CircularProgress size={14} />
        <Typography sx={{ fontSize: 12, color: "#64748b" }}>Loading scans…</Typography>
      </Stack>
    );
  }
  if (error) {
    return (
      <Alert severity="error" sx={{ mt: 1, py: 0.25 }}>
        {error}
      </Alert>
    );
  }
  if (!scans.length) {
    return (
      <Typography sx={{ mt: 1, fontSize: 12, color: "#64748b" }}>No scan events found.</Typography>
    );
  }
  return (
    <Box sx={{ mt: 1, maxHeight: 220, overflow: "auto", border: "1px solid #e2e8f0", borderRadius: 1, p: 0.75 }}>
      {scans.map((s, idx) => (
        <Typography key={`${s.id || idx}-${s.scanned_at_parsed || idx}`} sx={{ fontSize: 11, color: "#475569", py: 0.25 }}>
          {[fmtTime(s.scanned_at_parsed || s.scanned_at), s.user_name || s.employee, s.purpose, s.rack]
            .filter(Boolean)
            .join(" · ")}
        </Typography>
      ))}
    </Box>
  );
}

function MissingPortalInline({ bag, catalog, selectedDateEt, readOnly, onSaved, variant = "missing" }) {
  const isSpecialty = variant === "specialty";
  const bulkRequired = !isSpecialty && bagBulkReviewUnresolved(bag);
  const initialLines = useMemo(
    () => catalogSpecialtyLines(catalog, bag?.bulk_workitems),
    [catalog, bag?.bulk_workitems],
  );
  const [postLbs, setPostLbs] = useState(() =>
    bag?.post_weight_lbs == null || bag?.post_weight_lbs === "" ? "" : String(bag.post_weight_lbs),
  );
  const [preLbs, setPreLbs] = useState(() => {
    const pre = authoritativeEvidencePre(bag);
    return pre == null ? "" : String(pre);
  });
  const [preEditing, setPreEditing] = useState(false);
  const [completedBy, setCompletedBy] = useState(
    () => bag?.completion_employee || bag?.completed_by || "",
  );
  const [completionAt, setCompletionAt] = useState(() => toPickerValue(bag?.completion_at));
  const [qty, setQty] = useState(() =>
    Object.fromEntries(initialLines.map((l) => [l.workitem_id, l.quantity])),
  );
  const [noCharge, setNoCharge] = useState(
    String(bag?.bulk_resolution?.resolution_type || "") === "no_charge",
  );
  const [noChargeReason, setNoChargeReason] = useState(
    bag?.bulk_resolution?.no_charge_reason || "",
  );
  const [scansOpen, setScansOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPostLbs(
      bag?.post_weight_lbs == null || bag?.post_weight_lbs === ""
        ? ""
        : String(bag.post_weight_lbs),
    );
    const pre = authoritativeEvidencePre(bag);
    setPreLbs(pre == null ? "" : String(pre));
    setPreEditing(false);
    setCompletedBy(bag?.completion_employee || bag?.completed_by || "");
    setCompletionAt(toPickerValue(bag?.completion_at));
    setQty(Object.fromEntries(initialLines.map((l) => [l.workitem_id, l.quantity])));
    setNoCharge(String(bag?.bulk_resolution?.resolution_type || "") === "no_charge");
    setNoChargeReason(bag?.bulk_resolution?.no_charge_reason || "");
  }, [bag?.bag_id, bag?._detailsLoaded, bag?.manager_edit_version]); // eslint-disable-line react-hooks/exhaustive-deps

  const lockReady = Boolean(bag?._detailsLoaded);
  const lines = initialLines.map((l) => ({
    ...l,
    quantity: Number(qty[l.workitem_id] || 0),
    line_total: Math.round((Number(l.unit_price) || 0) * Number(qty[l.workitem_id] || 0) * 100) / 100,
  }));
  const bulkAvailability = bulkRequired
    ? validateSpecialtySave({
        lines,
        noChargeable: noCharge,
        noChargeReason,
        saving,
        readOnly,
        catalogReady: Array.isArray(catalog),
      })
    : { enabled: true, reason: null };
  const completionAvailability = isSpecialty
    ? validateSpecialtyComplete({
        completedBy,
        completionAt,
        postWeightLbs: postLbs,
        lockReady,
        saving,
        readOnly,
        bulkRequired,
        lines,
        noChargeable: noCharge,
        noChargeReason,
        catalogReady: Array.isArray(catalog),
      })
    : validateMissingComplete({
        completedBy,
        completionAt,
        postWeightLbs: postLbs,
        lockReady,
        saving,
        readOnly,
      });
  const canSave =
    completionAvailability.enabled &&
    bulkAvailability.enabled &&
    !saving &&
    !readOnly;

  const saveBlockReason =
    (!bulkAvailability.enabled && bulkAvailability.reason) ||
    (!completionAvailability.enabled && completionAvailability.reason) ||
    null;

  const save = async () => {
    if (!canSave) {
      setError(saveBlockReason || "Cannot save");
      return;
    }
    const baselinePre = authoritativeEvidencePre(bag);
    const parsedPre = parseWeightInput(preLbs);
    const draft = {
      service_type: String(bag?.service_type || "WF").toUpperCase(),
      rush_flag: bag?.rush_flag || "NON-RUSH",
      post_weight_lbs: parseWeightInput(postLbs),
      completed_by: completedBy,
      completion_at: completionAt,
      ...(bulkRequired || (isSpecialty && bagBulkReviewUnresolved(bag))
        ? bulkItemsDraft(lines, { noChargeable: noCharge, noChargeReason })
        : {}),
    };
    if (preEditing || (parsedPre != null && parsedPre !== baselinePre)) {
      draft.pre_weight_lbs = parsedPre;
    }
    const audit = suggestedCompleteAudit({
      draft,
      baselineBag: bag,
      variant: isSpecialty ? "specialty" : "missing",
    });
    const reasonCode = audit.reasonCode;
    const reasonNote = audit.reasonNote;
    setSaving(true);
    setError("");
    try {
      const res = await postVeewashStep1Correction({
        action: "edit_bag",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: reasonNote,
        reason_code: reasonCode,
        reason_note: reasonNote,
        expected_updated_at: bag.updated_at || bag.day_bag_updated_at || null,
        expected_manager_edit_version:
          bag.manager_edit_version != null ? Number(bag.manager_edit_version) : null,
        outcome_action: "mark_completed",
        draft,
      });
      if (!res?.data?.ok) {
        if (res?.data?.error === "conflict") {
          setError(formatReviewApiError("conflict"));
          return;
        }
        setError(formatReviewApiError(res?.data?.error, res?.data?.message || "Save failed"));
        return;
      }
      onSaved?.(res.data, { kind: "missing", bagId: bag.bag_id });
    } catch (err) {
      setError(
        formatReviewApiError(
          err?.response?.data?.error,
          err?.response?.data?.message || err?.message || "Save failed",
        ),
      );
    } finally {
      setSaving(false);
    }
  };

  const revertPre = () => {
    const pre = authoritativeEvidencePre(bag);
    setPreLbs(pre == null ? "" : String(pre));
    setPreEditing(false);
  };

  const completionEmp = bag?.completion_employee || bag?.completed_by;
  const completionTime = fmtTime(bag?.completion_at);
  const managerPre = bag?.corrected_pre_weight_lbs;

  return (
    <Box sx={{ mt: 0.75 }} data-testid={isSpecialty ? "review-specialty-inline" : "review-missing-inline"}>
      <Stack direction="row" spacing={1.25} flexWrap="wrap" sx={{ mb: 0.5 }} alignItems="center">
        <Typography data-testid="review-drawer-pre" sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
          PRE {preEditing ? "" : evidencePreLabel(bag)}
        </Typography>
        {!preEditing ? (
          <Button
            size="small"
            variant="text"
            onClick={() => setPreEditing(true)}
            disabled={readOnly || saving}
            sx={{ textTransform: "none", fontWeight: 700, minWidth: 0, px: 0.5 }}
          >
            Edit PRE
          </Button>
        ) : null}
        <Typography data-testid="review-drawer-post" sx={{ fontSize: 12, color: "#475569", fontWeight: 700 }}>
          POST {fmtLbs(bag?.post_weight_lbs ?? bag?.post_weight_value) || "—"}
        </Typography>
      </Stack>
      {preEditing ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
          <TextField
            size="small"
            type="number"
            label="PRE lbs (manager correction)"
            value={preLbs}
            onChange={(e) => setPreLbs(e.target.value)}
            inputProps={{ step: 0.1, min: 0 }}
            sx={{ flex: 1 }}
            disabled={readOnly || saving}
          />
          <Button size="small" onClick={revertPre} disabled={saving} sx={{ textTransform: "none" }}>
            Revert
          </Button>
        </Stack>
      ) : null}
      {managerPre != null ? (
        <Typography sx={{ fontSize: 11, color: "#64748b", mb: 0.5 }}>
          Manager PRE override active ({fmtLbs(managerPre)})
        </Typography>
      ) : null}
      {completionEmp || completionTime ? (
        <Typography sx={{ fontSize: 12, color: "#94a3b8", mb: 0.5 }}>
          Detected: {[completionEmp, completionTime].filter(Boolean).join(" · ")}
        </Typography>
      ) : null}
      {bulkRequired || (isSpecialty && lines.some((l) => Number(l.quantity) > 0)) ? (
        <BulkWorkitemFields
          catalog={catalog}
          bag={bag}
          readOnly={readOnly}
          saving={saving}
          qty={qty}
          setQty={setQty}
          noCharge={noCharge}
          setNoCharge={setNoCharge}
          noChargeReason={noChargeReason}
          setNoChargeReason={setNoChargeReason}
        />
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 0.75, py: 0.25, mt: 0.75 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <TextField
        size="small"
        type="number"
        label="POST lbs"
        value={postLbs}
        onChange={(e) => setPostLbs(e.target.value)}
        inputProps={{ step: 0.1, min: 0 }}
        fullWidth
        disabled={readOnly || saving}
        sx={{ mt: 0.75 }}
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
      {!canSave && saveBlockReason ? (
        <Typography sx={{ mt: 0.5, fontSize: 11, color: "#b45309" }}>
          {saveBlockReason}
        </Typography>
      ) : null}
      <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        <Button
          data-testid="review-save-complete"
          size="small"
          variant="contained"
          disabled={!canSave}
          onClick={save}
          sx={{ textTransform: "none", fontWeight: 800 }}
        >
          {saving ? "Saving…" : "Save & Complete"}
        </Button>
        <Button
          data-testid="review-view-scans"
          size="small"
          variant="outlined"
          onClick={() => setScansOpen((v) => !v)}
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          {scansOpen ? "Hide Scans" : "View Scans"}
        </Button>
      </Stack>
      <ScanChronology selectedDateEt={selectedDateEt} bagId={bag.bag_id} open={scansOpen} />
    </Box>
  );
}

function SpecialtyInline({ bag, catalog, selectedDateEt, readOnly, onSaved }) {
  const initialLines = useMemo(
    () => catalogSpecialtyLines(catalog, bag?.bulk_workitems),
    [catalog, bag?.bulk_workitems],
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
  const [scansOpen, setScansOpen] = useState(false);
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
  const availability = validateSpecialtySave({
    lines,
    noChargeable: noCharge,
    noChargeReason,
    saving,
    readOnly,
    catalogReady: Array.isArray(catalog),
  });

  const save = async () => {
    if (!availability.enabled) {
      setError(availability.reason || "Cannot save");
      return;
    }
    const reason = noCharge ? String(noChargeReason || "").trim() : "Specialty review";
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
          : lines.filter((l) => Number(l.quantity) > 0).map((l) => ({
              workitem_id: l.workitem_id,
              quantity: l.quantity,
            })),
      });
      if (!res?.data?.ok) {
        setError(formatReviewApiError(res?.data?.error, res?.data?.message || "Failed to save specialty"));
        return;
      }
      onSaved?.(res.data, { kind: "specialty", bagId: bag.bag_id });
    } catch (err) {
      setError(
        formatReviewApiError(
          err?.response?.data?.error,
          err?.response?.data?.message || err?.message || "Failed to save specialty",
        ),
      );
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
      <BulkWorkitemFields
        catalog={catalog}
        bag={bag}
        readOnly={readOnly}
        saving={saving}
        qty={qty}
        setQty={setQty}
        noCharge={noCharge}
        setNoCharge={setNoCharge}
        noChargeReason={noChargeReason}
        setNoChargeReason={setNoChargeReason}
      />
      <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
        <Button
          data-testid="review-save-specialty"
          size="small"
          variant="contained"
          disabled={!availability.enabled}
          onClick={save}
          sx={{ textTransform: "none", fontWeight: 800 }}
        >
          {saving ? "Saving…" : "Save Specialty"}
        </Button>
        <Button
          data-testid="review-view-scans"
          size="small"
          variant="outlined"
          onClick={() => setScansOpen((v) => !v)}
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          {scansOpen ? "Hide Scans" : "View Scans"}
        </Button>
      </Stack>
      <ScanChronology selectedDateEt={selectedDateEt} bagId={bag.bag_id} open={scansOpen} />
    </Box>
  );
}

/**
 * Missing From Portal / Specialty queue row — tap header to expand inline resolver.
 */
export default function ManagementRinseWfReviewDrawerRow({
  bag,
  drawerCategory = null,
  selectedDateEt,
  readOnly,
  expanded,
  onToggle,
  onSaved,
}) {
  const [actionBag, setActionBag] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const merged = actionBag
    ? {
        ...bag,
        ...actionBag,
        bag_id: bag.bag_id,
        category: bag?.category || actionBag?.category || actionBag?.review_category || drawerCategory,
        review_category:
          actionBag?.review_category || bag?.review_category || bag?.category || drawerCategory,
        _detailsLoaded: true,
      }
    : {
        ...bag,
        category: bag?.category || bag?.review_category || drawerCategory,
        review_category: bag?.review_category || bag?.category || drawerCategory,
        _detailsLoaded: false,
      };
  const inlineVariant = resolveReviewDrawerInlineVariant(merged, drawerCategory);

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
            formatReviewApiError(
              err?.response?.data?.error,
              err?.response?.data?.message || err?.message || "Failed to load bag details",
            ),
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
        {displayCustomerName(merged.customer_name) || "Customer unavailable"}
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
        ) : inlineVariant === "missing" ? (
          <MissingPortalInline
            bag={merged}
            catalog={catalog || []}
            selectedDateEt={selectedDateEt}
            readOnly={readOnly}
            onSaved={onSaved}
          />
        ) : inlineVariant === "specialty_bulk" ? (
          <SpecialtyInline
            bag={merged}
            catalog={catalog || []}
            selectedDateEt={selectedDateEt}
            readOnly={readOnly}
            onSaved={onSaved}
          />
        ) : inlineVariant === "specialty_review" ? (
          <MissingPortalInline
            bag={merged}
            catalog={catalog || []}
            selectedDateEt={selectedDateEt}
            readOnly={readOnly}
            onSaved={onSaved}
            variant="specialty"
          />
        ) : (
          <Typography sx={{ mt: 0.75, fontSize: 12, color: "#64748b" }}>
            No inline actions for this review category.
          </Typography>
        )}
      </Collapse>
    </Box>
  );
}
