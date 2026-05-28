import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getFoldingUserSequence } from "../../api";
import { foldingRangeParams } from "../../utils/foldingDateRange";
import {
  formatFoldingDuration,
  formatFoldingWallDateTime,
  formatLbs,
} from "../../utils/foldingFormat";
import { foldingExceptionLabel } from "../../utils/foldingExceptionLabels";

const timeCellSx = { whiteSpace: "nowrap", fontSize: 12, py: 1 };
const statusCellSx = { whiteSpace: "normal", maxWidth: 120, verticalAlign: "top" };

function SummaryCard({ label, value, sub }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

function formatFoldDuration(r, minMinutes) {
  const mins = r.duration_minutes;
  const text = mins != null ? `${mins}m` : formatFoldingDuration(r.duration_seconds);
  if (r.below_min_duration) {
    return (
      <Stack spacing={0.25}>
        <Typography variant="body2" fontWeight={700} color="error.main">{text}</Typography>
        <Typography variant="caption" color="error.main">
          Below {minMinutes} min min.
        </Typography>
      </Stack>
    );
  }
  return text;
}

export default function FoldingUserSequencePanel({
  userName,
  appliedDateStart,
  appliedDateEnd,
  appliedListDateField,
  searchTick,
  onOpenTimeline,
  onOpenOrder,
}) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const uname = String(userName || "").trim();
    if (!uname || !searchTick) {
      setData(null);
      return;
    }
    try {
      setLoading(true);
      setError("");
      const res = await getFoldingUserSequence({
        ...foldingRangeParams({
          dateStart: appliedDateStart,
          dateEnd: appliedDateEnd,
          dateField: appliedListDateField,
        }),
        user_name: uname,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load user sequence");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [userName, appliedDateStart, appliedDateEnd, appliedListDateField, searchTick]);

  useEffect(() => {
    load();
  }, [load]);

  if (!userName) return null;

  const s = data?.summary || {};
  const rules = data?.rules || {};
  const minMinutes = rules.min_duration_minutes ?? 10;
  const allRows = data?.rows || [];
  const filtered = allRows.filter((r) => {
    if (filter === "scoring") return r.included_in_scoring && !r.below_min_duration;
    if (filter === "exceptions") return !r.included_in_scoring || r.below_min_duration;
    return true;
  });
  const belowMinInScoring = allRows.filter((r) => r.below_min_duration && r.included_in_scoring);

  return (
    <Box mt={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1} flexWrap="wrap" gap={1}>
        <Typography variant="subtitle2" fontWeight={700}>
          Folding sequence — {userName}
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button size="small" variant="outlined" onClick={load} disabled={loading}>
            Refresh data
          </Button>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Show</InputLabel>
            <Select label="Show" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <MenuItem value="all">All bags</MenuItem>
              <MenuItem value="scoring">Scoring only</MenuItem>
              <MenuItem value="exceptions">Exceptions / not in scoring</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}

      {belowMinInScoring.length > 0 ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {belowMinInScoring.length} bag(s) under the {minMinutes}-minute minimum are still marked in scoring.
          Run Apply recompute in exception rules to fix stored status.
        </Alert>
      ) : null}

      {data ? (
        <>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            Sorted by folding start → end (ET). Gap = idle time between bags (not fold duration).
            Min fold duration rule: {minMinutes} minutes.
          </Typography>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid item xs={6} md={3}>
              <SummaryCard
                label="All activity"
                value={`${s.total_bags ?? 0} bags`}
                sub={`${formatLbs(s.total_lbs)} · ${s.total_folding_minutes ?? 0}m folding · ${s.total_gap_minutes ?? 0}m between bags`}
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <SummaryCard
                label="Used for scoring"
                value={`${s.scoring_bags ?? 0} bags`}
                sub={
                  s.scoring_bags_per_hour != null
                    ? `${s.scoring_bags_per_hour} bags/hr · ${s.scoring_lbs_per_hour} lbs/hr`
                    : "—"
                }
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <SummaryCard
                label="Exceptions / not in scoring"
                value={`${s.not_in_scoring_bags ?? 0}`}
                sub={`Too short (<${minMinutes}m): ${s.below_min_duration_count ?? s.too_short_count ?? 0}`}
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <SummaryCard
                label="Multiple folding scans"
                value={`${s.multiple_folding_scans_count ?? 0}`}
                sub={`Warnings (in scoring): ${s.multiple_folding_scans_warnings ?? 0} · Blocked: ${s.multiple_folding_scans_exceptions ?? 0}`}
              />
            </Grid>
          </Grid>

          <Table size="small" sx={{ tableLayout: "auto" }}>
            <TableHead>
              <TableRow>
                <TableCell sx={timeCellSx}>#</TableCell>
                <TableCell sx={timeCellSx}>Start ET</TableCell>
                <TableCell sx={timeCellSx}>End ET</TableCell>
                <TableCell>Fold duration</TableCell>
                <TableCell>Gap since prev</TableCell>
                <TableCell>Bag</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell align="right">Weight</TableCell>
                <TableCell sx={statusCellSx}>Status</TableCell>
                <TableCell>Scoring</TableCell>
                <TableCell>Duration rule</TableCell>
                <TableCell>Multiple folding scans</TableCell>
                <TableCell>Other exception</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={14} align="center" sx={{ py: 2, color: "text.secondary" }}>
                    {loading ? "Loading…" : "No rows for this filter."}
                  </TableCell>
                </TableRow>
              ) : filtered.map((r) => (
                <TableRow
                  key={r.bag_id}
                  sx={{
                    bgcolor: r.below_min_duration
                      ? "rgba(211, 47, 47, 0.1)"
                      : r.included_in_scoring
                        ? undefined
                        : "rgba(255, 152, 0, 0.08)",
                  }}
                >
                  <TableCell sx={timeCellSx}>{r.sequence}</TableCell>
                  <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_start_at)}</TableCell>
                  <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_end_at)}</TableCell>
                  <TableCell>{formatFoldDuration(r, minMinutes)}</TableCell>
                  <TableCell sx={{ fontSize: 12 }}>
                    {r.gap_minutes_from_previous == null
                      ? "First"
                      : r.gap_overlap
                        ? "Overlap"
                        : `${r.gap_minutes_from_previous}m idle`}
                  </TableCell>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                  <TableCell>{r.customer || "—"}</TableCell>
                  <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : "—"}</TableCell>
                  <TableCell sx={statusCellSx}>
                    <Chip
                      size="small"
                      label={r.status}
                      color={
                        r.below_min_duration
                          ? "error"
                          : r.included_in_scoring
                            ? "success"
                            : "warning"
                      }
                      sx={{ height: "auto", "& .MuiChip-label": { whiteSpace: "normal", py: 0.25 } }}
                    />
                  </TableCell>
                  <TableCell>{r.included_in_scoring ? "Yes" : "No"}</TableCell>
                  <TableCell>
                    {r.duration_exception_code || r.below_min_duration
                      ? foldingExceptionLabel(r.duration_exception_code || "FOLDING_DURATION_TOO_SHORT")
                      : "—"}
                  </TableCell>
                  <TableCell>
                    {r.multiple_folding_scans
                      ? (r.multiple_folding_scans_label || "Yes")
                      : "—"}
                  </TableCell>
                  <TableCell>
                    {r.other_exception_code
                      ? foldingExceptionLabel(r.other_exception_code)
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} flexWrap="wrap">
                      {onOpenTimeline ? (
                        <Button size="small" onClick={() => onOpenTimeline(r.bag_id)}>Timeline</Button>
                      ) : null}
                      {onOpenOrder ? (
                        <Button size="small" onClick={() => onOpenOrder(r.bag_id)}>Order</Button>
                      ) : null}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      ) : loading ? (
        <Typography variant="body2" color="text.secondary">Loading sequence…</Typography>
      ) : null}
    </Box>
  );
}
