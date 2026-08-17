import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { postVeewashStep1Correction, getDailyOperationsHdProductionDetail } from "../../api";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { PayrollDateTimeField } from "../PayrollDateTimeField";
import ManagementCopyableId from "../management/ManagementCopyableId";
import {
  buildEditBagPayloadDraft,
  classifyEditReasonRequirements,
  describeWeightProvenance,
  diffEditBagDraftVsLatest,
  hasCanonicalCompletion,
  isReviewFormDirty,
  reviewActionAvailability,
  validateEditBagDraft,
} from "./editBagHelpers";
import HdReviewFields, { validateHdReviewDraft } from "./HdReviewFields";
import HdReviewPanel from "./HdReviewPanel";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function toPickerValue(v) {
  if (!v) return "";
  const s = String(v).trim().replace(" ", "T");
  const m = s.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return m ? m[1] : s.slice(0, 16);
}

function weightFieldValue(v) {
  if (v === null || v === undefined || v === "") return "";
  return String(v);
}

const NO_CHARGE_REASONS = ["Customer cancelled", "False alarm", "Duplicate scan", "Other"];

const FINAL_ACTIONS = [
  { id: null, label: "Save Review", variant: "contained", color: "primary" },
  { id: "mark_completed", label: "Save & Mark Completed", variant: "contained", color: "success" },
  { id: "return_pending", label: "Save & Return to Pending", variant: "outlined", color: "primary" },
  { id: "exclude", label: "Save & Exclude", variant: "outlined", color: "error" },
];

const HD_FINAL_ACTIONS = [
  { id: null, label: "Save Review", variant: "contained", color: "primary" },
  { id: "mark_completed", label: "Save & Mark Completed", variant: "contained", color: "success" },
];

/**
 * One-shot Review WF Bag modal — evidence, work items, completion, and final
 * outcome in a single atomic save.
 */
