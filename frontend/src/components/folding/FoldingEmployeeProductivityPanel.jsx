import { useCallback, useEffect, useMemo, useState } from "react";
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
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getFoldingUserProductivity } from "../../api";
import { foldingRangeParams } from "../../utils/foldingDateRange";
import {
  formatFoldingDuration,
  formatFoldingWallDateTime,
  formatLbs,
} from "../../utils/foldingFormat";
import { foldingExceptionLabel } from "../../utils/foldingExceptionLabels";

const timeCellSx = { whiteSpace: "nowrap", fontSize: 12, py: 1 };
const statusCellSx = { whiteSpace: "normal", maxWidth: 140, verticalAlign: "top" };

function SummaryCard({ label, value, sub }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

function RateLine({ label, value, suffix = "" }) {
  if (value == null) return null;
  return (
    <Typography variant="caption" display="block" color="text.secondary">
      {label}: {value}{suffix}
    </Typography>
  );
}

function BagSequenceTable({ rows, filter, loading, onOpenTimeline, onOpenOrder }) {
  const filtered = rows.filter((r) => {
    if (filter === "scoring") return r.included_in_scoring;
    if (filter === "exceptions") return !r.included_in_scoring;
    return true;
  });

  return (
    <Table size="small" sx={{ tableLayout: "auto", mt: 2 }}>
      <TableHead>
        <TableRow>
          <TableCell sx={timeCellSx}>#</TableCell>
          <TableCell>Bag</TableCell>
          <TableCell>Customer</TableCell>
          <TableCell sx={timeCellSx}>Folding start</TableCell>
          <TableCell sx={timeCellSx}>Folding end</TableCell>
          <TableCell>Duration</TableCell>
          <TableCell>Gap from prev</TableCell>
          <TableCell align="right">Weight</TableCell>
          <TableCell sx={statusCellSx}>Status</TableCell>
          <TableCell>Exception / warning</TableCell>
          <TableCell>In scoring</TableCell>
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
            <TableCell sx={timeCellSx}>{r.sequence}</TableCell>
            <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
            <TableCell>{r.customer || "—"}</TableCell>
            <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_start_at)}</TableCell>
            <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_end_at)}</TableCell>
            <TableCell>
              {r.duration_minutes != null
                ? `${r.duration_minutes}m`
                : formatFoldingDuration(r.duration_seconds)}
            </TableCell>
            <TableCell sx={{ fontSize: 12 }}>
              {r.gap_minutes_from_previous == null
                ? "First"
                : r.gap_overlap
                  ? "Overlap"
                  : `${r.gap_minutes_from_previous}m`}
            </TableCell>
            <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : "—"}</TableCell>
            <TableCell sx={statusCellSx}>
              <Chip
                size="small"
                label={r.status || "—"}
                color={r.included_in_scoring ? "success" : "warning"}
              />
            </TableCell>
            <TableCell>
              {r.exception_code ? foldingExceptionLabel(r.exception_code) : "—"}
            </TableCell>
            <TableCell>{r.included_in_scoring ? "Yes" : "No"}</TableCell>
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
  );
}

function ModeASummary({ s, labels }) {
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={6} md={3}>
        <SummaryCard label="Total bags folded" value={s.total_bags ?? 0} sub={`${s.exception_bags ?? 0} exceptions`} />
      </Grid>
      <Grid item xs={6} md={3}>
        <SummaryCard label="Scoring bags" value={s.scoring_bags ?? 0} sub={`${formatLbs(s.scoring_lbs)} scoring lbs`} />
      </Grid>
      <Grid item xs={6} md={3}>
        <SummaryCard
          label="Total lbs / folding time"
          value={formatLbs(s.total_lbs)}
          sub={`${s.total_folding_minutes ?? 0}m folding · avg ${s.avg_minutes_per_bag ?? "—"}m/bag`}
        />
      </Grid>
      <Grid item xs={6} md={3}>
        <SummaryCard
          label="Gap / time killed"
          value={`${s.total_gap_minutes ?? 0}m`}
          sub={`Avg gap ${s.avg_gap_minutes ?? "—"}m`}
        />
      </Grid>
      <Grid item xs={12}>
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <RateLine label={labels.bags_per_folding_hour} value={s.bags_per_folding_hour} />
          <RateLine label={labels.lbs_per_folding_hour} value={s.lbs_per_folding_hour} suffix=" lbs" />
        </Paper>
      </Grid>
    </Grid>
  );
}

