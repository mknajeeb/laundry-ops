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
  formatDateTime,
  formatFoldingDuration,
  formatLbs,
} from "../../utils/foldingFormat";

function SummaryCard({ label, value, sub }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
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
  const allRows = data?.rows || [];
  const filtered = allRows.filter((r) => {
    if (filter === "scoring") return r.included_in_scoring;
    if (filter === "exceptions") return !r.included_in_scoring;
    return true;
  });

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

      {data ? (
        <>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            Sorted by folding start → end (ET). Gap = time between previous bag end and this bag start.
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
                sub={`Too short: ${s.too_short_count ?? 0} · Multi-fold warn: ${s.multiple_folding_scans_count ?? 0}`}
              />
            </Grid>
            <Grid item xs={6} md={3}>
              <SummaryCard
                label="Avg gap"
                value={s.avg_gap_minutes != null ? `${s.avg_gap_minutes}m` : "—"}
                sub={`Total gap time: ${s.total_gap_minutes ?? 0}m`}
              />
            </Grid>
          </Grid>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>#</TableCell>
                <TableCell>Start (ET)</TableCell>
                <TableCell>End (ET)</TableCell>
                <TableCell>Duration</TableCell>
                <TableCell>Gap</TableCell>
                <TableCell>Bag</TableCell>
                <TableCell>Customer</TableCell>
                <TableCell align="right">Weight</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Scoring</TableCell>
                <TableCell>Exception / warning</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={12} align="center" sx={{ py: 2, color: "text.secondary" }}>
                    {loading ? "Loading…" : "No rows for this filter."}
                  </TableCell>
                </TableRow>
              ) : filtered.map((r) => (
                <TableRow
                  key={r.bag_id}
                  sx={{
                    bgcolor: r.included_in_scoring ? undefined : "rgba(255, 152, 0, 0.08)",
                  }}
                >
                  <TableCell>{r.sequence}</TableCell>
                  <TableCell>{formatDateTime(r.folding_start_at)}</TableCell>
                  <TableCell>{formatDateTime(r.folding_end_at)}</TableCell>
                  <TableCell>
                    {r.duration_minutes != null ? `${r.duration_minutes}m` : formatFoldingDuration(r.duration_seconds)}
                  </TableCell>
                  <TableCell>
                    {r.gap_minutes_from_previous == null
                      ? "First bag"
                      : r.gap_overlap
                        ? "Overlap"
                        : `${r.gap_minutes_from_previous}m`}
                  </TableCell>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                  <TableCell>{r.customer || "—"}</TableCell>
                  <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : "—"}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={r.status}
                      color={r.included_in_scoring ? "success" : "warning"}
                    />
                  </TableCell>
                  <TableCell>{r.included_in_scoring ? "Yes" : "No"}</TableCell>
                  <TableCell>{r.exception_code || "—"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
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
