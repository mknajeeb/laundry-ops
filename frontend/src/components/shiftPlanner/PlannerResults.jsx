import {
  Alert,
  Box,
  Button,
  Chip,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { formatBottleneck } from "../../shiftPlanner/plannerHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

function SummaryCard({ label, value, sub, highlight }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: highlight ? "#16a34a55" : "#e2e8f0",
        bgcolor: highlight ? "#f0fdf4" : "#fff",
        minWidth: 0,
        flex: "1 1 140px",
      }}
    >
      <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, mt: 0.25 }}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block">{sub}</Typography>
      ) : null}
    </Paper>
  );
}

export function NextBatchDecisionCard({ decision }) {
  if (!decision) return null;
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlue,
        bgcolor: "#eff6ff",
      }}
    >
      <Typography variant="overline" fontWeight={800} color="primary">
        Next batch decision
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ mt: 0.5 }}>
        Batch #{decision.batch_number} · Start {decision.start_time || "—"}
      </Typography>
      <Grid container spacing={2} sx={{ mt: 1 }}>
        <Grid item xs={12} sm={4}>
          <Typography variant="caption" color="text.secondary">Already sorted</Typography>
          <Typography variant="body1" fontWeight={700}>{decision.bags_sorted_before_start ?? "—"}</Typography>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Typography variant="caption" color="text.secondary">Needed for batch</Typography>
          <Typography variant="body1" fontWeight={700}>{decision.bags_needed ?? "—"}</Typography>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Typography variant="caption" color="text.secondary">Sorted surplus</Typography>
          <Typography variant="body1" fontWeight={700} color={decision.sorted_surplus >= (decision.bags_needed || 0) ? "success.main" : "text.primary"}>
            {decision.sorted_surplus ?? 0}
          </Typography>
        </Grid>
      </Grid>
      <Alert severity="warning" sx={{ mt: 1.5, py: 0.5 }}>
        <Typography variant="body2" fontWeight={600}>{decision.recommendation}</Typography>
        {decision.alternative ? (
          <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>{decision.alternative}</Typography>
        ) : null}
      </Alert>
    </Paper>
  );
}

export function DecisionSummaryCards({ summary, inputsMeta }) {
  if (!summary) return null;
  const target = summary.target_time || inputsMeta.target_time || "target";
  return (
    <Stack direction="row" flexWrap="wrap" gap={1}>
      <SummaryCard label="Total bags" value={summary.total_bags ?? "—"} />
      <SummaryCard label="Washer loads" value={summary.total_washer_loads ?? "—"} />
      <SummaryCard label="Dryer loads" value={summary.total_dryer_loads ?? "—"} />
      <SummaryCard label={`Ready by ${target}`} value={summary.ready_by_target ?? "—"} sub={`/${summary.total_bags ?? ""}`} />
      <SummaryCard label={`Folded by ${target}`} value={`${summary.folded_by_target ?? "—"} / ${summary.total_bags ?? ""}`} highlight />
      <SummaryCard label="Ready not folded" value={summary.ready_not_folded_by_target ?? 0} />
      <SummaryCard label="Bottleneck" value={formatBottleneck(summary.bottleneck)} />
      <SummaryCard label="Rec. batch size" value={summary.recommended_batch_size ?? "—"} />
    </Stack>
  );
}

