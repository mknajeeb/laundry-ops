import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { convertTryOut } from "../api";
import {
  CONVERT_TRYOUT_TARGETS,
  catalogLabel,
  categoryLabel,
  classifyEmploymentCategory,
  currentAssignment,
  emptyAssignmentRow,
  formatYmdFriendly,
  mapAssignmentRow,
  parseYmd,
  previousAssignments,
  startDateLabel,
  validateTryOutDates,
} from "../payroll/employmentCategory";

function catKind(cats, catId) {
  const c = (cats || []).find((x) => String(x.id) === String(catId || ""));
  return c ? classifyEmploymentCategory(c) : "";
}

export default function EmploymentCategorySection({
  userId,
  cats,
  catRows,
  setCatRows,
  canEdit,
  required,
}) {
  const [convertOpen, setConvertOpen] = useState(false);
  const [targetCatId, setTargetCatId] = useState("");
  const [newStart, setNewStart] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState("");

  const current = currentAssignment(catRows);
  const previous = previousAssignments(catRows, current);
  const currentKind = catKind(cats, current?.employment_category_id);
  const isTryOut = currentKind === "tryout";
  const convertTargets = useMemo(
    () =>
      (cats || []).filter((c) =>
        CONVERT_TRYOUT_TARGETS.includes(classifyEmploymentCategory(c)),
      ),
    [cats],
  );

  const updateCurrent = (patch) => {
    setCatRows((prev) => {
      const next = [...(prev || [])];
      if (!next.length) {
        return [{ ...emptyAssignmentRow(), ...patch }];
      }
      const cur = currentAssignment(next);
      const idx = cur ? next.indexOf(cur) : 0;
      const at = idx >= 0 ? idx : 0;
      next[at] = { ...next[at], ...patch };
      return next;
    });
  };

  const onConvert = async () => {
    setLocalError("");
    if (!targetCatId || !parseYmd(newStart)) {
      setLocalError("Choose a new category and start date.");
      return;
    }
    if (!userId) {
      setLocalError("Save the employee first, then convert Try Out.");
      return;
    }
    setBusy(true);
    try {
      const res = await convertTryOut(userId, {
        employment_category_id: Number(targetCatId),
        start_date: parseYmd(newStart),
      });
      const rows = res.data?.assignments || [];
      setCatRows(rows.length ? rows.map(mapAssignmentRow) : [emptyAssignmentRow()]);
      setConvertOpen(false);
      setTargetCatId("");
      setNewStart("");
    } catch (e) {
      setLocalError(e.response?.data?.error || e.message || "Convert failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        Employment
      </Typography>
      <Stack spacing={1.25}>
        <TextField
          select
          size="small"
          label="Current Category"
          value={current?.employment_category_id || ""}
          onChange={(e) => {
            const v = e.target.value;
            const kind = catKind(cats, v);
            updateCurrent({
              employment_category_id: v,
              worker_category: kind,
              ...(kind === "tryout" ? {} : { effective_to: current?.effective_to || "" }),
            });
          }}
          required={required}
          disabled={!canEdit || isTryOut}
          helperText={
            isTryOut && canEdit
              ? "Use Convert Try Out to change category without losing history."
              : undefined
          }
        >
          <MenuItem value="">—</MenuItem>
          {(cats || []).map((c) => (
            <MenuItem key={c.id} value={String(c.id)}>
              {catalogLabel(c)}
            </MenuItem>
          ))}
        </TextField>

        {currentKind ? (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <TextField
              size="small"
              type="date"
              label={startDateLabel(currentKind)}
              InputLabelProps={{ shrink: true }}
              value={current?.effective_from || ""}
              onChange={(e) => updateCurrent({ effective_from: e.target.value })}
              required={required}
              disabled={!canEdit}
              fullWidth
            />
            {isTryOut ? (
              <TextField
                size="small"
                type="date"
                label="Try Out End Date"
                InputLabelProps={{ shrink: true }}
                value={current?.effective_to || ""}
                onChange={(e) => updateCurrent({ effective_to: e.target.value })}
                required={required}
                disabled={!canEdit}
                error={Boolean(
                  current?.effective_from &&
                    current?.effective_to &&
                    validateTryOutDates(current.effective_from, current.effective_to),
                )}
                helperText={validateTryOutDates(current.effective_from, current.effective_to) || " "}
                fullWidth
              />
            ) : null}
          </Stack>
        ) : null}

        {isTryOut && canEdit ? (
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              setLocalError("");
              setConvertOpen(true);
            }}
            sx={{ alignSelf: "flex-start" }}
          >
            Convert Try Out
          </Button>
        ) : null}

        {previous.filter((r) => r.employment_category_id).length ? (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              Previous
            </Typography>
            {previous
              .filter((r) => r.employment_category_id)
              .map((row, i) => {
                const kind = catKind(cats, row.employment_category_id);
                const start = formatYmdFriendly(row.effective_from);
                const end = row.effective_to ? formatYmdFriendly(row.effective_to) : "present";
                return (
                  <Typography key={row.id || `${row.employment_category_id}-${i}`} variant="body2">
                    {categoryLabel(kind, catalogLabel(cats.find((c) => String(c.id) === String(row.employment_category_id))))}{" "}
                    · {start}
                    {row.effective_to || start !== "—" ? ` – ${end}` : ""}
                  </Typography>
                );
              })}
          </Box>
        ) : null}
      </Stack>

      <Dialog open={convertOpen} onClose={() => !busy && setConvertOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Convert Try Out</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Keeps this employee and Try Out history. Payroll from the Try Out period stays Try Out.
          </Typography>
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <TextField
              select
              size="small"
              label="New category"
              value={targetCatId}
              onChange={(e) => setTargetCatId(e.target.value)}
              required
            >
              <MenuItem value="">—</MenuItem>
              {convertTargets.map((c) => (
                <MenuItem key={c.id} value={String(c.id)}>
                  {catalogLabel(c)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              type="date"
              label={`${startDateLabel(catKind(cats, targetCatId) || "w2")}`}
              InputLabelProps={{ shrink: true }}
              value={newStart}
              onChange={(e) => setNewStart(e.target.value)}
              required
            />
            {localError ? (
              <Typography variant="body2" color="error">
                {localError}
              </Typography>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConvertOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={onConvert} variant="contained" disabled={busy}>
            Convert
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