function ModeBSummary({ s, labels, spanNote }) {
  return (
    <>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        {spanNote}
      </Typography>
      <Grid container spacing={1.5}>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Work window"
            value={`${s.work_window_minutes ?? 0}m`}
            sub={`${formatFoldingWallDateTime(s.work_window_start)} → ${formatFoldingWallDateTime(s.work_window_end)}`}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Folding minutes" value={`${s.folding_minutes ?? 0}m`} sub={`Gap ${s.gap_minutes ?? 0}m`} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Idle / non-folding"
            value={`${s.idle_minutes ?? 0}m`}
            sub={`${s.total_bags ?? 0} total · ${s.scoring_bags ?? 0} scoring`}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Exceptions" value={s.exception_bags ?? 0} sub={formatLbs(s.total_lbs)} />
        </Grid>
        <Grid item xs={12}>
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <RateLine label={labels.bags_per_work_span_hour} value={s.bags_per_work_span_hour} />
            <RateLine label={labels.lbs_per_work_span_hour} value={s.lbs_per_work_span_hour} suffix=" lbs" />
            <RateLine label={labels.bags_per_folding_hour} value={s.bags_per_folding_hour} />
            <RateLine label={labels.lbs_per_folding_hour} value={s.lbs_per_folding_hour} suffix=" lbs" />
          </Paper>
        </Grid>
      </Grid>
    </>
  );
}

