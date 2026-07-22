import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  confirmCompletionReview,
  resolveCompletionReview,
  batchConfirmCompletionReviews,
} from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import CopyableBagId from "../CopyableBagId";

function toLocalInputValue(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function draftFromRow(row) {
  return {
    employee: row.assigned_employee || row.suggested_employee || "",
    completion_at: toLocalInputValue(row.assigned_completion_at || row.suggested_completion_at),
    weight_lbs: row.assigned_weight_lbs ?? row.registry_weight_lbs ?? "",
    note: row.review_note || "",
  };
}

/**
 * Completed Between Scrapes — Review Required
 * Visible until reviewed; not part of ordinary Pending / official productivity.
 */
export default function CompletionReviewSection({
  block,
  selectedDateEt,
  onChanged,
}) {
  const review = block || {};
  const rows = review.rows || [];
  const [drafts, setDrafts] = useState(() => {
    const init = {};
    for (const r of rows) init[r.bag_id] = draftFromRow(r);
    return init;
  });
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");

  const counts = useMemo(
    () => ({
      confirmed: review.confirmed_completed_count ?? 0,
      review: review.review_required_count ?? rows.length,
      potential: review.potential_completed_total ?? (review.confirmed_completed_count || 0) + rows.length,
    }),
    [review, rows.length]
  );

  if (!rows.length && !(review.review_required_count > 0)) {
    return null;
  }

  const updateDraft = (bagId, patch) => {
    setDrafts((prev) => ({
      ...prev,
      [bagId]: { ...(prev[bagId] || draftFromRow({})), ...patch },
    }));
  };

  const toggleSelect = (bagId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(bagId)) next.delete(bagId);
      else next.add(bagId);
      return next;
    });
  };

  const run = async (key, fn) => {
    setBusy(key);
    setError("");
    try {
      await fn();
      onChanged?.();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Request failed");
    } finally {
      setBusy(null);
    }
  };

  const confirmOne = (row) =>
    run(`confirm:${row.bag_id}`, async () => {
      const d = drafts[row.bag_id] || draftFromRow(row);
      if (!d.employee || !d.completion_at) {
        throw new Error("Employee and completion time are required");
      }
      await confirmCompletionReview(row.bag_id, {
        employee: d.employee,
        completion_at: d.completion_at,
        selected_date_et: selectedDateEt,
        weight_lbs: d.weight_lbs === "" ? null : Number(d.weight_lbs),
        review_note: d.note || null,
      });
    });

  const resolveOne = (row, resolution) =>
    run(`resolve:${row.bag_id}:${resolution}`, async () => {
      const d = drafts[row.bag_id] || draftFromRow(row);
      await resolveCompletionReview(row.bag_id, {
        resolution,
        review_note: d.note || null,
      });
    });

  const batchConfirm = () =>
    run("batch", async () => {
      const items = [];
      for (const bagId of selected) {
        const row = rows.find((r) => r.bag_id === bagId);
        const d = drafts[bagId] || draftFromRow(row || {});
        if (!d.employee || !d.completion_at) {
          throw new Error(`Employee and completion time required for ${bagId}`);
        }
        items.push({
          bag_id: bagId,
          employee: d.employee,
          completion_at: d.completion_at,
          weight_lbs: d.weight_lbs === "" ? null : Number(d.weight_lbs),
          review_note: d.note || null,
          selected_date_et: selectedDateEt,
        });
      }
      if (!items.length) throw new Error("Select at least one bag");
      await batchConfirmCompletionReviews({
        selected_date_et: selectedDateEt,
        items,
      });
      setSelected(new Set());
    });

  return (
    <Paper
      elevation={0}
      sx={{
        p: { xs: 1.25, sm: 1.75 },
        mb: 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.monitoringBorder,
        bgcolor: VEEWASH_DASHBOARD.monitoringBg,
      }}
    >
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between" sx={{ mb: 1 }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={800}>
            Completed Between Scrapes — Review Required
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            Day&apos;s Load bags that left the portal between scrapes before a finish weight was captured.
            Assign the correct employee, time, and weight from the portal bag history — check this daily so productivity stays accurate.
            Not in Pending or official productivity until confirmed.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" label={`Completed Today: ${counts.confirmed}`} />
          <Chip size="small" color="warning" label={`Completion Review Required: ${counts.review}`} />
          <Chip size="small" variant="outlined" label={`Potential Completed Total: ${counts.potential}`} />
        </Stack>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {selected.size > 0 ? (
        <Box sx={{ mb: 1 }}>
          <Button size="small" variant="contained" disabled={!!busy} onClick={batchConfirm}>
            Confirm selected ({selected.size})
          </Button>
        </Box>
      ) : null}

      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox" />
              <TableCell>Bag</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell>Evidence</TableCell>
              <TableCell>Employee</TableCell>
              <TableCell>Completion time</TableCell>
              <TableCell>Weight</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => {
              const d = drafts[row.bag_id] || draftFromRow(row);
              return (
                <TableRow key={row.bag_id} hover>
                  <TableCell padding="checkbox">
                    <Checkbox
                      size="small"
                      checked={selected.has(row.bag_id)}
                      onChange={() => toggleSelect(row.bag_id)}
                    />
                  </TableCell>
                  <TableCell>
                    <CopyableBagId bagId={row.bag_id} />
                    <Typography variant="caption" color="text.secondary" display="block">
                      {row.workflow || "WF"} · {row.confidence_level || "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{row.customer_name || "—"}</Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      EDD {row.estimated_delivery_date || "—"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" display="block">
                      Last portal: {row.last_portal_seen_at || "—"}
                    </Typography>
                    <Typography variant="caption" display="block">
                      Absent: {row.first_absent_scrape_at || "—"}
                    </Typography>
                    <Typography variant="caption" display="block">
                      CC: {row.complete_cleaning_at || "—"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {row.suggested_completion_source || row.reason_label}
                      {row.suggested_time_inferred ? " (inferred)" : ""}
                    </Typography>
                  </TableCell>
                  <TableCell sx={{ minWidth: 140 }}>
                    <TextField
                      size="small"
                      fullWidth
                      value={d.employee}
                      onChange={(e) => updateDraft(row.bag_id, { employee: e.target.value })}
                      placeholder="Required"
                    />
                  </TableCell>
                  <TableCell sx={{ minWidth: 180 }}>
                    <TextField
                      size="small"
                      fullWidth
                      type="datetime-local"
                      value={d.completion_at}
                      onChange={(e) => updateDraft(row.bag_id, { completion_at: e.target.value })}
                      InputLabelProps={{ shrink: true }}
                    />
                  </TableCell>
                  <TableCell sx={{ minWidth: 90 }}>
                    <TextField
                      size="small"
                      fullWidth
                      value={d.weight_lbs}
                      onChange={(e) => updateDraft(row.bag_id, { weight_lbs: e.target.value })}
                      placeholder="lbs"
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Stack spacing={0.5} alignItems="flex-end">
                      <Button
                        size="small"
                        variant="contained"
                        disabled={!!busy}
                        onClick={() => confirmOne(row)}
                      >
                        Confirm Completed
                      </Button>
                      <Button
                        size="small"
                        disabled={!!busy}
                        onClick={() => resolveOne(row, "KEEP_PENDING")}
                      >
                        Keep Pending
                      </Button>
                      <Button
                        size="small"
                        color="warning"
                        disabled={!!busy}
                        onClick={() => resolveOne(row, "MARKED_REJECTED")}
                      >
                        Mark Rejected/Issue
                      </Button>
                      <Button
                        size="small"
                        color="inherit"
                        disabled={!!busy}
                        onClick={() => resolveOne(row, "NOT_OUR_BAG")}
                      >
                        Not Our Bag
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Box>
    </Paper>
  );
}