export default function EditBagPanel({
  bag,
  selectedDateEt,
  catalog = [],
  readOnly = false,
  initialOutcome = null,
  embedded = false,
  scansSection = null,
  onCancel,
  onSaved,
  onError,
  onUndo,
  onReloadLatest,
}) {
  const existing = bag?.bulk_workitems || [];
  const initialQty = useMemo(() => {
    const map = {};
    for (const wi of catalog) map[wi.id] = 0;
    for (const line of existing) {
      if (line.workitem_id != null) map[line.workitem_id] = Number(line.quantity) || 0;
    }
    return map;
  }, [catalog, existing]);

  const [draft, setDraft] = useState(() => ({
    service_type: String(bag?.service_type || "WF").toUpperCase(),
    rush_flag: bag?.rush_flag || bag?.rush_status || "NON-RUSH",
    entry_at: toPickerValue(bag?.entry_at),
    rack: bag?.entry_rack || bag?.rack || "VeeWash Dirty",
    pre_weight_lbs: weightFieldValue(bag?.pre_weight_lbs),
    post_weight_lbs: weightFieldValue(bag?.post_weight_value ?? bag?.post_weight_lbs),
    no_chargeable: String(bag?.bulk_resolution?.resolution_type || "") === "no_charge",
    no_charge_reason: bag?.bulk_resolution?.no_charge_reason || "",
    completion_at: toPickerValue(bag?.completion_at || bag?.canonical_completion_timestamp),
    completed_by: bag?.completed_by || bag?.canonical_completion_employee || "",
    reason: "",
    reason_code: "",
    reason_note: "",
    item_count: bag?.hd_review?.item_count ?? bag?.item_count ?? "",
    total_revenue: bag?.hd_review?.total_revenue ?? bag?.total_revenue ?? "",
    washed_by_user_id: bag?.hd_review?.washed_by_user_id ?? "",
    folded_by_user_id: bag?.hd_review?.folded_by_user_id ?? "",
    washed_by_name_snapshot: bag?.hd_review?.washed_by_name_snapshot || "",
    folded_by_name_snapshot: bag?.hd_review?.folded_by_name_snapshot || "",
    hd_version: bag?.hd_review?.version ?? 0,
  }));
  const [hdEmployees, setHdEmployees] = useState([]);
  const [qty, setQty] = useState(initialQty);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const [pendingOutcome, setPendingOutcome] = useState(initialOutcome || null);
  const [showCompare, setShowCompare] = useState(false);
  const [undoToast, setUndoToast] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [lockVersion, setLockVersion] = useState(() =>
    bag?.manager_edit_version != null ? Number(bag.manager_edit_version) : null
  );
  const [lockUpdatedAt, setLockUpdatedAt] = useState(
    () => bag?.updated_at || bag?.day_bag_updated_at || null
  );
  const [baselineBag, setBaselineBag] = useState(bag);
  const [correctPre, setCorrectPre] = useState(() => {
    const pre = bag?.pre_weight_lbs;
    return pre === null || pre === undefined || pre === "";
  });
  const [correctPost, setCorrectPost] = useState(false);

  useEffect(() => {
    setQty(initialQty);
  }, [bag?.bag_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (initialOutcome) setPendingOutcome(initialOutcome);
  }, [initialOutcome]);

  // Bag detail is the authoritative lock source. Adopt version once details load;
  // do not keep a stale queue-summary token (prev || next hid concurrent bumps and
  // also pinned truncated list timestamps that disagreed with DB micros).
  useEffect(() => {
    if (!bag?._detailsLoaded) return;
    if (bag?.manager_edit_version != null) {
      setLockVersion(Number(bag.manager_edit_version));
    }
    const nextTs = bag?.updated_at || bag?.day_bag_updated_at || null;
    if (nextTs) setLockUpdatedAt(nextTs);
  }, [bag?._detailsLoaded, bag?.manager_edit_version, bag?.updated_at, bag?.day_bag_updated_at]);

  const isHd = String(draft.service_type || "").toUpperCase() === "HD";

  useEffect(() => {
    if (!isHd || !bag?.bag_id || !selectedDateEt) return undefined;
    let cancelled = false;
    getDailyOperationsHdProductionDetail(selectedDateEt, bag.bag_id)
      .then((res) => {
        if (cancelled) return;
        const detail = res?.data || {};
        const prod = detail.production || {};
        const opts = (detail.employee_options || []).filter((o) => !o.is_external);
        setHdEmployees(opts);
        setDraft((d) => ({
          ...d,
          item_count: prod.total_items != null ? String(prod.total_items) : d.item_count,
          total_revenue: prod.revenue != null ? String(prod.revenue) : d.total_revenue,
          washed_by_user_id: prod.washed_by_user_id ?? d.washed_by_user_id,
          folded_by_user_id: prod.folded_by_user_id ?? d.folded_by_user_id,
          washed_by_name_snapshot: prod.washed_by_name_snapshot || d.washed_by_name_snapshot,
          folded_by_name_snapshot: prod.folded_by_name_snapshot || d.folded_by_name_snapshot,
          hd_version: prod.version ?? d.hd_version ?? 0,
        }));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isHd, bag?.bag_id, selectedDateEt]);

  const reviewStatus = bag?.dashboard_status || bag?.outcome || "—";
  const customer =
    bag?.customer_name || bag?.customer || bag?.portal_customer_name || bag?.account_name || "—";
  const rushLabel = String(draft.rush_flag || "").toUpperCase().includes("NON")
    ? "Non-Rush"
    : "Rush";
  const canonicalOk = hasCanonicalCompletion(baselineBag || bag);

  const preWeightMissing = bag?.pre_weight_lbs === null || bag?.pre_weight_lbs === undefined;
  const postWeightPresent =
    (bag?.post_weight_value ?? bag?.post_weight_lbs) !== null &&
    (bag?.post_weight_value ?? bag?.post_weight_lbs) !== undefined;
  const preWeightNeedsManagerCorrection = preWeightMissing && postWeightPresent;

  const preProvenance = describeWeightProvenance({
    role: "pre",
    weightLbs: bag?.pre_weight_lbs,
    source: bag?.pre_weight_source,
    observedAt: bag?.pre_weight_observed_at,
    portalEventAt: bag?.pre_weight_at,
    attachBatchId: bag?.pre_weight_attach_batch_id,
    attachReason: bag?.pre_weight_attach_reason,
    needsManagerCorrection: preWeightNeedsManagerCorrection,
  });
  const postProvenance = describeWeightProvenance({
    role: "post",
    weightLbs: bag?.post_weight_value ?? bag?.post_weight_lbs,
    source: bag?.post_weight_source,
    observedAt: bag?.post_weight_observed_at,
    portalEventAt: bag?.post_weight_at,
    attachBatchId: bag?.post_weight_attach_batch_id,
    attachReason: bag?.post_weight_attach_reason,
  });

  const lines = useMemo(() => {
    if (isHd) return [];
    const out = catalog.map((wi) => {
      const q = Number(qty[wi.id] || 0);
      const price = Number(wi.current_unit_price) || 0;
      return {
        workitem_id: wi.id,
        name: wi.name,
        unit_price: price,
        quantity: q,
        line_total: Math.round(price * q * 100) / 100,
      };
    });
    for (const line of existing) {
      if (line.workitem_id != null && !catalog.some((c) => c.id === line.workitem_id)) {
        const q = Number(qty[line.workitem_id] ?? line.quantity ?? 0);
        const price = Number(line.unit_price) || 0;
        out.push({
          workitem_id: line.workitem_id,
          name: `${line.workitem_name || "Workitem"} (inactive)`,
          unit_price: price,
          quantity: q,
          line_total: Math.round(price * q * 100) / 100,
        });
      }
    }
    return out;
  }, [catalog, qty, existing, isHd]);

  const bulkTotal = lines.reduce((s, l) => s + (l.line_total || 0), 0);
  // Detail-ready once Management/Step1 marked the bag loaded. Version 0 is valid.
  const lockReady =
    Boolean(bag?._detailsLoaded) &&
    (lockVersion != null || bag?.manager_edit_version != null);
  const dirty = isReviewFormDirty({
    draft,
    baselineBag: baselineBag || bag,
    lines,
    baselineLines: (baselineBag || bag)?.bulk_workitems,
    correctPre,
    correctPost,
  });

  const bump = (id, delta) => {
    setQty((q) => ({ ...q, [id]: Math.max(0, Number(q[id] || 0) + delta) }));
  };

  const activeOutcome = pendingOutcome;
  const policy = classifyEditReasonRequirements({
    draft,
    baselineBag,
    outcome: activeOutcome,
    lines,
  });

  const validateLocal = (outcome = null) => {
    const p = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome,
      lines,
    });
    return validateEditBagDraft({
      reason: draft.reason,
      reasonCode: draft.reason_code || p.suggestedReasonCode,
      reasonNote: draft.reason_note || draft.reason,
      noChargeable: draft.no_chargeable,
      noChargeReason: draft.no_charge_reason,
      lines,
      isHd,
      reasonRequired: p.reasonRequired,
    });
  };

  const buildPayloadDraft = () => {
    const payload = buildEditBagPayloadDraft({ draft, lines, isHd });
    // PRE/POST stay evidence-locked unless the manager opts into correction.
    if (!correctPre) {
      payload.pre_weight_lbs = parseFloatOrNull(baselineBag?.pre_weight_lbs ?? bag?.pre_weight_lbs);
    }
    if (!correctPost) {
      payload.post_weight_lbs = parseFloatOrNull(
        baselineBag?.post_weight_value ??
          baselineBag?.post_weight_lbs ??
          bag?.post_weight_value ??
          bag?.post_weight_lbs
      );
    }
    return payload;
  };

  const enterConflict = (data) => {
    const latest = data?.latest || null;
    setConflict({
      message: "This bag was updated while you were reviewing it.",
      currentVersion:
        data?.manager_edit_version ??
        data?.current_version ??
        latest?.manager_edit_version ??
        latest?.updated_at ??
        null,
      latest,
      unsavedDraft: { ...draft },
      unsavedLines: lines,
      fieldDiffs: diffEditBagDraftVsLatest({
        draft,
        lines,
        latest: latest
          ? {
              ...latest,
              post_weight_value: latest.post_weight_lbs,
              bulk_workitems: (latest.bulk_items || []).map((x) => ({
                workitem_id: x.workitem_id,
                quantity: x.quantity,
                workitem_name: x.name,
              })),
            }
          : null,
      }),
    });
    setShowCompare(false);
  };

  const reloadLatest = async () => {
    setSaving(true);
    setLocalError("");
    try {
      const latestBag = onReloadLatest ? await onReloadLatest(bag.bag_id) : null;
      const next = latestBag || bag;
      if (next?.manager_edit_version != null) {
        setLockVersion(Number(next.manager_edit_version));
      }
      const lock = next?.updated_at || next?.day_bag_updated_at || null;
      setLockUpdatedAt(lock || null);
      setBaselineBag(next);
      setDraft((d) => ({
        ...d,
        pre_weight_lbs: weightFieldValue(next?.pre_weight_lbs),
        post_weight_lbs: weightFieldValue(next?.post_weight_value ?? next?.post_weight_lbs),
        completion_at: toPickerValue(next?.completion_at || next?.canonical_completion_timestamp),
        completed_by: next?.completed_by || next?.canonical_completion_employee || "",
      }));
      setConflict(null);
      setShowCompare(false);
    } catch (e) {
      setLocalError(e?.response?.data?.error || e?.message || "Reload failed");
    } finally {
      setSaving(false);
    }
  };

  const persist = async (outcomeAction) => {
    if (isHd) {
      const requireComplete = outcomeAction === "mark_completed";
      const hdErr = validateHdReviewDraft(draft, { requireComplete });
      if (hdErr) {
        setLocalError(hdErr);
        setPendingOutcome(outcomeAction);
        return;
      }
      setSaving(true);
      setLocalError("");
      try {
        const res = await postVeewashStep1Correction({
          action: requireComplete ? "mark_hd_completed" : "save_hd_review",
          bag_id: bag.bag_id,
          selected_date_et: selectedDateEt,
          version: draft.hd_version ?? 0,
          item_count: draft.item_count === "" ? null : Number(draft.item_count),
          total_revenue: draft.total_revenue === "" ? null : Number(draft.total_revenue),
          washed_by_user_id: draft.washed_by_user_id || null,
          folded_by_user_id: draft.folded_by_user_id || null,
          reason: String(draft.reason_note || draft.reason || "step1_hd_review").trim(),
        });
        if (!res?.data?.ok) {
          const msg =
            (res?.data?.errors || []).join(", ") || res?.data?.error || "HD review save failed";
          setLocalError(msg);
          onError?.(msg);
          return;
        }
        const review = res.data.review || {};
        setDraft((d) => ({
          ...d,
          hd_version: review.version ?? d.hd_version,
          washed_by_user_id: review.washed_by_user_id ?? d.washed_by_user_id,
          folded_by_user_id: review.folded_by_user_id ?? d.folded_by_user_id,
          washed_by_name_snapshot: review.washed_by_name_snapshot || d.washed_by_name_snapshot,
          folded_by_name_snapshot: review.folded_by_name_snapshot || d.folded_by_name_snapshot,
          item_count: review.item_count != null ? String(review.item_count) : d.item_count,
          total_revenue: review.total_revenue != null ? String(review.total_revenue) : d.total_revenue,
        }));
        setUndoToast({
          hdUndo: true,
          message: requireComplete
            ? "HD order marked completed. Undo restores prior review."
            : "HD review saved. Undo restores prior values.",
        });
        onSaved?.(res.data);
      } catch (e) {
        const msg = e?.response?.data?.error || e?.message || "HD review save failed";
        setLocalError(msg);
        onError?.(msg);
      } finally {
        setSaving(false);
      }
      return;
    }

    const err = validateLocal(outcomeAction);
    if (err) {
      setLocalError(err);
      setPendingOutcome(outcomeAction);
      const p = classifyEditReasonRequirements({
        draft,
        baselineBag,
        outcome: outcomeAction,
        lines,
      });
      if (p.reasonRequired && !draft.reason_code && p.suggestedReasonCode) {
        setDraft((d) => ({ ...d, reason_code: p.suggestedReasonCode }));
      }
      return;
    }
    const p = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome: outcomeAction,
      lines,
    });
    setSaving(true);
    setLocalError("");
    try {
      const reasonCode =
        String(draft.reason_code || p.suggestedReasonCode || "").trim().toUpperCase() || null;
      const reasonNote = String(draft.reason_note || draft.reason || "").trim() || null;
      const body = {
        action: "edit_bag",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: p.reasonRequired ? reasonNote || "" : "",
        reason_code: p.reasonRequired ? reasonCode : null,
        reason_note: p.reasonRequired ? reasonNote : null,
        expected_updated_at: lockUpdatedAt || bag.updated_at || bag.day_bag_updated_at || null,
        expected_manager_edit_version:
          lockVersion != null
            ? Number(lockVersion)
            : bag.manager_edit_version != null
              ? Number(bag.manager_edit_version)
              : null,
        outcome_action:
          outcomeAction && outcomeAction !== "decide_later" && outcomeAction !== "keep_review"
            ? outcomeAction
            : null,
        draft: buildPayloadDraft(),
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        if (res?.data?.error === "conflict") {
          enterConflict(res.data);
          return;
        }
        setLocalError(res?.data?.message || res?.data?.error || "Save failed");
        onError?.(res?.data?.message || res?.data?.error || "Save failed");
        return;
      }
      const editId = res.data.edit_id;
      setConflict(null);
      setUndoToast({ editId, message: "Review saved — Undo" });
      // Clear Saving immediately; post-save list refresh must not keep the button stuck.
      setSaving(false);
      setPendingOutcome(null);
      try {
        await onSaved?.(res.data, { keepExpanded: true, closeEditor: true });
      } catch (_) {
        /* save succeeded; refresh errors are non-blocking */
      }
    } catch (e) {
      const status = e?.response?.status;
      const data = e?.response?.data || {};
      if (status === 409 || data.error === "conflict") {
        enterConflict(data);
      } else {
        const msg = data.message || data.error || e?.message || "Save failed";
        setLocalError(msg);
        onError?.(msg);
      }
    } finally {
      setSaving(false);
      setPendingOutcome(null);
    }
  };

  const requestFinalAction = (outcomeAction) => {
    setLocalError("");
    setPendingOutcome(outcomeAction);
    if (isHd) {
      persist(outcomeAction);
      return;
    }
    const availability = reviewActionAvailability({
      actionId: outcomeAction,
      saving,
      lockReady,
      dirty,
      draft,
      baselineBag: baselineBag || bag,
      lines,
      isHd,
    });
    if (!availability.enabled) {
      setLocalError(availability.reason || "This action is not available");
      return;
    }
    const p = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome: outcomeAction,
      lines,
    });
    if (p.reasonRequired) {
      // First click: surface context-specific reasons. Second click / Confirm saves.
      if (!String(draft.reason_code || "").trim()) {
        if (p.suggestedReasonCode) {
          setDraft((d) => ({ ...d, reason_code: p.suggestedReasonCode }));
        }
        setLocalError(availability.reasonHint || "Select a reason to continue");
        return;
      }
      const err = validateEditBagDraft({
        reason: draft.reason,
        reasonCode: draft.reason_code,
        reasonNote: draft.reason_note || draft.reason,
        noChargeable: draft.no_chargeable,
        noChargeReason: draft.no_charge_reason,
        lines,
        isHd,
        reasonRequired: true,
      });
      if (err) {
        setLocalError(err);
        return;
      }
    }
    persist(outcomeAction);
  };

  const handleUndo = async () => {
    if (!undoToast?.editId && !undoToast?.hdUndo) return;
    setSaving(true);
    try {
      const res = await postVeewashStep1Correction(
        undoToast?.hdUndo
          ? {
              action: "undo_hd_review",
              bag_id: bag.bag_id,
              selected_date_et: selectedDateEt,
              reason: "step1_hd_review_undo",
            }
          : {
              action: "undo_bag_edit",
              bag_id: bag.bag_id,
              selected_date_et: selectedDateEt,
              edit_id: undoToast.editId,
            }
      );
      if (!res?.data?.ok) {
        const msg = res?.data?.error || "Undo failed";
        setLocalError(msg);
        onError?.(msg);
        return;
      }
      setUndoToast(null);
      onUndo?.(res.data);
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || "Undo failed";
      setLocalError(msg);
      onError?.(msg);
    } finally {
      setSaving(false);
    }
  };

  if (readOnly) {
    return (
      <Alert severity="info" sx={{ mb: 1 }}>
        Shift is closed — reopen to review this bag.
      </Alert>
    );
  }

  // HD uses a separate mobile-first review experience — never the WF modal.
  if (isHd) {
    return (
      <HdReviewPanel
        bag={bag}
        selectedDateEt={selectedDateEt}
        readOnly={readOnly}
        onCancel={onCancel}
        onSaved={onSaved}
        onError={onError}
        onUndo={onUndo}
      />
    );
  }

  const reasonCodes = policy.reasonCodes || [];
  const reasonNeededForPending = Boolean(
    pendingOutcome !== undefined &&
      classifyEditReasonRequirements({
        draft,
        baselineBag,
        outcome: pendingOutcome,
        lines,
      }).reasonRequired
  );

  const actionStates = Object.fromEntries(
    FINAL_ACTIONS.map((a) => [
      String(a.id),
      reviewActionAvailability({
        actionId: a.id,
        saving,
        lockReady,
        dirty,
        draft,
        baselineBag: baselineBag || bag,
        lines,
        isHd,
      }),
    ])
  );

  const headerBlock = (
    <>
      <Typography variant="h6" fontWeight={800} component="div">
        Review WF Bag
      </Typography>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={{ xs: 0.35, sm: 1 }}
        alignItems={{ xs: "flex-start", sm: "center" }}
        flexWrap="wrap"
        sx={{ mt: 0.25 }}
      >
        <ManagementCopyableId value={bag?.bag_id} fontSize={13} fontWeight={800} />
        <Typography variant="body2" color="text.secondary">
          · {customer} · {draft.service_type || "WF"} / {rushLabel} · {reviewStatus}
        </Typography>
        {dirty ? (
          <Typography
            variant="caption"
            data-testid="review-unsaved-indicator"
            sx={{
              fontWeight: 700,
              color: "#b45309",
              bgcolor: "#fffbeb",
              px: 0.75,
              py: 0.15,
              borderRadius: 1,
            }}
          >
            Unsaved changes
          </Typography>
        ) : null}
      </Stack>
    </>
  );

  return (
    <>
      <Dialog
        open
        fullWidth
        maxWidth="md"
        onClose={() => !saving && onCancel?.()}
        data-testid="review-wf-bag-modal"
        PaperProps={{
          sx: {
            m: { xs: 0, sm: 2 },
            maxHeight: { xs: "100%", sm: "92vh" },
            height: { xs: "100%", sm: "auto" },
            borderRadius: { xs: 0, sm: 2 },
          },
        }}
      >
        <DialogTitle sx={{ pb: 1 }}>{headerBlock}</DialogTitle>
        <DialogContent dividers sx={{ px: { xs: 1.5, sm: 3 } }}>
          {localError && !conflict ? (
            <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setLocalError("")}>
              {localError}
            </Alert>
          ) : null}

          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
                Evidence
              </Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <Box sx={{ flex: 1, p: 1, bgcolor: "grey.50", borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Evidence PRE
                    {correctPre ? " (editing)" : ""}
                  </Typography>
                  <Typography fontWeight={700}>
                    {correctPre && draft.pre_weight_lbs !== ""
                      ? `${draft.pre_weight_lbs} lb (corrected)`
                      : draft.pre_weight_lbs !== "" && draft.pre_weight_lbs != null
                        ? `${draft.pre_weight_lbs} lb`
                        : "—"}
                  </Typography>
                  {(preProvenance.lines || []).map((line) => (
                    <Typography key={line} variant="caption" display="block" color="text.secondary">
                      {line}
                    </Typography>
                  ))}
                </Box>
                <Box sx={{ flex: 1, p: 1, bgcolor: "grey.50", borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Evidence POST
                  </Typography>
                  <Typography fontWeight={700}>
                    {(bag?.post_weight_value ?? bag?.post_weight_lbs) != null
                      ? `${bag?.post_weight_value ?? bag?.post_weight_lbs} lb`
                      : "—"}
                  </Typography>
                  {(postProvenance.lines || []).map((line) => (
                    <Typography key={line} variant="caption" display="block" color="text.secondary">
                      {line}
                    </Typography>
                  ))}
                </Box>
                <Box sx={{ flex: 1, p: 1, bgcolor: "grey.50", borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Authoritative POST
                  </Typography>
                  <Typography fontWeight={700}>
                    {correctPost && draft.post_weight_lbs !== ""
                      ? `${draft.post_weight_lbs} lb (corrected)`
                      : (bag?.post_weight_value ?? bag?.post_weight_lbs) != null
                        ? `${bag?.post_weight_value ?? bag?.post_weight_lbs} lb`
                        : "—"}
                  </Typography>
                </Box>
              </Stack>
              <Accordion disableGutters elevation={0} sx={{ mt: 0.5, bgcolor: "transparent" }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 36 }}>
                  <Typography variant="caption">Evidence details</Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ px: 0, pt: 0 }}>
                  <Typography variant="caption" display="block" title={preProvenance.title || undefined}>
                    PRE: {(preProvenance.lines || [preProvenance.helperText || "—"]).join(" · ")}
                  </Typography>
                  <Typography variant="caption" display="block" title={postProvenance.title || undefined}>
                    POST: {(postProvenance.lines || [postProvenance.helperText || "—"]).join(" · ")}
                  </Typography>
                </AccordionDetails>
              </Accordion>
              <FormControlLabel
                sx={{ mt: 0.5 }}
                control={
                  <Checkbox
                    checked={correctPre}
                    onChange={(e) => {
                      setCorrectPre(e.target.checked);
                      if (!e.target.checked) {
                        setDraft((d) => ({
                          ...d,
                          pre_weight_lbs: weightFieldValue(baselineBag?.pre_weight_lbs),
                        }));
                      }
                    }}
                  />
                }
                label={preWeightMissing ? "Add PRE weight" : "Correct PRE weight"}
              />
              {correctPre ? (
                <TextField
                  size="small"
                  type="number"
                  label={preWeightMissing ? "PRE lbs" : "Corrected PRE lbs"}
                  value={draft.pre_weight_lbs}
                  onChange={(e) => setDraft((d) => ({ ...d, pre_weight_lbs: e.target.value }))}
                  inputProps={{ step: 0.1, min: 0 }}
                  fullWidth
                  sx={{ mt: 0.5 }}
                  helperText="Employee credit uses Evidence PRE."
                />
              ) : null}
              <FormControlLabel
                sx={{ mt: 0.5 }}
                control={
                  <Checkbox
                    checked={correctPost}
                    onChange={(e) => {
                      setCorrectPost(e.target.checked);
                      if (!e.target.checked) {
                        setDraft((d) => ({
                          ...d,
                          post_weight_lbs: weightFieldValue(
                            baselineBag?.post_weight_value ?? baselineBag?.post_weight_lbs
                          ),
                        }));
                      }
                    }}
                  />
                }
                label="Correct POST weight"
              />
              {correctPost ? (
                <TextField
                  size="small"
                  type="number"
                  label="Corrected POST lbs"
                  value={draft.post_weight_lbs}
                  onChange={(e) => setDraft((d) => ({ ...d, post_weight_lbs: e.target.value }))}
                  inputProps={{ step: 0.1, min: 0 }}
                  fullWidth
                  sx={{ mt: 0.5 }}
                />
              ) : null}
            </Box>

            {isHd ? (
              <HdReviewFields
                draft={draft}
                employeeOptions={hdEmployees}
                disabled={saving}
                onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
              />
            ) : null}

            {!isHd ? (
              <Box>
                <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
                  Work items
                </Typography>
                {!draft.no_chargeable
                  ? lines.map((line) => (
                      <Stack
                        key={line.workitem_id}
                        direction="row"
                        spacing={1}
                        alignItems="center"
                        sx={{ mb: 0.75 }}
                      >
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography fontWeight={700} noWrap>
                            {line.name}
                          </Typography>
                          <Typography variant="caption">${money(line.unit_price)}</Typography>
                        </Box>
                        <Button size="small" variant="outlined" onClick={() => bump(line.workitem_id, -1)}>
                          −
                        </Button>
                        <Typography fontFamily="monospace" sx={{ minWidth: 24, textAlign: "center" }}>
                          {line.quantity}
                        </Typography>
                        <Button size="small" variant="outlined" onClick={() => bump(line.workitem_id, 1)}>
                          +
                        </Button>
                        <Typography variant="caption" sx={{ minWidth: 56, textAlign: "right" }}>
                          ${money(line.line_total)}
                        </Typography>
                      </Stack>
                    ))
                  : null}
                {!draft.no_chargeable ? (
                  <Typography fontWeight={800} sx={{ mb: 0.5 }}>
                    Bulk total ${money(bulkTotal)}
                  </Typography>
                ) : null}
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={draft.no_chargeable}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, no_chargeable: e.target.checked }))
                      }
                    />
                  }
                  label="No chargeable bulk items"
                />
                {draft.no_chargeable ? (
                  <FormControl size="small" fullWidth sx={{ mt: 0.5 }}>
                    <InputLabel>No-charge reason</InputLabel>
                    <Select
                      label="No-charge reason"
                      value={
                        NO_CHARGE_REASONS.includes(draft.no_charge_reason)
                          ? draft.no_charge_reason
                          : draft.no_charge_reason
                            ? "Other"
                            : ""
                      }
                      onChange={(e) => {
                        const v = e.target.value;
                        setDraft((d) => ({
                          ...d,
                          no_charge_reason: v === "Other" ? "Other" : v,
                        }));
                      }}
                    >
                      {NO_CHARGE_REASONS.map((r) => (
                        <MenuItem key={r} value={r}>
                          {r}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                ) : null}
                {draft.no_chargeable &&
                (draft.no_charge_reason === "Other" ||
                  (draft.no_charge_reason &&
                    !NO_CHARGE_REASONS.includes(draft.no_charge_reason))) ? (
                  <TextField
                    size="small"
                    fullWidth
                    sx={{ mt: 1 }}
                    label="Other reason"
                    value={
                      NO_CHARGE_REASONS.includes(draft.no_charge_reason)
                        ? ""
                        : draft.no_charge_reason
                    }
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, no_charge_reason: e.target.value }))
                    }
                  />
                ) : null}
              </Box>
            ) : (
              <Typography variant="caption" color="text.secondary">
                WF bulk workitems are hidden for Hang Dry.
              </Typography>
            )}

            {!isHd ? (
              <Box>
                <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
                  Completion details
                </Typography>
                {canonicalOk ? (
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
                    Canonical completion evidence is present. Confirming completion does not require a
                    reason unless you change employee or time.
                  </Typography>
                ) : null}
                <FoldingUserSelect
                  label="Completion employee"
                  value={draft.completed_by || ""}
                  onChange={(name) => setDraft((d) => ({ ...d, completed_by: name }))}
                  allowEmpty
                  sx={{ width: "100%", minWidth: 0, mb: 1 }}
                />
                <PayrollDateTimeField
                  label="Completion date & time (ET)"
                  value={draft.completion_at || ""}
                  onChange={(v) => setDraft((d) => ({ ...d, completion_at: v }))}
                />
              </Box>
            ) : null}

            {!isHd && (reasonNeededForPending || policy.reasonRequired) ? (
              <Box
                data-testid="review-reason-fields"
                sx={{ p: 1.25, border: "1px solid", borderColor: "divider", borderRadius: 1 }}
              >
                <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
                  Reason required
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  {(policy.triggers || []).join(", ") || "manager override"}
                </Typography>
                <TextField
                  select
                  size="small"
                  required
                  fullWidth
                  label="Reason"
                  value={draft.reason_code || policy.suggestedReasonCode || ""}
                  onChange={(e) => setDraft((d) => ({ ...d, reason_code: e.target.value }))}
                  sx={{ mb: 1 }}
                >
                  {(reasonCodes.length ? reasonCodes : policy.reasonCodes || []).map((r) => (
                    <MenuItem key={r.code} value={r.code}>
                      {r.label}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  fullWidth
                  label={
                    String(draft.reason_code || policy.suggestedReasonCode) === "OTHER"
                      ? "Note (required for Other)"
                      : "Note (optional)"
                  }
                  value={draft.reason_note || draft.reason}
                  onChange={(e) => {
                    const next = e.target.value;
                    setDraft((d) => ({ ...d, reason_note: next, reason: next }));
                  }}
                  multiline
                  minRows={2}
                />
                <Button
                  sx={{ mt: 1 }}
                  variant="contained"
                  color={pendingOutcome === "exclude" ? "error" : "primary"}
                  disabled={saving || !lockReady}
                  onClick={() => persist(pendingOutcome)}
                  data-testid="review-confirm-reasoned-save"
                >
                  Confirm{" "}
                  {FINAL_ACTIONS.find((a) => a.id === pendingOutcome)?.label || "Save Review"}
                </Button>
              </Box>
            ) : (
              <Typography variant="caption" color="text.secondary">
                Ordinary work-item review and confirming existing completion do not require a reason.
              </Typography>
            )}
            {scansSection}
          </Stack>
        </DialogContent>
        <DialogActions
          sx={{
            px: 2,
            py: 1.5,
            flexWrap: "wrap",
            gap: 1,
            justifyContent: "flex-start",
            position: "sticky",
            bottom: 0,
            bgcolor: "background.paper",
          }}
        >
          {(isHd ? HD_FINAL_ACTIONS : FINAL_ACTIONS).map((a) => {
            const state =
              actionStates[String(a.id)] || {
                enabled: !saving && (isHd || lockReady),
                reason: null,
              };
            const disabled = saving || (!isHd && !state.enabled);
            return (
              <Box key={String(a.id)} sx={{ display: "inline-flex", flexDirection: "column" }}>
                <Button
                  variant={a.variant}
                  color={a.color}
                  disabled={disabled}
                  onClick={() => requestFinalAction(a.id)}
                  data-testid={`review-action-${a.id || "save_review"}`}
                  title={!state.enabled && state.reason ? state.reason : undefined}
                >
                  {saving && pendingOutcome === a.id ? "Saving…" : a.label}
                </Button>
                {!state.enabled && state.reason && !saving ? (
                  <Typography
                    variant="caption"
                    sx={{ color: "#94a3b8", maxWidth: 150, lineHeight: 1.2, mt: 0.25 }}
                    data-testid={`review-action-hint-${a.id || "save_review"}`}
                  >
                    {state.reason}
                  </Typography>
                ) : null}
              </Box>
            );
          })}
          <Button onClick={onCancel} disabled={saving} sx={{ ml: { sm: "auto" } }}>
            Cancel
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(conflict)}
        onClose={() => !saving && setConflict(null)}
        fullWidth
        maxWidth="xs"
        data-testid="review-conflict-dialog"
      >
        <DialogTitle>Bag updated</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {conflict?.message || "This bag was updated while you were reviewing it."}
          </Typography>
          {showCompare && (conflict?.fieldDiffs || []).length > 0 ? (
            <Stack spacing={0.5} sx={{ mt: 1 }}>
              {(conflict.fieldDiffs || []).map((d) => (
                <Typography key={d.label} variant="caption" display="block">
                  {d.label}: unsaved {d.unsaved} · latest {d.latest}
                </Typography>
              ))}
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 0.5 }}>
          <Button onClick={() => setShowCompare(true)} disabled={saving}>
            Compare Changes
          </Button>
          <Button onClick={reloadLatest} disabled={saving} variant="contained">
            Reload Latest
          </Button>
          <Button onClick={() => setConflict(null)} disabled={saving}>
            Cancel
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={Boolean(undoToast)}
        autoHideDuration={12000}
        onClose={() => setUndoToast(null)}
        message={undoToast?.message || "Changes saved"}
        action={
          <Button color="secondary" size="small" onClick={handleUndo} disabled={saving}>
            Undo
          </Button>
        }
      />
    </>
  );
}

function parseFloatOrNull(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
