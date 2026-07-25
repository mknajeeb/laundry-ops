import { FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";

/** Manager HD review fields — org employees only (no free-text). */
export default function HdReviewFields({
  draft,
  onChange,
  employeeOptions = [],
  disabled = false,
}) {
  const opts = Array.isArray(employeeOptions) ? employeeOptions : [];

  const withHistorical = (roleUserId, snapshot, prefix) => {
    const list = [...opts];
    if (!roleUserId) return list;
    const id = Number(roleUserId);
    if (list.some((o) => Number(o.user_id || o.id) === id)) return list;
    // Historical inactive/removed employee: visible for existing record only.
    list.push({
      user_id: roleUserId,
      display_name: `${snapshot || `Employee #${roleUserId}`} (historical)`,
      historical: true,
    });
    return list;
  };

  const washedOpts = withHistorical(
    draft.washed_by_user_id,
    draft.washed_by_name_snapshot,
    "w"
  );
  const foldedOpts = withHistorical(
    draft.folded_by_user_id,
    draft.folded_by_name_snapshot,
    "f"
  );

  return (
    <Stack spacing={1.25} sx={{ mb: 1.5 }}>
      <Typography variant="subtitle2" fontWeight={800}>
        HD production review
      </Typography>
      <Typography variant="caption" color="text.secondary">
        Enter Number of Items, Total Amount / Revenue, Washed By, and Folded By, then Save &amp;
        Mark Completed. Zero is allowed when intentionally entered; blank means not entered.
      </Typography>
      <TextField
        size="small"
        type="number"
        label="Number of Items"
        value={draft.item_count ?? ""}
        onChange={(e) => onChange({ item_count: e.target.value })}
        inputProps={{ min: 0, step: 1 }}
        disabled={disabled}
        fullWidth
      />
      <TextField
        size="small"
        type="number"
        label="Total Amount / Revenue"
        value={draft.total_revenue ?? ""}
        onChange={(e) => onChange({ total_revenue: e.target.value })}
        inputProps={{ min: 0, step: 0.01 }}
        disabled={disabled}
        fullWidth
      />
      <FormControl size="small" fullWidth disabled={disabled}>
        <InputLabel id="hd-washed-by">Washed By</InputLabel>
        <Select
          labelId="hd-washed-by"
          label="Washed By"
          value={draft.washed_by_user_id ?? ""}
          onChange={(e) => onChange({ washed_by_user_id: e.target.value })}
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
      <FormControl size="small" fullWidth disabled={disabled}>
        <InputLabel id="hd-folded-by">Folded By</InputLabel>
        <Select
          labelId="hd-folded-by"
          label="Folded By"
          value={draft.folded_by_user_id ?? ""}
          onChange={(e) => onChange({ folded_by_user_id: e.target.value })}
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
      {(draft.washed_by_name_snapshot || draft.folded_by_name_snapshot) && (
        <Typography variant="caption" color="text.secondary">
          Snapshots: Washed {draft.washed_by_name_snapshot || "—"} · Folded{" "}
          {draft.folded_by_name_snapshot || "—"}
        </Typography>
      )}
    </Stack>
  );
}

export function validateHdReviewDraft(draft, { requireComplete = false } = {}) {
  // Always reject malformed values when present (even on Save Review).
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
  if (!requireComplete) return "";
  if (draft.item_count === "" || draft.item_count == null) return "Number of Items is required";
  if (draft.total_revenue === "" || draft.total_revenue == null) {
    return "Total Amount / Revenue is required";
  }
  if (!draft.washed_by_user_id) return "Washed By is required";
  if (!draft.folded_by_user_id) return "Folded By is required";
  return "";
}
