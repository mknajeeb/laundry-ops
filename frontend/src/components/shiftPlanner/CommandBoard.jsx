import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  FormControlLabel,
  Checkbox,
  Grid,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { STRATEGY_FLAGS, HELPER_ASSIGN_OPTIONS } from "../../shiftPlanner/constants";
import {
  formatBottleneck,
  helperFieldsFromAssignment,
  buildBatchOverride,
} from "../../shiftPlanner/plannerHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const activityColor = {
  weighing: "#dbeafe",
  sorting: "#fef3c7",
  "helping washer": "#fde68a",
  "loading washer": "#e0e7ff",
  "transferring to dryer": "#fce7f3",
  "loading dryer": "#f3e8ff",
  folding: "#dcfce7",
  idle: "#f1f5f9",
  "on sorter": "#fef3c7",
};

function cellBg(activity) {
  if (!activity) return "#fff";
  const key = String(activity).toLowerCase();
  for (const [label, color] of Object.entries(activityColor)) {
    if (key.includes(label)) return color;
  }
  if (key.includes("wash")) return "#e0e7ff";
  if (key.includes("dry")) return "#f3e8ff";
  return "#fff";
}

export function TopControls({ inputs, onChange, onToggleFlag, onRun, loading }) {
  return (
    <Paper elevation={0} sx={{ p: 1.5, border: "1px solid #e2e8f0", borderRadius: 2 }}>
      <Grid container spacing={1} alignItems="center">
        <Grid item xs={6} sm={4} md={2}>
          <TextField label="Shift start" size="small" fullWidth value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} />
        </Grid>
        <Grid item xs={6} sm={4} md={2}>
          <TextField label="Target time" size="small" fullWidth value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} />
        </Grid>
        <Grid item xs={4} sm={3} md={1.5}>
          <TextField label="Bags" type="number" size="small" fullWidth value={inputs.bag_count} onChange={(e) => onChange("bag_count", e.target.value)} />
        </Grid>
        <Grid item xs={4} sm={3} md={1.5}>
          <TextField label="Batch size" type="number" size="small" fullWidth value={inputs.batch_size} onChange={(e) => onChange("batch_size", e.target.value)} inputProps={{ min: 6, max: 12 }} />
        </Grid>
        <Grid item xs={4} sm={3} md={1}>
          <TextField label="Washers" type="number" size="small" fullWidth value={inputs.washer_count} onChange={(e) => onChange("washer_count", e.target.value)} />
        </Grid>
        <Grid item xs={4} sm={3} md={1}>
          <TextField label="Dryers" type="number" size="small" fullWidth value={inputs.dryer_count} onChange={(e) => onChange("dryer_count", e.target.value)} />
        </Grid>
        <Grid item xs={12} sm="auto">
          <Button
            variant="contained"
            startIcon={loading ? null : <PlayArrowIcon />}
            onClick={onRun}
            disabled={loading}
            sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700, minWidth: 160 }}
          >
            {loading ? "Running…" : "Run simulation"}
          </Button>
        </Grid>
      </Grid>
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
        {STRATEGY_FLAGS.map((flag) => (
          <FormControlLabel
            key={flag.key}
            control={
              <Checkbox
                size="small"
                checked={(inputs.strategy_flags || []).includes(flag.key)}
                onChange={() => onToggleFlag(flag.key)}
              />
            }
            label={<Typography variant="caption">{flag.label}</Typography>}
          />
        ))}
      </Stack>
    </Paper>
  );
}

export function LaborControls({ inputs, onChange }) {
  return (
    <Paper elevation={0} sx={{ p: 1.25, border: "1px solid #e2e8f0", borderRadius: 2 }}>
      <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ textTransform: "uppercase" }}>
        Labor & timing
      </Typography>
      <Grid container spacing={1} sx={{ mt: 0.5 }}>
        {[
          ["sorter_count", "Sorters"],
          ["weigher_count", "Weighers"],
          ["washer_person_count", "Washer persons"],
          ["folder_count", "Folders"],
          ["wash_cycle_min", "Wash min"],
          ["dry_cycle_min", "Dry min"],
          ["sort_min_per_bag", "Sort min/bag"],
          ["fold_min_per_bag", "Fold min/bag"],
          ["orders_using_2_washers", "2-washer orders"],
          ["orders_using_2_dryers", "2-dryer orders"],
        ].map(([key, label]) => (
          <Grid item xs={6} sm={4} md={2.4} key={key}>
            <TextField label={label} type="number" size="small" fullWidth value={inputs[key]} onChange={(e) => onChange(key, e.target.value)} />
          </Grid>
        ))}
      </Grid>
    </Paper>
  );
}

