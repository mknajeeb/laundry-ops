import { useEffect, useMemo, useState } from "react";
import {
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
import { postVeewashStep1Correction } from "../../api";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { PayrollDateTimeField } from "../PayrollDateTimeField";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  buildEditBagPayloadDraft,
  classifyEditReasonRequirements,
  describeWeightProvenance,
  diffEditBagDraftVsLatest,
  EDIT_BAG_REASON_CODES,
  validateEditBagDraft,
} from "./editBagHelpers";

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

const OUTCOME_OPTIONS = [
  { id: "mark_completed", label: "Mark Completed" },
  { id: "return_pending", label: "Return to Pending" },
  { id: "keep_review", label: "Keep in Review Required" },
  { id: "exclude", label: "Exclude" },
  { id: "decide_later", label: "Decide Later" },
];

/**
 * Unified Edit Bag draft panel — local draft only until Save & Choose Action.
 */
export default function EditBagPanel({
  bag,
  selectedDateEt,
  catalog = [],
  readOnly = false,
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
    post_weight_lbs: weightFieldValue(
      bag?.post_weight_value ?? bag?.post_weight_lbs
    ),
    no_chargeable: String(bag?.bulk_resolution?.resolution_type || "") === "no_charge",
    no_charge_reason: bag?.bulk_resolution?.no_charge_reason || "",
    completion_at: toPickerValue(bag?.completion_at),
    completed_by: bag?.completed_by || "",
    reason: "",
    reason_code: "",
    reason_note: "",
  }));
  const [qty, setQty] = useState(initialQty);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const [saveAttempted, setSaveAttempted] = useState(false);
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const [pendingSave, setPendingSave] = useState(null);
  const [pendingOutcome, setPendingOutcome] = useState(null);
  const [undoToast, setUndoToast] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [lockUpdatedAt, setLockUpdatedAt] = useState(
    () => bag?.updated_at || bag?.day_bag_updated_at || null
  );
  const [baselineBag, setBaselineBag] = useState(bag);

  // Keep draft stable while editing — do not reset from bag prop refreshes.
  useEffect(() => {
    setQty(initialQty);
  }, [bag?.bag_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isHd = String(draft.service_type || "").toUpperCase() === "HD";

  // Heuristic hint only — post weight present (from portal) while pre weight is
  // still missing means the earlier weight-entry scan has no recoverable
  // portal evidence and needs a manager correction (see
  // backend/rinse_scan_weight_enrichment.py classify_and_backfill_bag).
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
    attachBatchId: bag?.pre_weight_attach_batch_id,
    attachReason: bag?.pre_weight_attach_reason,
    needsManagerCorrection: preWeightNeedsManagerCorrection,
  });
  const postProvenance = describeWeightProvenance({
    role: "post",
    weightLbs: bag?.post_weight_value ?? bag?.post_weight_lbs,
    source: bag?.post_weight_source,
    observedAt: bag?.post_weight_observed_at,
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

  const bump = (id, delta) => {
    setQty((q) => ({ ...q, [id]: Math.max(0, Number(q[id] || 0) + delta) }));
  };

  const validateLocal = (outcome = null) => {
    const policy = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome,
      lines,
    });
    return validateEditBagDraft({
      reason: draft.reason,
      reasonCode: draft.reason_code || policy.suggestedReasonCode,
      reasonNote: draft.reason_note || draft.reason,
      noChargeable: draft.no_chargeable,
      noChargeReason: draft.no_charge_reason,
      lines,
      isHd,
      reasonRequired: policy.reasonRequired,
    });
  };

  const buildPayloadDraft = () =>
    buildEditBagPayloadDraft({ draft, lines, isHd });

  const enterConflict = (data) => {
    const latest = data?.latest || null;
    setConflict({
      message: "This bag was updated after you opened it.",
      currentVersion: data?.current_version || latest?.updated_at || null,
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
    setLocalError("This bag was updated after you opened it.");
  };

  const reloadLatest = async () => {
    setSaving(true);
    setLocalError("");
    try {
      const latestBag = onReloadLatest
        ? await onReloadLatest(bag.bag_id)
        : null;
      const next = latestBag || bag;
      const lock = next?.updated_at || next?.day_bag_updated_at || conflict?.currentVersion;
      setLockUpdatedAt(lock || null);
      setBaselineBag(next);
      const diffs = diffEditBagDraftVsLatest({
        draft: conflict?.unsavedDraft || draft,
        lines: conflict?.unsavedLines || lines,
        latest: next,
      });
      setConflict((c) =>
        c
          ? {
              ...c,
              latest: next,
              fieldDiffs: diffs,
              reloaded: true,
              message:
                "Latest saved values loaded. Your unsaved edits were not applied automatically.",
            }
          : null
      );
    } catch (e) {
      setLocalError(e?.response?.data?.error || e?.message || "Reload failed");
    } finally {
      setSaving(false);
    }
  };

  const dismissConflict = () => {
    setConflict(null);
    setLocalError("");
  };

  const persist = async (outcomeAction) => {
    setSaveAttempted(true);
    const err = validateLocal(outcomeAction);
    if (err) {
      setLocalError(err);
      return;
    }
    const policy = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome: outcomeAction,
      lines,
    });
    if (policy.reasonRequired && !draft.reason_code && policy.suggestedReasonCode) {
      setDraft((d) => ({ ...d, reason_code: policy.suggestedReasonCode }));
    }
    setSaving(true);
    setLocalError("");
    try {
      const reasonCode =
        String(draft.reason_code || policy.suggestedReasonCode || "").trim().toUpperCase() ||
        null;
      const reasonNote = String(draft.reason_note || draft.reason || "").trim() || null;
      const body = {
        action: "edit_bag",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: reasonNote || "",
        reason_code: policy.reasonRequired ? reasonCode : reasonCode,
        reason_note: reasonNote,
        expected_updated_at: lockUpdatedAt || bag.updated_at || bag.day_bag_updated_at || null,
        outcome_action:
          outcomeAction && outcomeAction !== "decide_later" ? outcomeAction : null,
        draft: buildPayloadDraft(),
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        if (res?.data?.error === "conflict") {
          enterConflict(res.data);
          return;
        }
        setLocalError(res?.data?.error || res?.data?.message || "Save failed");
        onError?.(res?.data?.error || "Save failed");
        return;
      }
      const editId = res.data.edit_id;
      setOutcomeOpen(false);
      setPendingSave(null);
      setPendingOutcome(null);
      setConflict(null);
      setUndoToast({
        editId,
        message: "Changes saved — Undo",
      });
      onSaved?.(res.data, { keepExpanded: true });
    } catch (e) {
      const status = e?.response?.status;
      const data = e?.response?.data || {};
      if (status === 409 || data.error === "conflict") {
        enterConflict(data);
      } else {
        const msg = data.error || e?.message || "Save failed";
        setLocalError(msg);
        onError?.(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const startSave = () => {
    setSaveAttempted(true);
    const err = validateLocal(null);
    if (err) {
      setLocalError(err);
      return;
    }
    setLocalError("");
    setPendingSave(buildPayloadDraft());
    setPendingOutcome(null);
    setOutcomeOpen(true);
  };

  const chooseOutcome = (optId) => {
    const policy = classifyEditReasonRequirements({
      draft,
      baselineBag,
      outcome: optId,
      lines,
    });
    if (policy.reasonRequired) {
      setPendingOutcome(optId);
      if (policy.suggestedReasonCode && !draft.reason_code) {
        setDraft((d) => ({ ...d, reason_code: policy.suggestedReasonCode }));
      }
      setLocalError("");
      return;
    }
    persist(optId);
  };

  const handleUndo = async () => {
    if (!undoToast?.editId) return;
    setSaving(true);
    try {
      const res = await postVeewashStep1Correction({
        action: "undo_bag_edit",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        edit_id: undoToast.editId,
        reason: "Undo last Edit Bag change",
      });
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
        Shift is closed — reopen to edit this bag.
      </Alert>
    );
  }

  return (
    <Box
      data-testid="edit-bag-panel"
      sx={{
        mb: 1.5,
        p: 1.25,
        bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
        borderRadius: 1,
        border: "1px solid",
        borderColor: "divider",
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
        Edit Bag
      </Typography>
      {localError && !conflict ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setLocalError("")}>
          {localError}
        </Alert>
      ) : null}
      {conflict ? (
        <Alert
          severity="warning"
          sx={{ mb: 1 }}
          action={
            <Stack direction="row" spacing={0.5}>
              <Button color="inherit" size="small" onClick={reloadLatest} disabled={saving}>
                Reload Latest
              </Button>
              <Button color="inherit" size="small" onClick={dismissConflict}>
                Cancel
              </Button>
            </Stack>
          }
        >
          <Typography variant="body2" fontWeight={700}>
            {conflict.message}
          </Typography>
          {conflict.currentVersion ? (
            <Typography variant="caption" display="block">
              Current version: {String(conflict.currentVersion)}
            </Typography>
          ) : null}
          {(conflict.fieldDiffs || []).length > 0 ? (
            <Box sx={{ mt: 1 }}>
              <Typography variant="caption" fontWeight={700} display="block">
                Your unsaved values vs latest saved
              </Typography>
              {(conflict.fieldDiffs || []).slice(0, 8).map((d) => (
                <Typography key={d.label} variant="caption" display="block">
                  {d.label}: unsaved {d.unsaved} · latest {d.latest}
                </Typography>
              ))}
            </Box>
          ) : (
            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
              Reload Latest to refresh the editor lock without closing the queue.
            </Typography>
          )}
        </Alert>
      ) : null}

      <Stack spacing={1.25}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <FormControl size="small" fullWidth>
            <InputLabel>Service</InputLabel>
            <Select
              label="Service"
              value={draft.service_type}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  service_type: e.target.value,
                  rack: e.target.value === "HD" ? d.rack : d.rack || "VeeWash Dirty",
                }))
              }
            >
              <MenuItem value="WF">WF</MenuItem>
              <MenuItem value="HD">HD</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel>Rush</InputLabel>
            <Select
              label="Rush"
              value={String(draft.rush_flag || "").toUpperCase().includes("NON") ? "NON-RUSH" : "RUSH"}
              onChange={(e) => setDraft((d) => ({ ...d, rush_flag: e.target.value }))}
            >
              <MenuItem value="RUSH">Rush</MenuItem>
              <MenuItem value="NON-RUSH">Non-Rush</MenuItem>
            </Select>
          </FormControl>
        </Stack>

        <PayrollDateTimeField
          label="Workload entry (ET)"
          value={draft.entry_at || ""}
          onChange={(v) => setDraft((d) => ({ ...d, entry_at: v }))}
        />
        {!isHd ? (
          <TextField
            size="small"
            label="Entry rack"
            value={draft.rack || ""}
            onChange={(e) => setDraft((d) => ({ ...d, rack: e.target.value }))}
          />
        ) : null}

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            type="number"
            label="Pre Weight lbs"
            value={draft.pre_weight_lbs}
            onChange={(e) => setDraft((d) => ({ ...d, pre_weight_lbs: e.target.value }))}
            inputProps={{ step: 0.1, min: 0 }}
            helperText={preProvenance.helperText}
            FormHelperTextProps={{ title: preProvenance.title || undefined }}
            fullWidth
          />
          <TextField
            size="small"
            type="number"
            label="Post Weight lbs"
            value={draft.post_weight_lbs}
            onChange={(e) => setDraft((d) => ({ ...d, post_weight_lbs: e.target.value }))}
            inputProps={{ step: 0.1, min: 0 }}
            helperText={postProvenance.helperText}
            FormHelperTextProps={{ title: postProvenance.title || undefined }}
            fullWidth
          />
        </Stack>

        {!isHd ? (
          <Box sx={{ p: 1, border: "1px solid #e2e8f0", borderRadius: 1, bgcolor: "#fff" }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.75 }}>
              WF Bulk Workitems
            </Typography>
            {!draft.no_chargeable
              ? lines.map((line) => (
                  <Box key={line.workitem_id} sx={{ mb: 1 }}>
                    <Typography fontWeight={700}>{line.name}</Typography>
                    <Typography variant="caption" display="block">
                      Price: ${money(line.unit_price)}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ my: 0.5 }}>
                      <Button size="small" variant="outlined" onClick={() => bump(line.workitem_id, -1)}>
                        −
                      </Button>
                      <Typography fontFamily="monospace" sx={{ minWidth: 24, textAlign: "center" }}>
                        {line.quantity}
                      </Typography>
                      <Button size="small" variant="outlined" onClick={() => bump(line.workitem_id, 1)}>
                        +
                      </Button>
                    </Stack>
                    <Typography variant="caption">Line Total: ${money(line.line_total)}</Typography>
                  </Box>
                ))
              : null}
            {!draft.no_chargeable ? (
              <Typography fontWeight={800}>Bulk Item Total ${money(bulkTotal)}</Typography>
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
              label="No Chargeable Bulk Items"
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
              (draft.no_charge_reason && !NO_CHARGE_REASONS.includes(draft.no_charge_reason))) ? (
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

        <FoldingUserSelect
          label="Completion employee (optional)"
          value={draft.completed_by || ""}
          onChange={(name) => setDraft((d) => ({ ...d, completed_by: name }))}
          allowEmpty
          sx={{ width: "100%", minWidth: 0 }}
        />
        <PayrollDateTimeField
          label="Completion date & time (ET, optional)"
          value={draft.completion_at || ""}
          onChange={(v) => setDraft((d) => ({ ...d, completion_at: v }))}
        />

        {(() => {
          const basePolicy = classifyEditReasonRequirements({
            draft,
            baselineBag,
            outcome: pendingOutcome,
            lines,
          });
          if (!basePolicy.reasonRequired) {
            return (
              <Typography variant="caption" color="text.secondary">
                Routine work-item and review saves do not require a reason. A system audit
                code ({basePolicy.systemAction}) is recorded automatically.
              </Typography>
            );
          }
          return (
            <Stack spacing={1}>
              <Alert severity="info">
                This action needs a structured reason ({(basePolicy.triggers || []).join(", ")}).
              </Alert>
              <TextField
                select
                size="small"
                required
                label="Reason code"
                value={draft.reason_code || basePolicy.suggestedReasonCode || ""}
                onChange={(e) => setDraft((d) => ({ ...d, reason_code: e.target.value }))}
              >
                {EDIT_BAG_REASON_CODES.map((r) => (
                  <MenuItem key={r.code} value={r.code}>
                    {r.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                size="small"
                label={
                  String(draft.reason_code || basePolicy.suggestedReasonCode) === "OTHER"
                    ? "Reason note (required for Other)"
                    : "Reason note (optional)"
                }
                value={draft.reason_note || draft.reason}
                onChange={(e) => {
                  const next = e.target.value;
                  setDraft((d) => ({ ...d, reason_note: next, reason: next }));
                }}
                multiline
                minRows={2}
              />
            </Stack>
          );
        })()}

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button
            variant="contained"
            disabled={saving}
            onClick={startSave}
          >
            {saving ? "Saving…" : "Save & Choose Action"}
          </Button>
          <Button onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </Stack>
      </Stack>

      <Dialog open={outcomeOpen} onClose={() => !saving && setOutcomeOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Changes ready. What should happen to this bag?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Your draft{pendingSave ? " (including bulk items and weights)" : ""} will save
            together with the action you choose.
          </Typography>
          {pendingOutcome ? (
            <Stack spacing={1} sx={{ mb: 1.5 }}>
              <Alert severity="warning">
                {OUTCOME_OPTIONS.find((o) => o.id === pendingOutcome)?.label || pendingOutcome}{" "}
                requires a reason code before save.
              </Alert>
              <TextField
                select
                size="small"
                label="Reason code"
                value={draft.reason_code || ""}
                onChange={(e) => setDraft((d) => ({ ...d, reason_code: e.target.value }))}
              >
                {EDIT_BAG_REASON_CODES.map((r) => (
                  <MenuItem key={r.code} value={r.code}>
                    {r.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                size="small"
                label={
                  draft.reason_code === "OTHER"
                    ? "Reason note (required for Other)"
                    : "Reason note (optional)"
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
                variant="contained"
                color={pendingOutcome === "exclude" ? "error" : "primary"}
                disabled={saving}
                onClick={() => persist(pendingOutcome)}
              >
                Confirm {OUTCOME_OPTIONS.find((o) => o.id === pendingOutcome)?.label}
              </Button>
              <Button onClick={() => setPendingOutcome(null)} disabled={saving}>
                Back to actions
              </Button>
            </Stack>
          ) : (
            <Stack spacing={1}>
              {OUTCOME_OPTIONS.map((opt) => (
                <Button
                  key={opt.id}
                  variant={opt.id === "mark_completed" ? "contained" : "outlined"}
                  color={opt.id === "exclude" ? "error" : "primary"}
                  disabled={saving}
                  onClick={() => chooseOutcome(opt.id)}
                >
                  {opt.label}
                </Button>
              ))}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOutcomeOpen(false)} disabled={saving}>
            Back to editor
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
    </Box>
  );
}
