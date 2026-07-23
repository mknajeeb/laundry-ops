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
  describeWeightProvenance,
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
  }));
  const [qty, setQty] = useState(initialQty);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const [saveAttempted, setSaveAttempted] = useState(false);
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const [pendingSave, setPendingSave] = useState(null);
  const [undoToast, setUndoToast] = useState(null);

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
    observedAt: bag?.pre_weight_observed_at || bag?.pre_weight_at,
    attachBatchId: bag?.pre_weight_attach_batch_id,
    attachReason: bag?.pre_weight_attach_reason,
    needsManagerCorrection: preWeightNeedsManagerCorrection,
  });
  const postProvenance = describeWeightProvenance({
    role: "post",
    weightLbs: bag?.post_weight_value ?? bag?.post_weight_lbs,
    source: bag?.post_weight_source,
    observedAt: bag?.post_weight_observed_at || bag?.post_weight_at,
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

  const validateLocal = () =>
    validateEditBagDraft({
      reason: draft.reason,
      noChargeable: draft.no_chargeable,
      noChargeReason: draft.no_charge_reason,
      lines,
      isHd,
    });

  const buildPayloadDraft = () =>
    buildEditBagPayloadDraft({ draft, lines, isHd });

  const persist = async (outcomeAction) => {
    setSaveAttempted(true);
    const err = validateLocal();
    if (err) {
      setLocalError(err);
      return;
    }
    setSaving(true);
    setLocalError("");
    try {
      const body = {
        action: "edit_bag",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: draft.reason.trim(),
        expected_updated_at: bag.updated_at || bag.day_bag_updated_at || null,
        outcome_action:
          outcomeAction && outcomeAction !== "decide_later" ? outcomeAction : null,
        draft: buildPayloadDraft(),
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        const msg =
          res?.data?.error === "conflict"
            ? "This bag changed since you opened the editor. Reload and try again."
            : res?.data?.error || res?.data?.message || "Save failed";
        setLocalError(msg);
        onError?.(msg);
        return;
      }
      const editId = res.data.edit_id;
      setOutcomeOpen(false);
      setPendingSave(null);
      setUndoToast({
        editId,
        message: "Changes saved — Undo",
      });
      onSaved?.(res.data, { keepExpanded: true });
    } catch (e) {
      const status = e?.response?.status;
      const data = e?.response?.data || {};
      const msg =
        status === 409 || data.error === "conflict"
          ? "This bag changed since you opened the editor. Reload and try again."
          : data.error || e?.message || "Save failed";
      setLocalError(msg);
      onError?.(msg);
    } finally {
      setSaving(false);
    }
  };

  const startSave = () => {
    setSaveAttempted(true);
    const err = validateLocal();
    if (err) {
      setLocalError(err);
      return;
    }
    setLocalError("");
    setPendingSave(buildPayloadDraft());
    setOutcomeOpen(true);
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
      {localError ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setLocalError("")}>
          {localError}
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

        <TextField
          size="small"
          required
          label="Notes / correction reason"
          value={draft.reason}
          onChange={(e) => {
            const next = e.target.value;
            setDraft((d) => ({ ...d, reason: next }));
            if (saveAttempted && String(next || "").trim()) {
              setLocalError("");
            }
          }}
          error={saveAttempted && !String(draft.reason || "").trim()}
          helperText={
            saveAttempted && !String(draft.reason || "").trim()
              ? "Correction reason is required"
              : "Required before saving"
          }
          multiline
          minRows={2}
        />

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button
            variant="contained"
            disabled={saving || !String(draft.reason || "").trim()}
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
          <Stack spacing={1}>
            {OUTCOME_OPTIONS.map((opt) => (
              <Button
                key={opt.id}
                variant={opt.id === "mark_completed" ? "contained" : "outlined"}
                color={opt.id === "exclude" ? "error" : "primary"}
                disabled={saving}
                onClick={() => persist(opt.id)}
              >
                {opt.label}
              </Button>
            ))}
          </Stack>
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