export function SummaryStrip({ summary }) {
  if (!summary) return null;
  const cards = [
    ["Ready @ target", summary.ready_by_target],
    ["Folded @ target", summary.folded_by_target, true],
    ["Bottleneck", formatBottleneck(summary.bottleneck)],
    ["Washer loads", summary.total_washer_loads],
    ["Dryer loads", summary.total_dryer_loads],
  ];
  return (
    <Stack direction="row" flexWrap="wrap" gap={1}>
      {cards.map(([label, value, highlight]) => (
        <Paper
          key={label}
          elevation={0}
          sx={{
            px: 1.5,
            py: 1,
            borderRadius: 2,
            border: "1px solid",
            borderColor: highlight ? "#16a34a55" : "#e2e8f0",
            bgcolor: highlight ? "#f0fdf4" : "#fff",
            minWidth: 120,
          }}
        >
          <Typography variant="caption" fontWeight={700} color="text.secondary">{label}</Typography>
          <Typography variant="h6" fontWeight={800}>{value ?? "—"}</Typography>
        </Paper>
      ))}
    </Stack>
  );
}

export function NextBatchPanel({ nextBatch }) {
  if (!nextBatch) return null;
  const impact = nextBatch.impact;
  return (
    <Paper elevation={0} sx={{ p: 2, border: "2px solid", borderColor: VEEWASH_DASHBOARD.primaryBlue, borderRadius: 2, bgcolor: "#eff6ff" }}>
      <Typography variant="overline" fontWeight={800} color="primary">Next batch decision</Typography>
      <Typography variant="h6" fontWeight={800}>
        Batch #{nextBatch.batch_number} · Start {nextBatch.start_time || "—"}
      </Typography>
      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={6} sm={3}>
          <Typography variant="caption" color="text.secondary">Sorted available</Typography>
          <Typography fontWeight={700}>{nextBatch.bags_sorted_before_start ?? "—"}</Typography>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Typography variant="caption" color="text.secondary">Bags needed</Typography>
          <Typography fontWeight={700}>{nextBatch.bags_needed ?? "—"}</Typography>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Typography variant="caption" color="text.secondary">Sorted surplus</Typography>
          <Typography fontWeight={700} color="success.main">{nextBatch.sorted_surplus ?? 0}</Typography>
        </Grid>
        <Grid item xs={6} sm={3}>
          <Typography variant="caption" color="text.secondary">Folded @ target (now)</Typography>
          <Typography fontWeight={700}>{nextBatch.projected_folded_by_target ?? "—"}</Typography>
        </Grid>
      </Grid>
      <Alert severity="warning" sx={{ mt: 1.5, py: 0.5 }}>
        <Typography variant="body2" fontWeight={600}>{nextBatch.recommendation}</Typography>
        {nextBatch.alternative ? (
          <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>{nextBatch.alternative}</Typography>
        ) : null}
      </Alert>
      {impact ? (
        <Box sx={{ mt: 1.5, p: 1, bgcolor: "#fff", borderRadius: 1, border: "1px solid #bfdbfe" }}>
          <Typography variant="caption" fontWeight={800} color="primary">If recommended change applied</Typography>
          <Typography variant="body2">
            Ready @ target: {impact.ready_by_target_delta >= 0 ? "+" : ""}{impact.ready_by_target_delta}
            {" · "}
            Folded @ target: {impact.folded_by_target_delta >= 0 ? "+" : ""}{impact.folded_by_target_delta}
            {impact.finish_delta_min != null && impact.finish_delta_min !== 0 ? (
              <> · Finish: {Math.abs(impact.finish_delta_min)} min {impact.finish_delta_min < 0 ? "earlier" : "later"}</>
            ) : null}
          </Typography>
        </Box>
      ) : null}
    </Paper>
  );
}

function BatchOverrideControls({ batch, onApply }) {
  const [helper, setHelper] = useState("none");
  const [batchSize, setBatchSize] = useState(batch.apply_defaults?.batch_size || batch.batch_size || 8);
  const [washerFolds, setWasherFolds] = useState(false);
  const [sortPaused, setSortPaused] = useState(false);
  const [scope, setScope] = useState("from_this_batch");

  const apply = () => {
    const fields = {
      ...helperFieldsFromAssignment(helper),
      batch_size: Number(batchSize),
      washer_helps_folding: washerFolds,
      sorting_paused: sortPaused,
    };
    onApply(batch.batch_number, scope, fields);
  };

  return (
    <Stack direction="row" flexWrap="wrap" gap={0.5} alignItems="center" sx={{ mt: 0.75 }}>
      <FormControl size="small" sx={{ minWidth: 130 }}>
        <Select value={helper} onChange={(e) => setHelper(e.target.value)} displayEmpty>
          {HELPER_ASSIGN_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField size="small" type="number" label="Batch size" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} sx={{ width: 90 }} inputProps={{ min: 6, max: 12 }} />
      <FormControlLabel control={<Checkbox size="small" checked={washerFolds} onChange={(e) => setWasherFolds(e.target.checked)} />} label={<Typography variant="caption">Washer→fold</Typography>} />
      <FormControlLabel control={<Checkbox size="small" checked={sortPaused} onChange={(e) => setSortPaused(e.target.checked)} />} label={<Typography variant="caption">Pause sort</Typography>} />
      <FormControl size="small" sx={{ minWidth: 120 }}>
        <Select value={scope} onChange={(e) => setScope(e.target.value)}>
          <MenuItem value="this_batch_only">This batch</MenuItem>
          <MenuItem value="from_this_batch">From here</MenuItem>
        </Select>
      </FormControl>
      <Button size="small" variant="contained" onClick={apply} sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}>Apply</Button>
    </Stack>
  );
}

