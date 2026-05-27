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
  formatRate,
} from "../../utils/foldingFormat";
import FoldingExceptionCell from "./FoldingExceptionCell";
import FoldingScoringOverrideMenu from "./FoldingScoringOverrideMenu";

const timeCellSx = { whiteSpace: "nowrap", fontSize: 12, py: 1 };

function SummaryCard({ label, value, sub }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" fontWeight={700}>{value}</Typography>
      {sub ? <Typography variant="caption" color="text.secondary">{sub}</Typography> : null}
    </Paper>
  );
}

export default function FoldingEmployeeProductivityPanel({
  userName,
  appliedDateStart,
  appliedDateEnd,
  appliedListDateField,
  searchTick,
  admin,
  onOpenTimeline,
  onOpenOrder,
  onMapUser,
}) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState(0);
  const [shiftId, setShiftId] = useState("");
  const [shiftFilter, setShiftFilter] = useState("all");
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
      const params = {
        ...foldingRangeParams({
          dateStart: appliedDateStart,
          dateEnd: appliedDateEnd,
          dateField: appliedListDateField,
        }),
        user_name: uname,
        shift_filter: shiftFilter,
      };
      if (shiftId) params.shift_id = shiftId;
      const res = await getFoldingUserProductivity(params);
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load employee productivity");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [
    userName,
    appliedDateStart,
    appliedDateEnd,
    appliedListDateField,
    searchTick,
    shiftId,
    shiftFilter,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  const clocked = data?.clocked_productivity || {};
  const gaming = data?.gaming_scoring || {};
  const topSummary = useMemo(() => {
    if (clocked.available && clocked.summary) return clocked.summary;
    return gaming.summary || {};
  }, [clocked, gaming]);

  const shifts = clocked.shifts || [];

  if (!userName) return null;

  return (
    <Box mt={3}>
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>
        Employee productivity — {userName}
      </Typography>

      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Shifts</InputLabel>
          <Select
            label="Shifts"
            value={shiftFilter}
            onChange={(e) => setShiftFilter(e.target.value)}
          >
            <MenuItem value="all">All shifts</MenuItem>
            <MenuItem value="active">Active shifts</MenuItem>
            <MenuItem value="completed">Completed shifts</MenuItem>
          </Select>
        </FormControl>
        {shifts.length > 1 ? (
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel>Shift</InputLabel>
            <Select
              label="Shift"
              value={shiftId}
              onChange={(e) => setShiftId(e.target.value)}
            >
              <MenuItem value="">All shifts in period</MenuItem>
              {shifts.map((sh) => (
                <MenuItem key={sh.shift_id} value={String(sh.shift_id)}>
                  {formatFoldingWallDateTime(sh.clock_in_at)}
                  {" → "}
                  {sh.is_active
                    ? "active"
                    : formatFoldingWallDateTime(sh.clock_out_at || sh.effective_clock_out_at)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ) : null}
        <Button size="small" variant="outlined" onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}

      {!clocked.available ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {clocked.message || "Clocked productivity unavailable."}
          {clocked.map_user_hint && onMapUser ? (
            <Button size="small" sx={{ ml: 1 }} onClick={onMapUser}>
              Map Rinse user to clock employee
            </Button>
          ) : null}
          {clocked.map_user_hint ? (
            <Typography variant="caption" display="block" sx={{ mt: 1 }}>
              Gaming / scoring records below still use Rinse assigned_user_name.
            </Typography>
          ) : null}
        </Alert>
      ) : null}

      {data ? (
        <>
          <Grid container spacing={1.5} sx={{ mb: 2 }}>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Clocked hours"
                value={topSummary.clocked_hours != null ? formatRate(topSummary.clocked_hours, 2) : "—"}
                sub={topSummary.shift_count ? `${topSummary.shift_count} shifts` : undefined}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Total orders/bags" value={topSummary.total_bags ?? 0} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard label="Total lbs" value={formatLbs(topSummary.total_lbs)} />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Bags per clocked hour"
                value={formatRate(topSummary.bags_per_clocked_hour, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Lbs per clocked hour"
                value={formatRate(topSummary.lbs_per_clocked_hour, 2)}
              />
            </Grid>
            <Grid item xs={6} md={2}>
              <SummaryCard
                label="Used for scoring"
                value={topSummary.scoring_bags ?? 0}
                sub={formatLbs(topSummary.scoring_lbs)}
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <SummaryCard
                label="Excluded from scoring"
                value={topSummary.not_in_scoring_bags ?? topSummary.exception_bags ?? 0}
              />
            </Grid>
          </Grid>

          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Clocked productivity" />
            <Tab label="Gaming / scoring records" />
          </Tabs>

          {tab === 0 ? (
            clocked.available ? (
              <>
                {clocked.summary?.estimate_label ? (
                  <Alert severity="info" sx={{ mb: 2 }}>{clocked.summary.estimate_label}</Alert>
                ) : null}
                {shifts.length > 0 ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Employee</TableCell>
                        <TableCell>Clock in</TableCell>
                        <TableCell>Clock out</TableCell>
                        <TableCell align="right">Clocked hrs</TableCell>
                        <TableCell align="right">Bags</TableCell>
                        <TableCell align="right">Lbs</TableCell>
                        <TableCell align="right">Bags per clocked hour</TableCell>
                        <TableCell align="right">Lbs per clocked hour</TableCell>
                        <TableCell align="right">Used for scoring</TableCell>
                        <TableCell align="right">Excluded from scoring</TableCell>
                        <TableCell>Note</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {shifts.map((sh) => (
                        <TableRow
                          key={sh.shift_id}
                          hover
                          selected={String(shiftId) === String(sh.shift_id)}
                          sx={{ cursor: shifts.length > 1 ? "pointer" : undefined }}
                          onClick={() => {
                            if (shifts.length > 1) setShiftId(String(sh.shift_id));
                          }}
                        >
                          <TableCell>{sh.employee_name || userName}</TableCell>
                          <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(sh.clock_in_at)}</TableCell>
                          <TableCell sx={timeCellSx}>
                            {sh.clock_out_at
                              ? formatFoldingWallDateTime(sh.clock_out_at)
                              : formatFoldingWallDateTime(sh.effective_clock_out_at)}
                          </TableCell>
                          <TableCell align="right">{formatRate(sh.clocked_hours, 2)}</TableCell>
                          <TableCell align="right">{sh.total_bags}</TableCell>
                          <TableCell align="right">{formatLbs(sh.total_lbs)}</TableCell>
                          <TableCell align="right">{formatRate(sh.bags_per_clocked_hour, 2)}</TableCell>
                          <TableCell align="right">{formatRate(sh.lbs_per_clocked_hour, 2)}</TableCell>
                          <TableCell align="right">{sh.scoring_bags}</TableCell>
                          <TableCell align="right">{sh.not_in_scoring_bags}</TableCell>
                          <TableCell>
                            {sh.is_active_estimate ? (
                              <Typography variant="caption" color="warning.main">
                                {sh.estimate_label}
                              </Typography>
                            ) : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    No shift_sessions overlap this date range.
                  </Typography>
                )}
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Map this Rinse user to a clock employee to see clocked productivity.
              </Typography>
            )
          ) : null}

          {tab === 1 ? (
            <>
              <Grid container spacing={1.5} sx={{ mb: 2 }}>
                <Grid item xs={6} md={3}>
                  <SummaryCard label="Total bags folded" value={gaming.summary?.total_bags ?? 0} />
                </Grid>
                <Grid item xs={6} md={3}>
                  <SummaryCard label="Used for scoring" value={gaming.summary?.scoring_bags ?? 0} />
                </Grid>
                <Grid item xs={6} md={3}>
                  <SummaryCard
                    label="Excluded from scoring"
                    value={gaming.summary?.not_in_scoring_bags ?? 0}
                  />
                </Grid>
                <Grid item xs={6} md={3}>
                  <SummaryCard
                    label="Warnings (in scoring)"
                    value={gaming.summary?.warning_count ?? 0}
                    sub={`Exceptions: ${gaming.summary?.exception_count ?? 0}`}
                  />
                </Grid>
              </Grid>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Bag ID</TableCell>
                    <TableCell>Customer</TableCell>
                    <TableCell align="right">Weight</TableCell>
                    <TableCell sx={timeCellSx}>Folding start</TableCell>
                    <TableCell sx={timeCellSx}>Folding end</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Exception / warning</TableCell>
                    <TableCell>Used for scoring</TableCell>
                    <TableCell>Scoring status</TableCell>
                    <TableCell>Override</TableCell>
                    <TableCell>Reason</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(gaming.rows || []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={12} align="center" sx={{ py: 2, color: "text.secondary" }}>
                        {loading ? "Loading…" : "No records for this filter."}
                      </TableCell>
                    </TableRow>
                  ) : (gaming.rows || []).map((r) => (
                    <TableRow
                      key={r.bag_id}
                      sx={{
                        bgcolor: r.included_in_scoring ? undefined : "rgba(255, 152, 0, 0.08)",
                      }}
                    >
                      <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                      <TableCell>{r.customer || "—"}</TableCell>
                      <TableCell align="right">{r.weight_lbs != null ? formatLbs(r.weight_lbs) : "—"}</TableCell>
                      <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_start_at)}</TableCell>
                      <TableCell sx={timeCellSx}>{formatFoldingWallDateTime(r.folding_end_at)}</TableCell>
                      <TableCell>
                        {r.duration_minutes != null
                          ? `${r.duration_minutes}m`
                          : formatFoldingDuration(r.duration_seconds)}
                      </TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={r.status || "—"}
                          color={r.included_in_scoring ? "success" : "warning"}
                        />
                      </TableCell>
                      <TableCell>
                        <FoldingExceptionCell row={r} compact />
                      </TableCell>
                      <TableCell>{r.included_in_scoring ? "Yes" : "No"}</TableCell>
                      <TableCell>{r.scoring_status || "—"}</TableCell>
                      <TableCell>{r.scoring_override || "—"}</TableCell>
                      <TableCell sx={{ fontSize: 12 }}>{r.reason || "—"}</TableCell>
                      <TableCell>
                        <Stack spacing={0.5}>
                          <Stack direction="row" spacing={0.5} flexWrap="wrap">
                            {onOpenTimeline ? (
                              <Button size="small" onClick={() => onOpenTimeline(r.bag_id)}>
                                Timeline
                              </Button>
                            ) : null}
                            {onOpenOrder ? (
                              <Button size="small" onClick={() => onOpenOrder(r.bag_id)}>
                                Order
                              </Button>
                            ) : null}
                          </Stack>
                          {admin ? (
                            <FoldingScoringOverrideMenu bagId={r.bag_id} onDone={load} />
                          ) : null}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          ) : null}
        </>
      ) : loading ? (
        <Typography variant="body2" color="text.secondary">Loading productivity…</Typography>
      ) : null}
    </Box>
  );
}
