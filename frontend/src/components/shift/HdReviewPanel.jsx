import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { postVeewashStep1Correction, getDailyOperationsHdProductionDetail } from "../../api";

function asDateInput(v, fallback = "") {
  if (!v) return fallback || "";
  return String(v).trim().slice(0, 10);
}

function withHistorical(opts, roleUserId, snapshot) {
  const list = Array.isArray(opts) ? [...opts] : [];
  if (!roleUserId) return list;
  const id = Number(roleUserId);
  if (list.some((o) => Number(o.user_id || o.id) === id)) return list;
  list.push({
    user_id: roleUserId,
    display_name: `${snapshot || `Employee #${roleUserId}`} (historical)`,
    historical: true,
  });
  return list;
}

export function validateHdReviewDraft(draft, { requireComplete = false } = {}) {
  if (draft.item_count !== "" && draft.item_count != null) {
    const items = Number(draft.item_count);
    if (!Number.isInteger(items) || items < 0) {
      return "Number of Items must be a whole number ≥ 0";
    }
  }
  if (draft.total_revenue !== "" && draft.total_revenue != null) {
    const rev = Number(draft.total_revenue);
    if (!Number.isFinite(rev) || rev < 0) {
      return "Total Amount / Revenue must be ≥ 0";
    }
  }
  for (const key of ["washed_date_et", "folded_date_et"]) {
    const raw = draft[key];
    if (raw && !/^\d{4}-\d{2}-\d{2}$/.test(String(raw).trim())) {
      return key === "washed_date_et"
        ? "Washed Date must be YYYY-MM-DD"
        : "Folded Date must be YYYY-MM-DD";
    }
  }
  if (!requireComplete) return "";
  if (draft.item_count === "" || draft.item_count == null) return "# of Items is required";
  if (draft.total_revenue === "" || draft.total_revenue == null) {
    return "Total Amount / Revenue is required";
  }
  if (!draft.washed_by_user_id) return "Washed By is required";
  if (!draft.washed_date_et) return "Washed Date is required";
  if (!draft.folded_by_user_id) return "Folded By is required";
  if (!draft.folded_date_et) return "Folded Date is required";
  return "";
}

/**
 * Mobile-first HD Review — operational data entry only.
 * Completely separate from WF Review (no evidence / weights / bulk items).
 */
