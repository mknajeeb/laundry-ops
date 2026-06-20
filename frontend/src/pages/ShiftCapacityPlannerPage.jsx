import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { simulateShiftCapacity } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD, KPI_VARIANT_STYLES } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

const DEFAULT_INPUTS = {
  start_time: "7:00 AM",
  target_time: "12:00 PM",
  bag_count: 50,
  avg_lbs_per_bag: 20,
  orders_using_2_washers: 40,
  orders_using_2_dryers: 40,
  split_input_mode: "count",
  sorter_early_start_min: 0,
  sorter_break_after_bags: 0,
  sorter_break_duration_min: 0,
  washer_break_after_bags: 0,
  washer_break_duration_min: 0,
  washer_count: 4,
  dryer_count: 4,
  wash_cycle_min: 30,
  dry_cycle_min: 45,
  weigh_min_per_bag: 1,
  sort_min_per_bag: 5,
  fold_min_per_bag: 6,
  folder_count: 3,
  weigher_count: "",
  sorter_count: "",
  weighing_handled_by: "dedicated_weigher",
  washing_strategy: "hybrid_recommended",
  batch_size: 8,
  load_washer_min: 3,
  unload_washer_min: 3,
  load_dryer_min: 3,
  unload_dryer_min: 2,
  washer_transfer_min: 5,
};

const WASHING_STRATEGIES = [
  { value: "continuous_washing", label: "Continuous Washing" },
  { value: "batch_washing", label: "Batch Washing" },
  { value: "hybrid_recommended", label: "Hybrid Recommended" },
];

const BATCH_SIZE_OPTIONS = [6, 8, 10, 12];
const MILESTONE_ORDER = ["8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"];
const INPUT_TABS = ["Time & volume", "Split loads", "Staff & ops", "What-if"];
const RESULT_TABS = ["Strategy", "Milestones", "Orders", "Washer lanes", "Dryer lanes", "Utilization"];

const STAGE_COLORS = {
  weighing: "#2563eb",
  sorting: "#7c3aed",
  washing: "#0891b2",
  waiting_dryer: "#ea580c",
  drying: "#d97706",
  folding: "#16a34a",
  none: "#64748b",
  waiting: "#94a3b8",
  ready_for_dryer: "#ea580c",
  ready_to_fold: "#16a34a",
};

const STATUS_COLORS = {
  waiting: "#94a3b8",
  washing: "#0891b2",
  drying: "#d97706",
  ready_for_dryer: "#ea580c",
  ready_to_fold: "#16a34a",
  transferred: "#64748b",
};

function calcLoadTotals(bagCount, orders2) {
  const n = Math.min(Math.max(0, Number(orders2) || 0), bagCount);
  const single = bagCount - n;
  return {
    orders2: n,
    orders1: single,
    washerLoads: n * 2 + single,
    dryerLoads: n * 2 + single,
  };
}

function TopCard({ label, value, sub, variant = "total" }) {
  const style = KPI_VARIANT_STYLES[variant] || KPI_VARIANT_STYLES.total;
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: "2px solid",
        borderColor: style.border,
        bgcolor: style.bg,
        minWidth: 0,
        flex: "1 1 120px",
      }}
    >
      <Typography variant="caption" fontWeight={700} sx={{ color: style.accent, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, mt: 0.25, color: "#0f172a" }}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}

function numField(key, label, inputs, onChange, { min = 0, step = 1, helperText } = {}) {
  return (
    <TextField
      key={key}
      label={label}
      type="number"
      size="small"
      value={inputs[key]}
      onChange={(e) => onChange(key, e.target.value)}
      inputProps={{ min, step }}
      helperText={helperText}
      fullWidth
    />
  );
}

function ResourceUtilizationPanel({ utilization }) {
  if (!utilization?.length) return null;
  return (
    <Stack spacing={1}>
      {utilization.map((row) => (
        <Box key={row.resource}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.25 }}>
            <Typography variant="caption" fontWeight={700} sx={{ textTransform: "capitalize" }}>
              {row.resource.replace(/_/g, " ")}
              {row.is_bottleneck ? (
                <Chip size="small" label="bottleneck" color="error" sx={{ ml: 0.5, height: 18, fontSize: 10 }} />
              ) : null}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {row.utilization_pct}% · {row.idle_minutes}m idle
            </Typography>
          </Stack>
          <LinearProgress
            variant="determinate"
            value={row.utilization_pct}
            sx={{
              height: 6,
              borderRadius: 1,
              bgcolor: "#e2e8f0",
              "& .MuiLinearProgress-bar": {
                bgcolor: row.is_bottleneck ? "#dc2626" : "#0891b2",
              },
            }}
          />
        </Box>
      ))}
    </Stack>
  );
}