export function BatchTimelineTable({ rows, onApplyOverride }) {
  if (!rows?.length) return null;
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden" }}>
      <Box sx={{ px: 1.5, py: 1, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
        <Typography variant="subtitle1" fontWeight={800}>Batch timeline</Typography>
        <Typography variant="caption" color="text.secondary">One row per batch — sort → wash → dry → fold pipeline</Typography>
      </Box>
      <TableContainer sx={{ maxHeight: 520 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {["Batch", "Bags", "Size", "Sort", "Wash", "Dry", "Ready", "Fold", "Fold@target", "Bottleneck", "Recommendation", "Actions"].map((h) => (
                <TableCell key={h}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.batch_number} hover>
                <TableCell sx={{ fontWeight: 700 }}>#{row.batch_number}</TableCell>
                <TableCell>{row.bags}</TableCell>
                <TableCell>{row.batch_size}</TableCell>
                <TableCell>{row.sort_start && row.sort_end ? `${row.sort_start}–${row.sort_end}` : "—"}</TableCell>
                <TableCell>{row.wash_start && row.wash_end ? `${row.wash_start}–${row.wash_end}` : "—"}</TableCell>
                <TableCell>{row.dry_start && row.dry_end ? `${row.dry_start}–${row.dry_end}` : "—"}</TableCell>
                <TableCell>{row.ready_time || "—"}</TableCell>
                <TableCell>{row.fold_start && row.fold_end ? `${row.fold_start}–${row.fold_end}` : "—"}</TableCell>
                <TableCell align="right">{row.folded_by_target ?? 0}</TableCell>
                <TableCell>{formatBottleneck(row.bottleneck)}</TableCell>
                <TableCell sx={{ maxWidth: 220 }}>
                  <Typography variant="caption">{row.recommendation || "—"}</Typography>
                </TableCell>
                <TableCell sx={{ minWidth: 360 }}>
                  {onApplyOverride ? (
                    <BatchOverrideControls batch={row} onApply={onApplyOverride} />
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export function ResourceTimelineGrid({ resourceTimeline }) {
  if (!resourceTimeline?.resources?.length) return null;
  const { resources, batch_columns: columns, cells } = resourceTimeline;
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden" }}>
      <Box sx={{ px: 1.5, py: 1, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
        <Typography variant="subtitle1" fontWeight={800}>Resource timeline</Typography>
        <Typography variant="caption" color="text.secondary">Who is doing what during each batch</Typography>
      </Box>
      <TableContainer sx={{ maxHeight: 360 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Resource</TableCell>
              {columns.map((col) => (
                <TableCell key={col} align="center">Batch {col}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {resources.map((res) => (
              <TableRow key={res.id}>
                <TableCell sx={{ fontWeight: 600 }}>{res.label}</TableCell>
                {columns.map((col) => {
                  const activity = cells?.[res.id]?.[String(col)] || "idle";
                  return (
                    <TableCell
                      key={`${res.id}-${col}`}
                      align="center"
                      sx={{ bgcolor: cellBg(activity), fontSize: 11, fontWeight: 600, textTransform: "capitalize" }}
                    >
                      {activity}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ p: 1 }}>
        {Object.entries(activityColor).map(([label, color]) => (
          <Chip key={label} size="small" label={label} sx={{ bgcolor: color, fontSize: 10 }} />
        ))}
      </Stack>
    </Paper>
  );
}

export function EmptyPlanMessage({ hasRun, valid }) {
  if (!hasRun) {
    return <Alert severity="info">Run simulation to generate plan.</Alert>;
  }
  if (!valid) {
    return (
      <Alert severity="error">
        Simulation returned no batch progress — check inputs and run again. All-zero output is treated as a bug.
      </Alert>
    );
  }
  return null;
}