export default function HdReviewPanel({
  bag,
  selectedDateEt,
  readOnly = false,
  onCancel,
  onSaved,
  onError,
  onUndo,
}) {
  const defaultDate = asDateInput(selectedDateEt);
  const [draft, setDraft] = useState(() => ({
    item_count: bag?.hd_review?.item_count ?? "",
    total_revenue: bag?.hd_review?.total_revenue ?? "",
    washed_by_user_id: bag?.hd_review?.washed_by_user_id ?? "",
    folded_by_user_id: bag?.hd_review?.folded_by_user_id ?? "",
    washed_by_name_snapshot: bag?.hd_review?.washed_by_name_snapshot || "",
    folded_by_name_snapshot: bag?.hd_review?.folded_by_name_snapshot || "",
    washed_date_et: asDateInput(bag?.hd_review?.washed_date_et, defaultDate),
    folded_date_et: asDateInput(bag?.hd_review?.folded_date_et, defaultDate),
    hd_version: bag?.hd_review?.version ?? 0,
  }));
  const [employees, setEmployees] = useState([]);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const [undoToast, setUndoToast] = useState(null);

  useEffect(() => {
    if (!bag?.bag_id || !selectedDateEt) return undefined;
    let cancelled = false;
    getDailyOperationsHdProductionDetail(selectedDateEt, bag.bag_id)
      .then((res) => {
        if (cancelled) return;
        const detail = res?.data || {};
        const prod = detail.production || {};
        const opts = (detail.employee_options || []).filter((o) => !o.is_external);
        setEmployees(opts);
        setDraft((d) => ({
          ...d,
          item_count: prod.total_items != null ? String(prod.total_items) : d.item_count,
          total_revenue: prod.revenue != null ? String(prod.revenue) : d.total_revenue,
          washed_by_user_id: prod.washed_by_user_id ?? d.washed_by_user_id,
          folded_by_user_id: prod.folded_by_user_id ?? d.folded_by_user_id,
          washed_by_name_snapshot: prod.washed_by_name_snapshot || d.washed_by_name_snapshot,
          folded_by_name_snapshot: prod.folded_by_name_snapshot || d.folded_by_name_snapshot,
          washed_date_et: asDateInput(prod.washed_date_et, d.washed_date_et || defaultDate),
          folded_date_et: asDateInput(prod.folded_date_et, d.folded_date_et || defaultDate),
          hd_version: prod.version ?? d.hd_version ?? 0,
        }));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [bag?.bag_id, selectedDateEt, defaultDate]);

  const customer =
    bag?.customer_name || bag?.customer || bag?.portal_customer_name || bag?.account_name || "—";
  const rushLabel = String(bag?.rush_flag || bag?.rush_status || "")
    .toUpperCase()
    .includes("NON")
    ? "Non-Rush"
    : "Rush";
  const reviewStatus = bag?.dashboard_status || bag?.outcome || bag?.hd_review?.review_status || "—";

  const washedOpts = withHistorical(
    employees,
    draft.washed_by_user_id,
    draft.washed_by_name_snapshot
  );
  const foldedOpts = withHistorical(
    employees,
    draft.folded_by_user_id,
    draft.folded_by_name_snapshot
  );

  const patch = (next) => setDraft((d) => ({ ...d, ...next }));

  const persist = async (requireComplete) => {
    const err = validateHdReviewDraft(draft, { requireComplete });
    if (err) {
      setLocalError(err);
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
        washed_date_et: draft.washed_date_et || null,
        folded_date_et: draft.folded_date_et || null,
        reason: requireComplete ? "step1_hd_mark_completed" : "step1_hd_review_save",
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
        washed_date_et: asDateInput(review.washed_date_et, d.washed_date_et),
        folded_date_et: asDateInput(review.folded_date_et, d.folded_date_et),
        item_count: review.item_count != null ? String(review.item_count) : d.item_count,
        total_revenue: review.total_revenue != null ? String(review.total_revenue) : d.total_revenue,
      }));
      setUndoToast({
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
  };

  const handleUndo = async () => {
    setSaving(true);
    try {
      const res = await postVeewashStep1Correction({
        action: "undo_hd_review",
        bag_id: bag.bag_id,
        selected_date_et: selectedDateEt,
        reason: "step1_hd_review_undo",
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
        Shift is closed — reopen to review this HD order.
      </Alert>
    );
  }

  const fieldSx = {
    "& .MuiInputBase-root": { minHeight: 52, fontSize: "1.05rem" },
    "& .MuiInputLabel-root": { fontSize: "1rem" },
  };

  return (
    <>
      <Dialog
        open
        fullScreen
        onClose={() => !saving && onCancel?.()}
        data-testid="review-hd-bag-modal"
        PaperProps={{
          sx: {
            display: "flex",
            flexDirection: "column",
            bgcolor: "#f7f8fa",
          },
        }}
      >
        <DialogTitle sx={{ pb: 1, bgcolor: "#fff", borderBottom: "1px solid", borderColor: "divider" }}>
          <Typography variant="h6" fontWeight={800} component="div">
            Review HD Order
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {bag?.bag_id} · {customer} · HD / {rushLabel} · {reviewStatus}
          </Typography>
        </DialogTitle>

        <DialogContent
          sx={{
            px: 2,
            py: 2,
            flex: 1,
            overflowY: "auto",
            pb: 12,
          }}
        >
          {localError ? (
            <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setLocalError("")}>
              {localError}
            </Alert>
          ) : null}

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Enter items, revenue, who washed/folded, and the ET business dates. Save Review allows
            partial entry. Save &amp; Mark Completed requires all six fields.
          </Typography>

          <Stack spacing={2}>
            <TextField
              type="number"
              label="# of Items"
              value={draft.item_count ?? ""}
              onChange={(e) => patch({ item_count: e.target.value })}
              inputProps={{ min: 0, step: 1, inputMode: "numeric" }}
              disabled={saving}
              fullWidth
              sx={fieldSx}
            />
            <TextField
              type="number"
              label="Total Amount / Revenue"
              value={draft.total_revenue ?? ""}
              onChange={(e) => patch({ total_revenue: e.target.value })}
              inputProps={{ min: 0, step: 0.01, inputMode: "decimal" }}
              disabled={saving}
              fullWidth
              sx={fieldSx}
            />
            <FormControl fullWidth disabled={saving} sx={fieldSx}>
              <InputLabel id="hd-washed-by">Washed By</InputLabel>
              <Select
                labelId="hd-washed-by"
                label="Washed By"
                value={draft.washed_by_user_id ?? ""}
                onChange={(e) => patch({ washed_by_user_id: e.target.value })}
              >
                <MenuItem value="">
                  <em>Select employee</em>
                </MenuItem>
                {washedOpts.map((o) => (
                  <MenuItem key={`w-${o.user_id || o.id}`} value={o.user_id || o.id}>
                    {o.display_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              type="date"
              label="Washed Date"
              value={draft.washed_date_et || ""}
              onChange={(e) => patch({ washed_date_et: e.target.value })}
              InputLabelProps={{ shrink: true }}
              disabled={saving}
              fullWidth
              sx={fieldSx}
              helperText="ET business date (no time)"
            />
            <FormControl fullWidth disabled={saving} sx={fieldSx}>
              <InputLabel id="hd-folded-by">Folded By</InputLabel>
              <Select
                labelId="hd-folded-by"
                label="Folded By"
                value={draft.folded_by_user_id ?? ""}
                onChange={(e) => patch({ folded_by_user_id: e.target.value })}
              >
                <MenuItem value="">
                  <em>Select employee</em>
                </MenuItem>
                {foldedOpts.map((o) => (
                  <MenuItem key={`f-${o.user_id || o.id}`} value={o.user_id || o.id}>
                    {o.display_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              type="date"
              label="Folded Date"
              value={draft.folded_date_et || ""}
              onChange={(e) => patch({ folded_date_et: e.target.value })}
              InputLabelProps={{ shrink: true }}
              disabled={saving}
              fullWidth
              sx={fieldSx}
              helperText="ET business date (no time)"
            />
          </Stack>
        </DialogContent>

        <DialogActions
          sx={{
            position: "sticky",
            bottom: 0,
            px: 2,
            py: 1.5,
            gap: 1,
            flexDirection: "column",
            alignItems: "stretch",
            bgcolor: "#fff",
            borderTop: "1px solid",
            borderColor: "divider",
            boxShadow: "0 -4px 16px rgba(0,0,0,0.06)",
          }}
        >
          <Button
            variant="contained"
            color="primary"
            size="large"
            disabled={saving}
            onClick={() => persist(false)}
            sx={{ minHeight: 48, fontWeight: 800 }}
          >
            {saving ? "Saving…" : "Save Review"}
          </Button>
          <Button
            variant="contained"
            color="success"
            size="large"
            disabled={saving}
            onClick={() => persist(true)}
            sx={{ minHeight: 48, fontWeight: 800 }}
          >
            Save &amp; Mark Completed
          </Button>
          <Button
            color="inherit"
            size="large"
            disabled={saving}
            onClick={() => onCancel?.()}
            sx={{ minHeight: 44 }}
          >
            Cancel
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={Boolean(undoToast)}
        autoHideDuration={8000}
        onClose={() => setUndoToast(null)}
        message={undoToast?.message || ""}
        action={
          <Button color="secondary" size="small" disabled={saving} onClick={handleUndo}>
            Undo
          </Button>
        }
      />
    </>
  );
}