function ModeCSummary({ s, labels, shifts }) {
  return (
    <>
      <Grid container spacing={1.5}>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Clocked minutes" value={`${s.clocked_minutes ?? 0}m`} sub={`${shifts?.length ?? 0} shift(s)`} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Folding in shift"
            value={`${s.folding_minutes_in_shift ?? 0}m`}
            sub={`Non-folding ${s.non_folding_minutes_in_shift ?? 0}m`}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Bags in shift"
            value={s.total_bags ?? 0}
            sub={`${s.scoring_bags ?? 0} scoring · gap ${s.gap_minutes_in_shift ?? 0}m`}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Lbs in shift" value={formatLbs(s.total_lbs)} sub={formatLbs(s.scoring_lbs)} />
        </Grid>
        <Grid item xs={12}>
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <RateLine label={labels.bags_per_clocked_hour} value={s.bags_per_clocked_hour} />
            <RateLine label={labels.lbs_per_clocked_hour} value={s.lbs_per_clocked_hour} suffix=" lbs" />
            <RateLine label={labels.bags_per_folding_hour} value={s.bags_per_folding_hour} />
            <RateLine label={labels.lbs_per_folding_hour} value={s.lbs_per_folding_hour} suffix=" lbs" />
          </Paper>
        </Grid>
      </Grid>
      {shifts?.length ? (
        <Table size="small" sx={{ mt: 2 }}>
          <TableHead>
            <TableRow>
              <TableCell>Clock in</TableCell>
              <TableCell>Clock out</TableCell>
              <TableCell>Clocked</TableCell>
              <TableCell>Bags</TableCell>
              <TableCell>Scoring</TableCell>
              <TableCell>Note</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {shifts.map((sh) => (
              <TableRow key={sh.shift_id}>
                <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(sh.clock_in_at)}</TableCell>
                <TableCell sx={timeCellSx}>
                  {sh.clock_out_at
                    ? formatFoldingWallDateTime(sh.clock_out_at)
                    : formatFoldingWallDateTime(sh.effective_clock_out_at)}
                </TableCell>
                <TableCell>{sh.clocked_minutes}m</TableCell>
                <TableCell>{sh.bags_in_shift}</TableCell>
                <TableCell>{sh.scoring_bags_in_shift}</TableCell>
                <TableCell>
                  {sh.is_active_estimate ? (
                    <Typography variant="caption" color="warning.main">
                      {sh.estimate_label || "Active shift estimate"}
                    </Typography>
                  ) : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </>
  );
}

export default function FoldingEmployeeProductivityPanel({
  userName,
  appliedDateStart,
  appliedDateEnd,
  appliedListDateField,
  searchTick,
  onOpenTimeline,
  onOpenOrder,
}) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState(0);
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
      const res = await getFoldingUserProductivity({
        ...foldingRangeParams({
          dateStart: appliedDateStart,
          dateEnd: appliedDateEnd,
          dateField: appliedListDateField,
        }),
        user_name: uname,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load employee productivity");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [userName, appliedDateStart, appliedDateEnd, appliedListDateField, searchTick]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => {
    if (!data) return [];
    if (tab === 2 && data.mode_c_clock_hours?.available) {
      return data.mode_c_clock_hours.rows || [];
    }
    return data.mode_a_bag_wise?.rows || [];
  }, [data, tab]);

  if (!userName) return null;

  const modeA = data?.mode_a_bag_wise?.summary || {};
  const modeB = data?.mode_b_work_span?.summary || {};
  const modeC = data?.mode_c_clock_hours || {};
  const shortBags = data?.diagnostics?.short_duration_bags || [];

  return (
    <Box mt={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1} flexWrap="wrap" gap={1}>
        <Typography variant="subtitle2" fontWeight={700}>
          Employee productivity / sequence — {userName}
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button size="small" variant="outlined" onClick={load} disabled={loading}>
            Refresh data
          </Button>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Show bags</InputLabel>
            <Select label="Show bags" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <MenuItem value="all">All bags (incl. exceptions)</MenuItem>
              <MenuItem value="scoring">Scoring only</MenuItem>
              <MenuItem value="exceptions">Exceptions / not in scoring</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}

      {shortBags.length > 0 ? (
        <Alert severity="info" sx={{ mb: 1 }}>
          Short-duration diagnostic: {shortBags.length} bag(s) under 10 minutes or flagged
          FOLDING_DURATION_TOO_SHORT. They appear in the full sequence below; scoring count excludes them
          unless included_in_scoring = 1.
          {shortBags.map((b) => (
            <Typography key={b.bag_id} variant="caption" display="block">
              {b.bag_id}: {b.duration_minutes ?? (b.duration_seconds / 60)}m — {b.exception_code || b.status}
              {" "}(in scoring: {b.in_leaderboard_scoring ? "yes" : "no"})
            </Typography>
          ))}
        </Alert>
      ) : null}

      {data ? (
        <>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Bag-wise" />
            <Tab label="Work span" />
            <Tab label="Clock hours" />
          </Tabs>

          {tab === 0 ? (
            <>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                {data.mode_a_bag_wise?.denominator_note}
              </Typography>
              <ModeASummary s={modeA} labels={modeA.denominator_labels || {}} />
            </>
          ) : null}

          {tab === 1 ? (
            <ModeBSummary
              s={modeB}
              labels={modeB.denominator_labels || {}}
              spanNote={data.mode_b_work_span?.span_note}
            />
          ) : null}

          {tab === 2 ? (
            modeC.available ? (
              <ModeCSummary s={modeC.summary || {}} labels={modeC.summary?.denominator_labels || {}} shifts={modeC.shifts} />
            ) : (
              <Alert severity="warning">{modeC.message || "Clock-hour mode unavailable."}</Alert>
            )
          ) : null}

          <Typography variant="subtitle2" fontWeight={600} sx={{ mt: 2 }}>
            Sequential trail (stored folding times)
          </Typography>
          <BagSequenceTable
            rows={rows}
            filter={filter}
            loading={loading}
            onOpenTimeline={onOpenTimeline}
            onOpenOrder={onOpenOrder}
          />
        </>
      ) : loading ? (
        <Typography variant="body2" color="text.secondary">Loading productivity…</Typography>
      ) : null}
    </Box>
  );
}