function SplitDistributionCard({ splitDist, bagCount, totals }) {
  if (!splitDist && !totals) return null;
  return (
    <Paper elevation={0} sx={{ p: 1.5, borderRadius: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        Load split ({bagCount} orders)
      </Typography>
      <Stack spacing={0.35}>
        {(splitDist?.summary_lines || []).slice(0, 6).map((line) => (
          <Typography key={line} variant="body2" sx={{ fontSize: 13 }}>
            {line}
          </Typography>
        ))}
      </Stack>
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
        <Chip size="small" label={`${totals?.washerLoads ?? splitDist?.washer_loads_total} washer loads`} />
        <Chip size="small" label={`${totals?.dryerLoads ?? splitDist?.dryer_loads_total} dryer loads`} />
      </Stack>
    </Paper>
  );
}

function BottleneckChip({ stage }) {
  const color = STAGE_COLORS[stage] || STAGE_COLORS.none;
  return (
    <Chip
      size="small"
      label={stage || "none"}
      sx={{ bgcolor: `${color}18`, color, fontWeight: 700, textTransform: "capitalize" }}
    />
  );
}

function StatusChip({ status }) {
  const color = STATUS_COLORS[status] || STAGE_COLORS.none;
  return (
    <Chip
      size="small"
      label={(status || "unknown").replace(/_/g, " ")}
      sx={{ bgcolor: `${color}18`, color, fontWeight: 600, textTransform: "capitalize" }}
    />
  );
}

function MilestoneTable({ milestones }) {
  const rows = MILESTONE_ORDER.filter((c) => milestones?.[c]).map((c) => ({ time: c, ...milestones[c] }));
  if (!rows.length) return null;
  return (
    <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
            <TableCell sx={{ fontWeight: 700 }}>Time</TableCell>
            <TableCell align="right">Sorted</TableCell>
            <TableCell align="right">In wash</TableCell>
            <TableCell align="right">In dry</TableCell>
            <TableCell align="right">Folded</TableCell>
            <TableCell>Bottleneck</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.time} hover>
              <TableCell sx={{ fontWeight: 700 }}>{row.time}</TableCell>
              <TableCell align="right">{row.bags_sorted}</TableCell>
              <TableCell align="right">{row.bags_in_washer}</TableCell>
              <TableCell align="right">{row.bags_in_dryer}</TableCell>
              <TableCell align="right">{row.bags_folded}</TableCell>
              <TableCell><BottleneckChip stage={row.bottleneck} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

const PIPELINE_STAGES = [
  { key: "sort", label: "Sort", color: STAGE_COLORS.sorting, timeKey: "sorted_time", detailKey: null },
  { key: "wash", label: "Wash", color: STAGE_COLORS.washing, startKey: "wash_start", endKey: "wash_end", detailKey: "washer" },
  { key: "dry", label: "Dry", color: STAGE_COLORS.drying, startKey: "dry_start", endKey: "dry_end", detailKey: "dryer" },
  { key: "ready", label: "Ready", color: STAGE_COLORS.ready_to_fold, timeKey: "ready_fold", detailKey: null },
];

function stageTimeLabel(row, stage) {
  if (stage.startKey && row[stage.startKey]) {
    const end = row[stage.endKey];
    return end ? `${row[stage.startKey]}–${end}` : row[stage.startKey];
  }
  return row[stage.timeKey] || null;
}

function stageComplete(row, stage) {
  if (stage.startKey) return Boolean(row[stage.startKey]);
  return Boolean(row[stage.timeKey]);
}

function PipelineStageCell({ row, stage, compact }) {
  const done = stageComplete(row, stage);
  const time = stageTimeLabel(row, stage);
  const detail = stage.detailKey ? row[stage.detailKey] : null;
  return (
    <Box
      sx={{
        flex: "1 1 0",
        minWidth: compact ? 72 : 88,
        px: 0.5,
        py: 0.5,
        borderRadius: 1,
        border: "1px solid",
        borderColor: done ? `${stage.color}55` : "#e2e8f0",
        bgcolor: done ? `${stage.color}12` : "#f8fafc",
        opacity: done ? 1 : 0.72,
      }}
    >
      <Typography variant="caption" fontWeight={800} display="block" sx={{ color: stage.color, lineHeight: 1.2, fontSize: 10 }}>
        {stage.label}
      </Typography>
      <Typography variant="caption" display="block" sx={{ fontWeight: done ? 600 : 400, color: done ? "#0f172a" : "#94a3b8", lineHeight: 1.3, fontSize: 11 }}>
        {time || "—"}
      </Typography>
      {detail ? (
        <Typography variant="caption" display="block" color="text.secondary" sx={{ fontSize: 10 }}>
          {detail}
        </Typography>
      ) : null}
    </Box>
  );
}

function OrderPipelineRow({ row, compact }) {
  return (
    <Stack direction="row" alignItems="stretch" spacing={0.25} sx={{ minWidth: compact ? 320 : 380 }}>
      {PIPELINE_STAGES.map((stage, idx) => (
        <Box key={stage.key} sx={{ display: "flex", alignItems: "stretch", flex: 1 }}>
          <PipelineStageCell row={row} stage={stage} compact={compact} />
          {idx < PIPELINE_STAGES.length - 1 ? (
            <Typography
              component="span"
              sx={{ alignSelf: "center", color: "#cbd5e1", fontWeight: 700, px: 0.15, fontSize: 12, userSelect: "none" }}
            >
              →
            </Typography>
          ) : null}
        </Box>
      ))}
    </Stack>
  );
}

function BagAvailabilityForecast({ guidance }) {
  if (!guidance?.next_wash_batch_start && guidance?.additional_bags_by_next_batch == null) return null;
  const additional = guidance.additional_bags_by_next_batch;
  const atFirst = guidance.bags_sorted_at_first_wash ?? guidance.bags_sorted_before_first_wash;
  const byNext = guidance.bags_sorted_by_next_batch;
  const batchSize = guidance.forecast_batch_size ?? guidance.recommended_first_batch_size;
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.25,
        mb: 1,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.tealBorder,
        bgcolor: VEEWASH_DASHBOARD.tealLight,
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        Bag availability forecast
      </Typography>
      <Stack direction="row" flexWrap="wrap" gap={0.75} alignItems="center">
        <Chip
          size="small"
          label={`${atFirst ?? "—"} sorted at 1st wash`}
          sx={{ fontWeight: 600 }}
        />
        <Typography variant="body2" color="text.secondary">→</Typography>
        <Chip
          size="small"
          color={additional > 0 ? "success" : "default"}
          label={
            additional != null
              ? `+${additional} more by next batch (${byNext ?? "—"} total)`
              : "Next batch timing unavailable"
          }
          sx={{ fontWeight: 700 }}
        />
        <Chip
          size="small"
          variant="outlined"
          label={`Next batch wash ${guidance.next_wash_batch_start || "—"} · size ${batchSize}`}
        />
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
        Counts bags that finish sorting before the next batch wash start (order {batchSize + 1}), beyond what was ready at first wash.
      </Typography>
    </Paper>
  );
}

function OrderTimelineTable({ rows, guidance }) {
  if (!rows?.length) return null;
  const preview = rows.slice(0, 25);
  return (
    <Stack spacing={1}>
      <BagAvailabilityForecast guidance={guidance} />
      <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ px: 0.25 }}>
        {PIPELINE_STAGES.map((stage) => (
          <Chip
            key={stage.key}
            size="small"
            label={stage.label}
            sx={{ bgcolor: `${stage.color}18`, color: stage.color, fontWeight: 700, height: 22, fontSize: 11 }}
          />
        ))}
        <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center", ml: 0.5 }}>
          Sort → Wash → Dry → Ready to fold
        </Typography>
      </Stack>
      <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder, maxHeight: 480 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
              <TableCell sx={{ fontWeight: 700, width: 48 }}>#</TableCell>
              <TableCell sx={{ fontWeight: 700, minWidth: 400 }}>Pipeline</TableCell>
              <TableCell sx={{ fontWeight: 700, display: { xs: "none", md: "table-cell" } }}>Sorted</TableCell>
              <TableCell sx={{ fontWeight: 700, display: { xs: "none", lg: "table-cell" } }}>Washer</TableCell>
              <TableCell sx={{ fontWeight: 700, display: { xs: "none", lg: "table-cell" } }}>Wash</TableCell>
              <TableCell sx={{ fontWeight: 700, display: { xs: "none", xl: "table-cell" } }}>Dryer</TableCell>
              <TableCell sx={{ fontWeight: 700, display: { xs: "none", xl: "table-cell" } }}>Ready</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {preview.map((row) => (
              <TableRow key={row.order} hover>
                <TableCell sx={{ fontWeight: 700, verticalAlign: "top" }}>{row.order}</TableCell>
                <TableCell sx={{ py: 0.75, verticalAlign: "top" }}>
                  <OrderPipelineRow row={row} />
                </TableCell>
                <TableCell sx={{ display: { xs: "none", md: "table-cell" }, verticalAlign: "top" }}>{row.sorted_time || "—"}</TableCell>
                <TableCell sx={{ display: { xs: "none", lg: "table-cell" }, verticalAlign: "top" }}>{row.washer || "—"}</TableCell>
                <TableCell sx={{ display: { xs: "none", lg: "table-cell" }, verticalAlign: "top" }}>
                  {row.wash_start ? `${row.wash_start}–${row.wash_end}` : "—"}
                </TableCell>
                <TableCell sx={{ display: { xs: "none", xl: "table-cell" }, verticalAlign: "top" }}>
                  {row.dryer || (row.dry_start ? `${row.dry_start}–${row.dry_end}` : "—")}
                </TableCell>
                <TableCell sx={{ display: { xs: "none", xl: "table-cell" }, verticalAlign: "top" }}>{row.ready_fold || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {rows.length > preview.length ? (
        <Typography variant="caption" color="text.secondary">
          Showing first {preview.length} of {rows.length} orders
        </Typography>
      ) : null}
    </Stack>
  );
}

function TimelineLanes({ washerTimeline, dryerTimeline, compact }) {
  const laneSx = compact ? { maxHeight: 360, overflow: "auto" } : {};
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={12} md={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>Washer lanes</Typography>
        <Stack spacing={1} sx={laneSx}>
          {(washerTimeline || []).map((lane) => (
            <Paper key={`w-${lane.washer_id}`} variant="outlined" sx={{ p: 1, borderRadius: 1 }}>
              <Typography variant="caption" fontWeight={800} color="primary" display="block" sx={{ mb: 0.5 }}>
                Washer {lane.washer_id}
              </Typography>
              {lane.loads.map((load) => (
                <Typography key={load.load_id} variant="caption" display="block" sx={{ lineHeight: 1.5 }}>
                  {load.start}–{load.end} · order {load.bag_start} · {load.pounds} lb
                </Typography>
              ))}
            </Paper>
          ))}
        </Stack>
      </Grid>
      <Grid item xs={12} md={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>Dryer lanes</Typography>
        <Stack spacing={1} sx={laneSx}>
          {(dryerTimeline || []).map((lane) => (
            <Paper key={`d-${lane.dryer_id}`} variant="outlined" sx={{ p: 1, borderRadius: 1 }}>
              <Typography variant="caption" fontWeight={800} color="warning.dark" display="block" sx={{ mb: 0.5 }}>
                Dryer {lane.dryer_id}
              </Typography>
              {lane.loads.map((load) => (
                <Typography key={load.load_id} variant="caption" display="block" sx={{ lineHeight: 1.5 }}>
                  {load.start}–{load.end} · order {load.bag_start ?? load.bag_end} · {load.pounds} lb
                </Typography>
              ))}
            </Paper>
          ))}
        </Stack>
      </Grid>
    </Grid>
  );
}

function StrategyPanel({ recommendation, staffing, operational, opGuidance, inputsMeta }) {
  if (!recommendation) return null;
  const staff = recommendation.suggested_staff || {};
  return (
    <Stack spacing={1.5}>
      <Paper elevation={0} sx={{ p: 1.5, borderRadius: 2, border: "2px solid", borderColor: VEEWASH_DASHBOARD.tealBorder, bgcolor: VEEWASH_DASHBOARD.tealLight }}>
        <Typography variant="subtitle1" fontWeight={800} gutterBottom>
          Recommended: {recommendation.label}
        </Typography>
        <Stack direction="row" flexWrap="wrap" gap={0.5}>
          <Chip size="small" label={`Start ${recommendation.start_time}`} />
          <Chip size="small" label={`Weighers ${staff.weighers ?? staffing?.weighers ?? 0}`} />
          <Chip size="small" label={`Sorters ${staff.sorters ?? staffing?.sorters ?? 0}`} />
          <Chip size="small" label={`Folders ${staff.folders ?? staffing?.folders ?? 0}`} />
          <Chip size="small" label={`1st fold ${recommendation.first_fold_ready || "—"}`} />
          <BottleneckChip stage={recommendation.main_bottleneck} />
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
          {recommendation.reason}
        </Typography>
      </Paper>
      <Paper elevation={0} sx={{ p: 1.5, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>
          Batch guidance · size {operational?.recommended_batch_size ?? "—"}
        </Typography>
        <Stack direction="row" flexWrap="wrap" gap={0.5}>
          <Chip size="small" label={`1st wash ${opGuidance.first_wash_batch_start || "—"}`} />
          <Chip size="small" label={`Unload ${opGuidance.washer_return_to_unload || "—"}`} />
          <Chip size="small" label={`Switch fold ${opGuidance.switch_labor_to_folding || "—"}`} />
          <Chip size="small" label={`${inputsMeta.total_wash_loads} wash / ${inputsMeta.total_dryer_loads} dry loads`} />
        </Stack>
      </Paper>
    </Stack>
  );
}

function InputPanel({ tab, inputs, onChange, previewTotals }) {
  if (tab === 0) {
    return (
      <Stack spacing={1.25}>
        <TextField label="Start time" size="small" value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} fullWidth />
        <TextField label="Target time" size="small" value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} fullWidth />
        {numField("bag_count", "Total orders/bags", inputs, onChange, { min: 1 })}
        {numField("avg_lbs_per_bag", "Avg lb/bag", inputs, onChange, { min: 1 })}
        <Grid container spacing={1}>
          <Grid item xs={6}>{numField("washer_count", "Washers", inputs, onChange, { min: 1 })}</Grid>
          <Grid item xs={6}>{numField("dryer_count", "Dryers", inputs, onChange, { min: 1 })}</Grid>
          <Grid item xs={6}>{numField("wash_cycle_min", "Wash cycle (min)", inputs, onChange, { min: 1 })}</Grid>
          <Grid item xs={6}>{numField("dry_cycle_min", "Dry cycle (min)", inputs, onChange, { min: 1 })}</Grid>
        </Grid>
      </Stack>
    );
  }
  if (tab === 1) {
    const bagCount = Number(inputs.bag_count) || 0;
    const mode = inputs.split_input_mode;
    const pctWash = bagCount ? Math.round((Number(inputs.orders_using_2_washers) / bagCount) * 100) : 0;
    const pctDry = bagCount ? Math.round((Number(inputs.orders_using_2_dryers) / bagCount) * 100) : 0;
    return (
      <Stack spacing={1.25}>
        <FormControl size="small" fullWidth>
          <InputLabel>Input mode</InputLabel>
          <Select label="Input mode" value={mode} onChange={(e) => onChange("split_input_mode", e.target.value)}>
            <MenuItem value="count">Order counts</MenuItem>
            <MenuItem value="pct">Percentages</MenuItem>
          </Select>
        </FormControl>
        {mode === "count" ? (
          <>
            {numField(
              "orders_using_2_washers",
              "Orders using 2 washers",
              inputs,
              onChange,
              { min: 0, helperText: `${previewTotals.orders1Wash} orders use 1 washer → ${previewTotals.washerLoads} washer loads` }
            )}
            {numField(
              "orders_using_2_dryers",
              "Orders using 2 dryers",
              inputs,
              onChange,
              { min: 0, helperText: `${previewTotals.orders1Dry} orders use 1 dryer → ${previewTotals.dryerLoads} dryer loads` }
            )}
          </>
        ) : (
          <>
            {numField(
              "orders_using_2_washers",
              "Orders using 2 washers (%)",
              inputs,
              onChange,
              { min: 0, max: 100, helperText: `≈ ${Math.round(bagCount * pctWash / 100)} orders · ${previewTotals.washerLoads} washer loads` }
            )}
            {numField(
              "orders_using_2_dryers",
              "Orders using 2 dryers (%)",
              inputs,
              onChange,
              { min: 0, max: 100, helperText: `≈ ${Math.round(bagCount * pctDry / 100)} orders · ${previewTotals.dryerLoads} dryer loads` }
            )}
          </>
        )}
        <Alert severity="info" sx={{ py: 0.25, "& .MuiAlert-message": { fontSize: 12 } }}>
          Split is per order: lights+darks may use 2 washers. Dryer split is independent.
        </Alert>
      </Stack>
    );
  }
  if (tab === 2) {
    return (
      <Stack spacing={1.25}>
        <FormControl size="small" fullWidth>
          <InputLabel>Weighing handled by</InputLabel>
          <Select label="Weighing handled by" value={inputs.weighing_handled_by} onChange={(e) => onChange("weighing_handled_by", e.target.value)}>
            <MenuItem value="dedicated_weigher">Dedicated weigher</MenuItem>
            <MenuItem value="sorter">Sorter</MenuItem>
            <MenuItem value="washer">Washer</MenuItem>
          </Select>
        </FormControl>
        <Grid container spacing={1}>
          <Grid item xs={4}>{numField("weigh_min_per_bag", "Weigh min", inputs, onChange, { min: 0.1, step: 0.1 })}</Grid>
          <Grid item xs={4}>{numField("sort_min_per_bag", "Sort min", inputs, onChange, { min: 0.1, step: 0.1 })}</Grid>
          <Grid item xs={4}>{numField("fold_min_per_bag", "Fold min", inputs, onChange, { min: 0.1, step: 0.1 })}</Grid>
        </Grid>
        <Grid container spacing={1}>
          <Grid item xs={4}>{numField("folder_count", "Folders", inputs, onChange, { min: 0 })}</Grid>
          {inputs.weighing_handled_by === "dedicated_weigher" ? (
            <Grid item xs={4}>
              <TextField label="Weighers (auto)" size="small" value={inputs.weigher_count} onChange={(e) => onChange("weigher_count", e.target.value)} fullWidth />
            </Grid>
          ) : null}
          <Grid item xs={4}>
            <TextField label="Sorters (auto)" size="small" value={inputs.sorter_count} onChange={(e) => onChange("sorter_count", e.target.value)} fullWidth />
          </Grid>
        </Grid>
        <FormControl size="small" fullWidth>
          <InputLabel>Washing strategy</InputLabel>
          <Select label="Washing strategy" value={inputs.washing_strategy} onChange={(e) => onChange("washing_strategy", e.target.value)}>
            {WASHING_STRATEGIES.map((s) => (
              <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" fullWidth>
          <InputLabel>Batch size</InputLabel>
          <Select label="Batch size" value={Number(inputs.batch_size)} onChange={(e) => onChange("batch_size", e.target.value)}>
            {BATCH_SIZE_OPTIONS.map((n) => (
              <MenuItem key={n} value={n}>{n} bags</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", "&:before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 40, "& .MuiAccordionSummary-content": { my: 0.5 } }}>
            <Typography variant="caption" fontWeight={700}>Washer person timings</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0 }}>
            <Grid container spacing={1}>
              <Grid item xs={6}>{numField("load_washer_min", "Load washer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("unload_washer_min", "Unload washer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("washer_transfer_min", "Transfer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("load_dryer_min", "Load dryer", inputs, onChange, { min: 0 })}</Grid>
            </Grid>
          </AccordionDetails>
        </Accordion>
      </Stack>
    );
  }
  return (
    <Stack spacing={1.25}>
      {numField("sorter_early_start_min", "Sorter early start (min)", inputs, onChange, { min: 0 })}
      {numField("sorter_break_after_bags", "Sorter break after bags", inputs, onChange, { min: 0 })}
      {numField("sorter_break_duration_min", "Sorter break (min)", inputs, onChange, { min: 0 })}
      {numField("washer_break_after_bags", "Washer break after bags", inputs, onChange, { min: 0 })}
      {numField("washer_break_duration_min", "Washer break (min)", inputs, onChange, { min: 0 })}
    </Stack>
  );
}

export default function ShiftCapacityPlannerPage() {
  const { t } = useI18n();
  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [inputTab, setInputTab] = useState(0);
  const [resultTab, setResultTab] = useState(0);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const bagCount = Number(inputs.bag_count) || 0;
  const previewTotals = useMemo(() => {
    const mode = inputs.split_input_mode;
    let orders2Wash = Number(inputs.orders_using_2_washers) || 0;
    let orders2Dry = Number(inputs.orders_using_2_dryers) || 0;
    if (mode === "pct") {
      orders2Wash = Math.round(bagCount * orders2Wash / 100);
      orders2Dry = Math.round(bagCount * orders2Dry / 100);
    }
    const washTotals = calcLoadTotals(bagCount, orders2Wash);
    const dryTotals = calcLoadTotals(bagCount, orders2Dry);
    return {
      orders2Wash: washTotals.orders2,
      orders1Wash: washTotals.orders1,
      washerLoads: washTotals.washerLoads,
      orders2Dry: dryTotals.orders2,
      orders1Dry: dryTotals.orders1,
      dryerLoads: dryTotals.dryerLoads,
    };
  }, [inputs, bagCount]);

  const payload = useMemo(() => {
    const body = { ...inputs };
    delete body.split_input_mode;
    ["weigher_count", "sorter_count"].forEach((k) => {
      if (body[k] === "" || body[k] == null) delete body[k];
      else body[k] = Number(body[k]);
    });
    const numericKeys = [
      "bag_count", "avg_lbs_per_bag", "sorter_early_start_min", "sorter_break_after_bags",
      "sorter_break_duration_min", "washer_break_after_bags", "washer_break_duration_min",
      "washer_count", "dryer_count", "wash_cycle_min", "dry_cycle_min",
      "weigh_min_per_bag", "sort_min_per_bag", "fold_min_per_bag", "folder_count",
      "batch_size", "load_washer_min", "unload_washer_min", "load_dryer_min",
      "unload_dryer_min", "washer_transfer_min",
    ];
    numericKeys.forEach((k) => { body[k] = Number(body[k]); });

    if (inputs.split_input_mode === "pct") {
      delete body.orders_using_2_washers;
      delete body.orders_using_2_dryers;
      body.orders_using_2_washers_pct = Number(inputs.orders_using_2_washers);
      body.orders_using_2_dryers_pct = Number(inputs.orders_using_2_dryers);
    } else {
      body.orders_using_2_washers = Number(inputs.orders_using_2_washers);
      body.orders_using_2_dryers = Number(inputs.orders_using_2_dryers);
    }
    return body;
  }, [inputs]);

  const runSim = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await simulateShiftCapacity(payload);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message || "Simulation failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [payload]);

  useEffect(() => {
    runSim();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const staffing = result?.staffing;
  const operational = result?.operational;
  const opData = operational?.active_strategy || operational?.strategies?.[inputs.washing_strategy];
  const opGuidance = opData?.guidance || operational?.guidance || {};
  const legacyStrategy = result?.recommendation?.recommended || "continuous_washing";
  const legacyData = result?.strategies?.[legacyStrategy];
  const inputsMeta = result?.inputs || {};
  const splitDist = inputsMeta.split_distribution;
  const resourceUtil = opData?.resource_utilization || result?.resource_utilization || [];

  const stickySummary = result ? (
    <Paper
      elevation={2}
      sx={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        p: 1.25,
        mb: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
      }}
    >
      <Stack direction="row" flexWrap="wrap" gap={1}>
        <TopCard label="Orders" value={inputsMeta.bag_count ?? bagCount} sub={`${previewTotals.washerLoads} wash · ${previewTotals.dryerLoads} dry loads`} variant="total" />
        <TopCard label="Strategy" value={result.recommendation?.label?.split(" ")[0] || "—"} sub={result.recommendation?.main_bottleneck || "—"} variant="info" />
        <TopCard label="1st wash" value={opGuidance.first_wash_batch_start || "—"} sub={`Fold switch ${opGuidance.switch_labor_to_folding || "—"}`} variant="pending" />
        <TopCard
          label="+bags next batch"
          value={opGuidance.additional_bags_by_next_batch != null ? `+${opGuidance.additional_bags_by_next_batch}` : "—"}
          sub={opGuidance.next_wash_batch_start ? `@ ${opGuidance.next_wash_batch_start}` : `${opGuidance.bags_sorted_at_first_wash ?? "—"} at 1st wash`}
          variant="info"
        />
        <TopCard label="Folded @ target" value={legacyData?.final?.bags_folded ?? "—"} sub={`/${inputsMeta.bag_count}`} variant="completed" />
        <TopCard label="Batch" value={operational?.recommended_batch_size ?? "—"} sub={inputs.washing_strategy.replace(/_/g, " ")} variant="snapshot" />
      </Stack>
    </Paper>
  ) : null;

  const resultContent = () => {
    if (!result) return null;
    switch (resultTab) {
      case 0:
        return (
          <StrategyPanel
            recommendation={result.recommendation}
            staffing={staffing}
            operational={operational}
            opGuidance={opGuidance}
            inputsMeta={inputsMeta}
          />
        );
      case 1:
        return (
          <Stack spacing={1}>
            <MilestoneTable milestones={legacyData?.milestones} />
            {(legacyData?.alerts || []).slice(0, 3).map((msg, i) => (
              <Alert key={i} severity="info" sx={{ py: 0.25 }}>{msg}</Alert>
            ))}
            {result.what_if ? (
              <Alert severity="warning" sx={{ py: 0.25 }}>
                What-if Δ folded: {result.what_if.comparison?.delta?.bags_folded ?? 0}
              </Alert>
            ) : null}
          </Stack>
        );
      case 2:
        return (
          <OrderTimelineTable
            rows={opData?.order_timeline || operational?.order_timeline}
            guidance={opGuidance}
          />
        );
      case 3:
        return <TimelineLanes washerTimeline={opData?.washer_timeline || operational?.washer_timeline} dryerTimeline={[]} compact />;
      case 4:
        return <TimelineLanes washerTimeline={[]} dryerTimeline={opData?.dryer_timeline || operational?.dryer_timeline} compact />;
      case 5:
        return <ResourceUtilizationPanel utilization={resourceUtil} />;
      default:
        return null;
    }
  };

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 3 }}>
      <Box sx={{ bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg, color: "#fff", px: { xs: 2, md: 3 }, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <VeeWashLogo height={26} variant="light" />
          <Box>
            <Typography variant="h6" fontWeight={800}>{t("nav.shiftCapacityPlanner")}</Typography>
            <Typography variant="caption" sx={{ opacity: 0.9 }}>{t("shiftCapacityPlanner.subtitle")}</Typography>
          </Box>
        </Stack>
      </Box>

      <Box sx={{ px: { xs: 1.5, md: 2.5 }, pt: 1.5, maxWidth: 1500, mx: "auto" }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 1.5 }}>
          <Button size="small" component={RouterLink} to="/performance" sx={{ textTransform: "none", fontWeight: 600 }}>
            {t("nav.shiftAnalysis")}
          </Button>
        </Stack>

        <Grid container spacing={2} alignItems="flex-start">
          <Grid item xs={12} lg={3.5}>
            <Paper
              elevation={0}
              sx={{
                borderRadius: 2,
                border: "1px solid",
                borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
                display: "flex",
                flexDirection: "column",
                maxHeight: { lg: "calc(100vh - 120px)" },
                position: { lg: "sticky" },
                top: { lg: 12 },
              }}
            >
              <Box sx={{ px: 1.5, pt: 1.5, pb: 0 }}>
                <Typography variant="subtitle2" fontWeight={800}>{t("shiftCapacityPlanner.inputs")}</Typography>
                <Tabs
                  value={inputTab}
                  onChange={(_, v) => setInputTab(v)}
                  variant="scrollable"
                  scrollButtons="auto"
                  sx={{ minHeight: 36, mt: 0.5, "& .MuiTab-root": { minHeight: 36, py: 0.5, fontSize: 12, textTransform: "none" } }}
                >
                  {INPUT_TABS.map((label) => (
                    <Tab key={label} label={label} />
                  ))}
                </Tabs>
              </Box>
              <Box sx={{ px: 1.5, py: 1.25, overflow: "auto", flex: 1 }}>
                <InputPanel tab={inputTab} inputs={inputs} onChange={onChange} previewTotals={previewTotals} />
              </Box>
              <Box sx={{ p: 1.5, borderTop: "1px solid", borderColor: "divider" }}>
                <Button
                  variant="contained"
                  fullWidth
                  startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  onClick={runSim}
                  disabled={loading}
                  sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700 }}
                >
                  {t("shiftCapacityPlanner.run")}
                </Button>
              </Box>
            </Paper>
          </Grid>

          <Grid item xs={12} lg={8.5}>
            {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
            {loading && !result ? (
              <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
                <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
              </Box>
            ) : null}
            {result ? (
              <Box>
                {stickySummary}
                <SplitDistributionCard splitDist={splitDist} bagCount={inputsMeta.bag_count} totals={previewTotals} />
                <Tabs
                  value={resultTab}
                  onChange={(_, v) => setResultTab(v)}
                  variant="scrollable"
                  scrollButtons="auto"
                  sx={{ mt: 1.5, mb: 1, minHeight: 40, "& .MuiTab-root": { minHeight: 40, textTransform: "none", fontWeight: 600 } }}
                >
                  {RESULT_TABS.map((label) => (
                    <Tab key={label} label={label} />
                  ))}
                </Tabs>
                <Box sx={{ minHeight: 320 }}>{resultContent()}</Box>
              </Box>
            ) : null}
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}