export function ActionPlanPanel({ actions, staffing, optimizer }) {
  if (!actions?.length) return null;
  const staff = staffing || optimizer?.suggested_staff || {};
  return (
    <Paper elevation={0} sx={{ p: 1.5, border: "1px solid #e2e8f0", borderRadius: 2 }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>Action plan</Typography>
      <Stack spacing={0.75} sx={{ mb: 1.5 }}>
        {actions.map((line) => (
          <Typography key={line} variant="body2">• {line}</Typography>
        ))}
      </Stack>
      <Stack direction="row" flexWrap="wrap" gap={0.5}>
        <Chip size="small" label={`Folders ${staff.folders ?? "—"}`} />
        <Chip size="small" label={`Sorters ${staff.sorters ?? "—"}`} />
        <Chip size="small" label={`Weighers ${staff.weighers ?? staff.using_weighers ?? "—"}`} />
        {optimizer?.label ? <Chip size="small" color="success" label={optimizer.label} /> : null}
      </Stack>
    </Paper>
  );
}

export function RunningMilestoneTable({ rows }) {
  if (!rows?.length) return null;
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden" }}>
      <Box sx={{ px: 1.5, py: 1, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
        <Typography variant="subtitle2" fontWeight={800}>Running milestones</Typography>
        <Typography variant="caption" color="text.secondary">
          Hourly counts — ready, folded, sorted surplus, and suggested action
        </Typography>
      </Box>
      <TableContainer sx={{ maxHeight: 420 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              <TableCell align="right">Weighed</TableCell>
              <TableCell align="right">Sorted</TableCell>
              <TableCell align="right">Sorted surplus</TableCell>
              <TableCell align="right">Wait wash</TableCell>
              <TableCell align="right">In wash</TableCell>
              <TableCell align="right">Wait dry</TableCell>
              <TableCell align="right">In dry</TableCell>
              <TableCell align="right">Ready fold</TableCell>
              <TableCell align="right">Folded</TableCell>
              <TableCell>Bottleneck</TableCell>
              <TableCell>Suggested action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.time || row.clock} hover>
                <TableCell sx={{ fontWeight: 600 }}>{row.time || row.clock}</TableCell>
                <TableCell align="right">{row.bags_weighed ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_sorted ?? "—"}</TableCell>
                <TableCell align="right">{row.sorted_surplus_before_next_batch ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_waiting_for_wash ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_in_wash ?? row.bags_in_washer ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_waiting_for_dryer ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_in_dryer ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_ready_for_fold ?? row.bags_ready_to_fold ?? "—"}</TableCell>
                <TableCell align="right">{row.bags_folded ?? "—"}</TableCell>
                <TableCell>{formatBottleneck(row.bottleneck)}</TableCell>
                <TableCell sx={{ maxWidth: 220 }}>
                  <Typography variant="caption">{row.suggested_action || row.action_needed || "—"}</Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export function CompactBatchTable({ rows }) {
  if (!rows?.length) return null;
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden" }}>
      <Box sx={{ px: 1.5, py: 1, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
        <Typography variant="subtitle2" fontWeight={800}>Batch timeline</Typography>
      </Box>
      <TableContainer sx={{ maxHeight: 360 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Batch</TableCell>
              <TableCell>Bags</TableCell>
              <TableCell align="right">Sorted before</TableCell>
              <TableCell align="right">Surplus</TableCell>
              <TableCell>Wash</TableCell>
              <TableCell>Dry</TableCell>
              <TableCell>Ready</TableCell>
              <TableCell>Fold end</TableCell>
              <TableCell align="right">Folded</TableCell>
              <TableCell>Bottleneck</TableCell>
              <TableCell>Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.batch_number} hover>
                <TableCell>#{row.batch_number}</TableCell>
                <TableCell>{row.order_range || row.batch_size}</TableCell>
                <TableCell align="right">{row.sorted_before_batch_start ?? row.sorted_in_batch_before_wash ?? "—"}</TableCell>
                <TableCell align="right">{row.sorted_surplus_before_start ?? 0}</TableCell>
                <TableCell>{row.wash_start && row.wash_end ? `${row.wash_start}–${row.wash_end}` : "—"}</TableCell>
                <TableCell>{row.dry_start && row.dry_end ? `${row.dry_start}–${row.dry_end}` : "—"}</TableCell>
                <TableCell>{row.ready_to_fold_at || "—"}</TableCell>
                <TableCell>{row.fold_end || row.fold_complete_at || "—"}</TableCell>
                <TableCell align="right">{row.bags_folded_by_batch_end ?? row.folded_at_end ?? "—"}</TableCell>
                <TableCell>{row.bottleneck_reason || row.bottleneck || "—"}</TableCell>
                <TableCell sx={{ maxWidth: 200 }}>
                  <Typography variant="caption">{row.suggested_action || "—"}</Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export function BatchCommandCenter({ batches, onApplyOverride }) {
  if (!batches?.length) return null;
  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" fontWeight={800}>Batch command center</Typography>
      <Typography variant="caption" color="text.secondary">
        Apply overrides to re-run simulation with updated batch timing (not guidance-only).
      </Typography>
      {batches.map((batch) => {
        const bn = batch.batch_number;
        const baseSize = Number(batch.batch_size || batch.orders_in_batch) || 8;
        return (
        <Paper key={batch.batch_number} elevation={0} sx={{ p: 1.25, border: "1px solid #e2e8f0", borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1}>
            <Box>
              <Typography variant="subtitle2" fontWeight={800}>Batch {batch.batch_number}</Typography>
              <Typography variant="caption" color="text.secondary">
                Size {batch.batch_size || batch.orders_in_batch} · {batch.batch_start || batch.wash_start} – {batch.batch_end_time || batch.batch_end}
              </Typography>
            </Box>
            <Chip size="small" label={batch.bottleneck || "None"} color={batch.bottleneck && batch.bottleneck !== "None" ? "warning" : "default"} />
          </Stack>
          <Grid container spacing={1} sx={{ mt: 0.75 }}>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">Sorted before start</Typography>
              <Typography variant="body2" fontWeight={700}>{batch.sorted_before_batch_start ?? batch.sorted_in_batch_before_wash ?? 0}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">Sorted surplus</Typography>
              <Typography variant="body2" fontWeight={700}>{batch.sorted_surplus_before_start ?? 0}</Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">Waiting wash / dry / fold</Typography>
              <Typography variant="body2" fontWeight={700}>
                {batch.bags_waiting_for_wash ?? 0} / {batch.bags_waiting_for_dryer ?? 0} / {batch.bags_waiting_for_fold ?? 0}
              </Typography>
            </Grid>
            <Grid item xs={6} sm={3}>
              <Typography variant="caption" color="text.secondary">Staffing</Typography>
              <Typography variant="body2" fontWeight={700}>{batch.staffing_recommendation || "—"}</Typography>
            </Grid>
          </Grid>
          <Typography variant="body2" sx={{ mt: 1 }}>{batch.suggested_action}</Typography>
          {batch.batch_size_recommendation ? (
            <Typography variant="caption" color="text.secondary" display="block">{batch.batch_size_recommendation}</Typography>
          ) : null}
          {onApplyOverride ? (
            <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
              <Button size="small" variant="outlined" onClick={() => onApplyOverride(bn, "this_batch_only", { sorter_helps_washer: true })}>
                Sorter helps (this batch)
              </Button>
              <Button size="small" variant="outlined" onClick={() => onApplyOverride(bn, "from_this_batch", { sorter_helps_washer: true })}>
                Sorter helps (from here)
              </Button>
              <Button size="small" variant="outlined" onClick={() => onApplyOverride(bn, "from_this_batch", { extra_folders: 1 })}>
                +1 folder (from here)
              </Button>
              <Button size="small" variant="outlined" onClick={() => onApplyOverride(bn, "from_this_batch", { batch_size: Math.min(12, baseSize + 2) })}>
                Batch +2 (from here)
              </Button>
              <Button size="small" variant="outlined" onClick={() => onApplyOverride(bn, "from_this_batch", { batch_size: Math.max(6, baseSize - 2) })}>
                Batch −2 (from here)
              </Button>
            </Stack>
          ) : null}
        </Paper>
        );
      })}
    </Stack>
  );
}

export function ScenarioCompareTable({ rows, loading }) {
  if (loading) {
    return <Typography variant="body2" color="text.secondary">Loading scenario comparisons…</Typography>;
  }
  if (!rows?.length) {
    return (
      <Alert severity="info">
        Run simulation with Compare tab open to load scenario comparisons (+1 folder, batch sizes, etc.).
      </Alert>
    );
  }
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden" }}>
      <Box sx={{ px: 1.5, py: 1, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
        <Typography variant="subtitle2" fontWeight={800}>What-if comparison</Typography>
        <Typography variant="caption" color="text.secondary">Changes vs current setup — no duplicate inputs</Typography>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Scenario</TableCell>
            <TableCell align="right">Ready @ target</TableCell>
            <TableCell align="right">Folded @ target</TableCell>
            <TableCell>Finish</TableCell>
            <TableCell>Bottleneck</TableCell>
            <TableCell align="right">Fold Δ</TableCell>
            <TableCell align="right">Ready Δ</TableCell>
            <TableCell>Recommendation</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.scenario} hover>
              <TableCell sx={{ fontWeight: row.scenario === "Current" ? 700 : 400 }}>{row.scenario}</TableCell>
              <TableCell align="right">{row.ready_by_target ?? "—"}</TableCell>
              <TableCell align="right">{row.folded_by_target ?? "—"}</TableCell>
              <TableCell>{row.estimated_finish_time || "—"}</TableCell>
              <TableCell>{formatBottleneck(row.bottleneck)}</TableCell>
              <TableCell align="right">{row.impact > 0 ? `+${row.impact}` : row.impact ?? "—"}</TableCell>
              <TableCell align="right">{row.ready_impact > 0 ? `+${row.ready_impact}` : row.ready_impact ?? "—"}</TableCell>
              <TableCell>{row.recommendation || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  );
}

export function QuickScenarioButtons({ scenarios, onApply, disabled }) {
  return (
    <Stack direction="row" flexWrap="wrap" gap={0.75}>
      {scenarios.map((s) => (
        <Chip
          key={s.key}
          label={s.label}
          clickable
          disabled={disabled}
          onClick={() => onApply(s)}
          variant="outlined"
          size="small"
        />
      ))}
    </Stack>
  );
}
