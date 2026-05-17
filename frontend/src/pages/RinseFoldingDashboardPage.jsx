import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
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
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  getFoldingBenchmarks,
  getFoldingLeaderboard,
  getFoldingPerformanceDetail,
  listFoldingExceptions,
  listFoldingPerformance,
  overrideFoldingPerformance,
  recomputeFoldingPerformance,
  updateFoldingBenchmarks,
} from "../api";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import {
  formatDateTime,
  formatFoldingDuration,
  formatFoldingHours,
  formatLbs,
  formatRate,
  isoDateInput,
  targetStatusChipColor,
} from "../utils/foldingFormat";

function isFoldingAdmin(user) {
  const roles = (user?.roles || []).map((r) => String(r).toUpperCase());
  return roles.some((r) => ["ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"].includes(r));
}

function SummaryCard({ label, value, sub }) {
  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h5" fontWeight={700}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary">
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}

function RinseFoldingDashboardPage({ user }) {
  const admin = isFoldingAdmin(user);
  const today = isoDateInput();
  const weekAgo = isoDateInput(new Date(Date.now() - 6 * 86400000));

  const [anchorDate, setAnchorDate] = useState(today);
  const [period, setPeriod] = useState("today");
  const [leaderboard, setLeaderboard] = useState(null);
  const [records, setRecords] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  const [recomputeStart, setRecomputeStart] = useState(weekAgo);
  const [recomputeEnd, setRecomputeEnd] = useState(today);
  const [dateField, setDateField] = useState("date_clean");
  const [recomputeSummary, setRecomputeSummary] = useState(null);
  const [recomputing, setRecomputing] = useState(false);

  const [benchmarks, setBenchmarks] = useState(null);
  const [benchmarksOpen, setBenchmarksOpen] = useState(false);
  const [benchBags, setBenchBags] = useState("2.5");
  const [benchLbs, setBenchLbs] = useState("40");

  const [drawerBagId, setDrawerBagId] = useState(null);
  const [drawerDetail, setDrawerDetail] = useState(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideBagId, setOverrideBagId] = useState(null);
  const [overrideForm, setOverrideForm] = useState({
    assigned_user_name: "",
    folding_start_at: "",
    folding_end_at: "",
    admin_notes: "",
    notes: "",
    excluded_from_performance: false,
  });

  const workDateFilter = period === "today" ? anchorDate : null;

  const loadAll = useCallback(async () => {
    try {
      setLoading(true);
      setMessage({ type: "", text: "" });
      const [lbRes, benchRes, recRes, exRes] = await Promise.all([
        getFoldingLeaderboard({ period, date: anchorDate }),
        getFoldingBenchmarks(),
        listFoldingPerformance({
          limit: 500,
          ...(workDateFilter ? { work_date: workDateFilter } : {}),
        }),
        listFoldingExceptions({ limit: 500 }),
      ]);
      setLeaderboard(lbRes.data);
      setBenchmarks(benchRes.data);
      setBenchBags(String(benchRes.data?.bags_per_hour_target ?? 2.5));
      setBenchLbs(String(benchRes.data?.lbs_per_hour_target ?? 40));
      let rec = recRes.data || [];
      if (period === "week" && lbRes.data?.period_start) {
        const ps = lbRes.data.period_start;
        const pe = lbRes.data.period_end;
        rec = rec.filter((r) => {
          const wd = String(r.work_date || "").slice(0, 10);
          return wd >= ps && wd <= pe;
        });
      }
      setRecords(rec);
      setExceptions(exRes.data || []);
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || e?.message || "Failed to load folding data",
      });
    } finally {
      setLoading(false);
    }
  }, [anchorDate, period, workDateFilter]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const openDrawer = async (bagId) => {
    setDrawerBagId(bagId);
    setDrawerDetail(null);
    try {
      const res = await getFoldingPerformanceDetail(bagId);
      setDrawerDetail(res.data);
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Could not load bag detail",
      });
    }
  };

  const openOverride = (row, preExclude = false) => {
    const bid = row?.bag_id;
    if (!bid) return;
    setOverrideBagId(bid);
    setOverrideForm({
      assigned_user_name: row?.assigned_user_name || "",
      folding_start_at: row?.folding_start_at
        ? String(row.folding_start_at).slice(0, 16)
        : "",
      folding_end_at: row?.folding_end_at ? String(row.folding_end_at).slice(0, 16) : "",
      admin_notes: row?.admin_notes || "",
      notes: "",
      excluded_from_performance: preExclude,
    });
    setOverrideOpen(true);
  };

  const submitOverride = async () => {
    if (!overrideBagId) return;
    try {
      const body = {
        assigned_user_name: overrideForm.assigned_user_name || undefined,
        admin_notes: overrideForm.admin_notes || undefined,
        notes: overrideForm.notes || undefined,
        excluded_from_performance: overrideForm.excluded_from_performance,
      };
      if (overrideForm.folding_start_at) {
        body.folding_start_at = new Date(overrideForm.folding_start_at).toISOString();
      }
      if (overrideForm.folding_end_at) {
        body.folding_end_at = new Date(overrideForm.folding_end_at).toISOString();
      }
      await overrideFoldingPerformance(overrideBagId, body);
      setOverrideOpen(false);
      setMessage({ type: "success", text: `Override saved for ${overrideBagId}` });
      await loadAll();
      if (drawerBagId === overrideBagId) await openDrawer(overrideBagId);
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Override failed",
      });
    }
  };

  const runRecompute = async () => {
    try {
      setRecomputing(true);
      setRecomputeSummary(null);
      const res = await recomputeFoldingPerformance({
        start_date: recomputeStart,
        end_date: recomputeEnd,
        date_field: dateField,
      });
      setRecomputeSummary(res.data?.summary || null);
      setMessage({ type: "success", text: "Folding performance recompute finished." });
      await loadAll();
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Recompute failed",
      });
    } finally {
      setRecomputing(false);
    }
  };

  const saveBenchmarks = async () => {
    try {
      await updateFoldingBenchmarks({
        bags_per_hour_target: parseFloat(benchBags),
        lbs_per_hour_target: parseFloat(benchLbs),
      });
      setBenchmarksOpen(false);
      setMessage({ type: "success", text: "Benchmarks updated." });
      await loadAll();
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Failed to update benchmarks",
      });
    }
  };

  const team = leaderboard?.team || {};
  const bench = leaderboard?.benchmarks || benchmarks || {};
  const vsBags =
    team.bags_per_hour != null && bench.bags_per_hour_target != null
      ? team.bags_per_hour - bench.bags_per_hour_target
      : null;
  const vsLbs =
    team.lbs_per_hour != null && bench.lbs_per_hour_target != null
      ? team.lbs_per_hour - bench.lbs_per_hour_target
      : null;

  const staffRows = leaderboard?.users || [];

  const perf = drawerDetail?.performance;
  const registry = drawerDetail?.registry;

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1400, mx: "auto" }}>
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems="flex-start" gap={2} mb={2}>
        <Box>
          <Typography variant="h4" fontWeight={800}>
            Folding Performance Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Manage folding metrics for completed bags. Recompute manually after scan uploads.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <TextField
            type="date"
            size="small"
            label="Date"
            value={anchorDate}
            onChange={(e) => setAnchorDate(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <ToggleButtonGroup
            size="small"
            exclusive
            value={period}
            onChange={(_, v) => v && setPeriod(v)}
          >
            <ToggleButton value="today">Today</ToggleButton>
            <ToggleButton value="week">This week</ToggleButton>
          </ToggleButtonGroup>
          <Button variant="outlined" size="small" onClick={loadAll} disabled={loading}>
            Refresh
          </Button>
          {admin ? (
            <Button variant="outlined" size="small" onClick={() => setBenchmarksOpen(true)}>
              Benchmarks
            </Button>
          ) : null}
        </Stack>
      </Stack>

      {message.text ? (
        <Alert severity={message.type || "info"} sx={{ mb: 2 }} onClose={() => setMessage({ type: "", text: "" })}>
          {message.text}
        </Alert>
      ) : null}

      {admin ? (
        <Paper sx={{ p: 2, mb: 3 }}>
          <Typography variant="subtitle1" fontWeight={700} gutterBottom>
            Generate / Recompute Performance
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap">
            <TextField
              type="date"
              size="small"
              label="Start"
              value={recomputeStart}
              onChange={(e) => setRecomputeStart(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              type="date"
              size="small"
              label="End"
              value={recomputeEnd}
              onChange={(e) => setRecomputeEnd(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Date field</InputLabel>
              <Select label="Date field" value={dateField} onChange={(e) => setDateField(e.target.value)}>
                <MenuItem value="date_clean">date_clean</MenuItem>
                <MenuItem value="completed_at">completed_at</MenuItem>
              </Select>
            </FormControl>
            <Button variant="contained" onClick={runRecompute} disabled={recomputing}>
              {recomputing ? "Running…" : "Generate / Recompute"}
            </Button>
          </Stack>
          {recomputeSummary ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
              <Chip label={`Processed: ${recomputeSummary.processed ?? 0}`} size="small" />
              <Chip label={`Skipped (not completed): ${recomputeSummary.skipped_not_completed ?? 0}`} size="small" />
              <Chip label={`Calculated: ${recomputeSummary.calculated ?? 0}`} size="small" color="success" />
              <Chip label={`Exceptions: ${recomputeSummary.exceptions ?? 0}`} size="small" color="warning" />
              <Chip label={`Warnings: ${recomputeSummary.warnings ?? 0}`} size="small" />
              <Chip label={`Errors: ${recomputeSummary.errors ?? 0}`} size="small" color="error" />
            </Stack>
          ) : null}
        </Paper>
      ) : null}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Bags folded" value={team.bag_count ?? 0} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Total lbs" value={formatLbs(team.total_lbs)} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="Folding hours"
            value={formatFoldingHours(team.total_folding_seconds)}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Bags / hour" value={formatRate(team.bags_per_hour)} sub={`Target ${formatRate(bench.bags_per_hour_target)}`} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard label="Lbs / hour" value={formatRate(team.lbs_per_hour)} sub={`Target ${formatRate(bench.lbs_per_hour_target)}`} />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="vs target (bags/hr)"
            value={vsBags != null ? (vsBags >= 0 ? `+${formatRate(vsBags)}` : formatRate(vsBags)) : "—"}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <SummaryCard
            label="vs target (lbs/hr)"
            value={vsLbs != null ? (vsLbs >= 0 ? `+${formatRate(vsLbs)}` : formatRate(vsLbs)) : "—"}
          />
        </Grid>
      </Grid>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Staff leaderboard
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Rank</TableCell>
              <TableCell>Staff</TableCell>
              <TableCell align="right">Bags</TableCell>
              <TableCell align="right">Lbs</TableCell>
              <TableCell align="right">Hours</TableCell>
              <TableCell align="right">Bags/hr</TableCell>
              <TableCell align="right">Lbs/hr</TableCell>
              <TableCell align="right">Gap</TableCell>
              <TableCell>Target</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {staffRows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={9} align="center">
                  No calculated performance for this period. Run recompute after uploading scans.
                </TableCell>
              </TableRow>
            ) : (
              staffRows.map((u) => (
                <TableRow key={u.user_name} hover>
                  <TableCell>{u.rank}</TableCell>
                  <TableCell>{u.user_name}</TableCell>
                  <TableCell align="right">{u.bag_count}</TableCell>
                  <TableCell align="right">{formatLbs(u.total_lbs)}</TableCell>
                  <TableCell align="right">{formatFoldingHours(u.total_folding_seconds)}</TableCell>
                  <TableCell align="right">{formatRate(u.bags_per_hour)}</TableCell>
                  <TableCell align="right">{formatRate(u.lbs_per_hour)}</TableCell>
                  <TableCell align="right">{formatFoldingDuration(u.gap_seconds_total)}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={u.target_status || "n/a"}
                      color={targetStatusChipColor(u.target_status)}
                    />
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Folding records
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Bag ID</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell align="right">Weight</TableCell>
              <TableCell>User</TableCell>
              <TableCell>Start</TableCell>
              <TableCell>End</TableCell>
              <TableCell>Duration</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Exception</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {records.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center">
                  No records for this period.
                </TableCell>
              </TableRow>
            ) : (
              records.map((r) => (
                <TableRow key={r.bag_id} hover>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                  <TableCell>{r.name_clean || "—"}</TableCell>
                  <TableCell align="right">
                    {formatLbs(r.weight_lbs ?? r.registry_weight_num)}
                  </TableCell>
                  <TableCell>{r.assigned_user_name || "—"}</TableCell>
                  <TableCell>{formatDateTime(r.folding_start_at)}</TableCell>
                  <TableCell>{formatDateTime(r.folding_end_at)}</TableCell>
                  <TableCell>{formatFoldingDuration(r.duration_seconds)}</TableCell>
                  <TableCell>
                    <Chip size="small" label={r.status} color={r.status === "CALCULATED" ? "success" : "warning"} />
                  </TableCell>
                  <TableCell>{r.exception_code || "—"}</TableCell>
                  <TableCell>
                    <Button size="small" onClick={() => openDrawer(r.bag_id)}>
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Exceptions
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Bag ID</TableCell>
              <TableCell>Code</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell align="right">Weight</TableCell>
              <TableCell>User</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {exceptions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center">
                  No exceptions.
                </TableCell>
              </TableRow>
            ) : (
              exceptions.map((r) => (
                <TableRow key={r.bag_id} hover>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{r.bag_id}</TableCell>
                  <TableCell>{r.exception_code}</TableCell>
                  <TableCell>{r.name_clean || "—"}</TableCell>
                  <TableCell align="right">
                    {formatLbs(r.weight_lbs ?? r.registry_weight_num)}
                  </TableCell>
                  <TableCell>{r.assigned_user_name || "—"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      <Button size="small" onClick={() => openDrawer(r.bag_id)}>
                        Timeline
                      </Button>
                      {admin ? (
                        <>
                          <Button size="small" onClick={() => openOverride(r)}>
                            Override
                          </Button>
                          <Button size="small" color="warning" onClick={() => openOverride(r, true)}>
                            Exclude
                          </Button>
                        </>
                      ) : null}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Paper>

      <Drawer anchor="right" open={Boolean(drawerBagId)} onClose={() => setDrawerBagId(null)}>
        <Box sx={{ width: { xs: "100vw", sm: 480 }, p: 2 }}>
          <Typography variant="h6" fontWeight={700} gutterBottom>
            Bag {drawerBagId}
          </Typography>
          {perf ? (
            <Stack spacing={1} sx={{ mb: 2 }}>
              <Typography variant="body2">
                Registry: {registry?.completion_status || "—"}
              </Typography>
              <Typography variant="body2">Customer: {perf.name_clean || registry?.name_clean || "—"}</Typography>
              <Typography variant="body2">Status: {perf.status}</Typography>
              <Typography variant="body2">User: {perf.assigned_user_name || "—"}</Typography>
              <Typography variant="body2">
                Duration: {formatFoldingDuration(perf.duration_seconds)}
              </Typography>
              <Typography variant="body2">Exception: {perf.exception_code || "—"}</Typography>
              {perf.admin_notes ? (
                <Typography variant="body2">Notes: {perf.admin_notes}</Typography>
              ) : null}
              {admin ? (
                <Button size="small" variant="outlined" onClick={() => openOverride(perf)}>
                  Override
                </Button>
              ) : null}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Loading…
            </Typography>
          )}
          <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
            Scan events
          </Typography>
          <FoldingScanEventsTable events={drawerDetail?.scan_events} />
          {drawerDetail?.override_history?.length ? (
            <>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
                Override history
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Field</TableCell>
                    <TableCell>Old</TableCell>
                    <TableCell>New</TableCell>
                    <TableCell>When</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {drawerDetail.override_history.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell>{o.field_name}</TableCell>
                      <TableCell>{o.old_value ?? "—"}</TableCell>
                      <TableCell>{o.new_value ?? "—"}</TableCell>
                      <TableCell>{formatDateTime(o.created_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          ) : null}
        </Box>
      </Drawer>

      <Dialog open={overrideOpen} onClose={() => setOverrideOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Override — {overrideBagId}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Assigned user"
              value={overrideForm.assigned_user_name}
              onChange={(e) =>
                setOverrideForm((f) => ({ ...f, assigned_user_name: e.target.value }))
              }
              fullWidth
            />
            <TextField
              label="Folding start"
              type="datetime-local"
              value={overrideForm.folding_start_at}
              onChange={(e) =>
                setOverrideForm((f) => ({ ...f, folding_start_at: e.target.value }))
              }
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Folding end"
              type="datetime-local"
              value={overrideForm.folding_end_at}
              onChange={(e) =>
                setOverrideForm((f) => ({ ...f, folding_end_at: e.target.value }))
              }
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Admin notes"
              value={overrideForm.admin_notes}
              onChange={(e) => setOverrideForm((f) => ({ ...f, admin_notes: e.target.value }))}
              fullWidth
              multiline
              minRows={2}
            />
            <TextField
              label="Override notes"
              value={overrideForm.notes}
              onChange={(e) => setOverrideForm((f) => ({ ...f, notes: e.target.value }))}
              fullWidth
            />
            {overrideForm.excluded_from_performance ? (
              <Alert severity="warning">This bag will be excluded from performance stats.</Alert>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOverrideOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitOverride}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={benchmarksOpen} onClose={() => setBenchmarksOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Folding benchmarks</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Bags per hour target"
              type="number"
              value={benchBags}
              onChange={(e) => setBenchBags(e.target.value)}
              fullWidth
            />
            <TextField
              label="Lbs per hour target"
              type="number"
              value={benchLbs}
              onChange={(e) => setBenchLbs(e.target.value)}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBenchmarksOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveBenchmarks}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default RinseFoldingDashboardPage;
