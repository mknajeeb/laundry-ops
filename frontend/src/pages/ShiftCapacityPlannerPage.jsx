import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
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
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
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
  single_bag_load_pct: 20,
  two_bag_split_pct: 40,
  sorter_early_start_min: 0,
  sorter_break_after_bags: 0,
  sorter_break_duration_min: 0,
  washer_break_after_bags: 0,
  washer_break_duration_min: 0,
  washer_count: 4,
  dryer_count: 4,
  washer_capacity_lb: 50,
  dryer_capacity_lb: 50,
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

function TopCard({ label, value, sub, variant = "total" }) {
  const style = KPI_VARIANT_STYLES[variant] || KPI_VARIANT_STYLES.total;
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "2px solid",
        borderColor: style.border,
        bgcolor: style.bg,
        minWidth: 0,
        flex: "1 1 140px",
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

function ResourceUtilizationPanel({ utilization }) {
  if (!utilization?.length) return null;
  return (
    <Paper elevation={0} sx={{ p: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        Resource utilization
      </Typography>
      <Stack spacing={1}>
        {utilization.map((row) => (
          <Box key={row.resource}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.25 }}>
              <Typography variant="caption" fontWeight={700} sx={{ textTransform: "capitalize" }}>
                {row.resource.replace(/_/g, " ")}
                {row.is_bottleneck ? (
                  <Chip size="small" label="bottleneck" color="error" sx={{ ml: 0.5, height: 18, fontSize: 10 }} />
                ) : null}
                {row.has_excess_idle ? (
                  <Chip size="small" label="idle" color="info" sx={{ ml: 0.5, height: 18, fontSize: 10 }} />
                ) : null}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {row.utilization_pct}% busy · {row.idle_minutes}m idle
              </Typography>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={row.utilization_pct}
              sx={{
                height: 8,
                borderRadius: 1,
                bgcolor: "#e2e8f0",
                "& .MuiLinearProgress-bar": {
                  bgcolor: row.is_bottleneck ? "#dc2626" : row.has_excess_idle ? "#94a3b8" : "#0891b2",
                },
              }}
            />
          </Box>
        ))}
      </Stack>
    </Paper>
  );
}

function SplitDistributionCard({ splitDist, bagCount }) {
  if (!splitDist) return null;
  return (
    <Paper
      elevation={0}
      sx={{ p: 2, borderRadius: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}
    >
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        Load split distribution ({bagCount} orders)
      </Typography>
      <Stack spacing={0.5}>
        {(splitDist.summary_lines || []).map((line) => (
          <Typography key={line} variant="body2">
            {line}
          </Typography>
        ))}
      </Stack>
      <Stack direction="row" flexWrap="wrap" gap={0.75} sx={{ mt: 1 }}>
        <Chip size="small" label={`${splitDist.total_wash_loads} wash loads`} />
        <Chip size="small" label={`${splitDist.single_loads} single`} />
        <Chip size="small" label={`${splitDist.two_bag_split_loads} × 2-bag split`} />
        <Chip size="small" label={`${splitDist.multi_bag_loads} capacity-packed`} />
      </Stack>
    </Paper>
  );
}

function WhatIfComparison({ whatIf }) {
  if (!whatIf?.comparison) return null;
  const { baseline, scenario, delta } = whatIf.comparison;
  return (
    <Paper elevation={0} sx={{ p: 2, border: "2px solid", borderColor: "#f59e0b", bgcolor: "#fffbeb" }}>
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        What-if vs baseline
      </Typography>
      <Grid container spacing={1.5}>
        <Grid item xs={12} sm={4}>
          <TopCard label="Baseline folded" value={baseline.bags_folded} sub={`Bottleneck: ${baseline.bottleneck || "—"}`} variant="snapshot" />
        </Grid>
        <Grid item xs={12} sm={4}>
          <TopCard label="Scenario folded" value={scenario.bags_folded} sub={`Bottleneck: ${scenario.bottleneck || "—"}`} variant="pending" />
        </Grid>
        <Grid item xs={12} sm={4}>
          <TopCard
            label="Delta"
            value={delta.bags_folded >= 0 ? `+${delta.bags_folded}` : delta.bags_folded}
            sub={[delta.first_wash_start, delta.switch_to_folding].filter(Boolean).join(" · ") || "—"}
            variant={delta.bags_folded >= 0 ? "completed" : "total"}
          />
        </Grid>
      </Grid>
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
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
            <TableCell sx={{ fontWeight: 700 }}>Time</TableCell>
            <TableCell align="right">Weighed</TableCell>
            <TableCell align="right">Sorted</TableCell>
            <TableCell align="right">In washer</TableCell>
            <TableCell align="right">Washed</TableCell>
            <TableCell align="right">In dryer</TableCell>
            <TableCell align="right">Dried</TableCell>
            <TableCell align="right">Ready fold</TableCell>
            <TableCell align="right">Folded</TableCell>
            <TableCell>Bottleneck</TableCell>
            <TableCell>Action</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.time} hover>
              <TableCell sx={{ fontWeight: 700 }}>{row.time}</TableCell>
              <TableCell align="right">{row.bags_weighed}</TableCell>
              <TableCell align="right">{row.bags_sorted}</TableCell>
              <TableCell align="right">{row.bags_in_washer}</TableCell>
              <TableCell align="right">{row.bags_washed_complete}</TableCell>
              <TableCell align="right">{row.bags_in_dryer}</TableCell>
              <TableCell align="right">{row.bags_dried_complete}</TableCell>
              <TableCell align="right">{row.bags_ready_for_folding}</TableCell>
              <TableCell align="right">{row.bags_folded}</TableCell>
              <TableCell>
                <BottleneckChip stage={row.bottleneck} />
              </TableCell>
              <TableCell>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  {row.action_needed}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function OperationalBatchCard({ operational }) {
  if (!operational) return null;
  const guidance = operational.guidance || {};
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
      }}
    >
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Recommended batch: {operational.recommended_batch_size} bags
      </Typography>
      <Stack direction="row" flexWrap="wrap" gap={0.75}>
        <Chip size="small" label={`1st wash ${guidance.first_wash_batch_start || "—"}`} />
        <Chip size="small" label={`Return unload ${guidance.washer_return_to_unload || "—"}`} />
        <Chip size="small" label={`Sort before wash ${guidance.bags_sorted_before_first_wash ?? "—"}`} />
        <Chip
          size="small"
          label={guidance.sorting_continues_while_washing ? "Sort while washing" : "Batch sort only"}
          color={guidance.sorting_continues_while_washing ? "success" : "warning"}
        />
        <Chip
          size="small"
          label={guidance.washer_pauses_for_dryer_moves ? "Washer pauses for moves" : "No wash pause"}
        />
        <Chip size="small" label={`Switch to fold ${guidance.switch_labor_to_folding || "—"}`} />
      </Stack>
    </Paper>
  );
}

function NextActionTimeline({ actions }) {
  if (!actions?.length) return null;
  return (
    <Paper elevation={0} sx={{ p: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        Next actions
      </Typography>
      <Stack spacing={0.75}>
        {actions.map((block, i) => (
          <Box
            key={`${block.start}-${block.action}-${i}`}
            sx={{
              p: 1,
              borderRadius: 1,
              borderLeft: "4px solid",
              borderColor: STAGE_COLORS[block.category] || STAGE_COLORS.none,
              bgcolor: "#fff",
            }}
          >
            <Typography variant="body2" fontWeight={700}>
              {block.start} – {block.end}
            </Typography>
            <Typography variant="body2">{block.action}</Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  );
}

function OrderTimelineTable({ rows }) {
  if (!rows?.length) return null;
  const preview = rows.slice(0, 20);
  return (
    <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
            <TableCell sx={{ fontWeight: 700 }}>Order</TableCell>
            <TableCell>Sorted</TableCell>
            <TableCell>Washer</TableCell>
            <TableCell>Wash start</TableCell>
            <TableCell>Wash end</TableCell>
            <TableCell>Dryer</TableCell>
            <TableCell>Dry start</TableCell>
            <TableCell>Dry end</TableCell>
            <TableCell>Ready fold</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {preview.map((row) => (
            <TableRow key={row.order} hover>
              <TableCell sx={{ fontWeight: 700 }}>{row.order}</TableCell>
              <TableCell>{row.sorted_time || "—"}</TableCell>
              <TableCell>{row.washer || "—"}</TableCell>
              <TableCell>{row.wash_start || "—"}</TableCell>
              <TableCell>{row.wash_end || "—"}</TableCell>
              <TableCell>{row.dryer || "—"}</TableCell>
              <TableCell>{row.dry_start || "—"}</TableCell>
              <TableCell>{row.dry_end || "—"}</TableCell>
              <TableCell>{row.ready_fold || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length > preview.length ? (
        <Typography variant="caption" color="text.secondary" sx={{ p: 1, display: "block" }}>
          Showing {preview.length} of {rows.length} orders
        </Typography>
      ) : null}
    </TableContainer>
  );
}

function TimelineLanes({ washerTimeline, dryerTimeline }) {
  return (
    <Grid container spacing={2}>
      <Grid item xs={12} lg={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>
          Washer lanes
        </Typography>
        <Stack spacing={1.5}>
          {(washerTimeline || []).map((lane) => (
            <Paper key={`w-${lane.washer_id}`} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5 }}>
              <Typography variant="caption" fontWeight={800} color="primary" display="block" sx={{ mb: 0.75 }}>
                Washer {lane.washer_id}
              </Typography>
              <Stack spacing={0.75}>
                {lane.loads.map((load) => (
                  <Box
                    key={load.load_id}
                    sx={{
                      p: 1,
                      borderRadius: 1,
                      border: "1px solid",
                      borderColor: STAGE_COLORS.washing,
                      bgcolor: `${STAGE_COLORS.washing}08`,
                    }}
                  >
                    <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={0.5}>
                      <Typography variant="body2" fontWeight={700}>
                        {load.start} → {load.end}
                      </Typography>
                      {load.status ? <StatusChip status={load.status} /> : null}
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      Bags {load.bag_start}–{load.bag_end} · {load.pounds} lb · {load.bags} bags
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Grid>
      <Grid item xs={12} lg={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>
          Dryer lanes
        </Typography>
        <Stack spacing={1.5}>
          {(dryerTimeline || []).map((lane) => (
            <Paper key={`d-${lane.dryer_id}`} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5 }}>
              <Typography variant="caption" fontWeight={800} color="warning.dark" display="block" sx={{ mb: 0.75 }}>
                Dryer {lane.dryer_id}
              </Typography>
              <Stack spacing={0.75}>
                {lane.loads.map((load) => (
                  <Box
                    key={load.load_id}
                    sx={{
                      p: 1,
                      borderRadius: 1,
                      border: "1px solid",
                      borderColor: STAGE_COLORS.drying,
                      bgcolor: `${STAGE_COLORS.drying}08`,
                    }}
                  >
                    <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={0.5}>
                      <Typography variant="body2" fontWeight={700}>
                        {load.start} → {load.end}
                      </Typography>
                      {load.status ? <StatusChip status={load.status} /> : null}
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      Bags {load.bag_start}–{load.bag_end} · {load.pounds} lb · {load.bags} bags
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Grid>
    </Grid>
  );
}

function StrategyCard({ recommendation, staffing }) {
  if (!recommendation) return null;
  const staff = recommendation.suggested_staff || {};
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        mb: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: VEEWASH_DASHBOARD.tealBorder,
        bgcolor: VEEWASH_DASHBOARD.tealLight,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={800}>
          Recommended: {recommendation.label}
        </Typography>
        <Chip size="small" label="Best fit" color="success" sx={{ fontWeight: 700 }} />
      </Stack>
      <Stack direction="row" flexWrap="wrap" gap={0.75}>
        <Chip size="small" label={`Start ${recommendation.start_time}`} />
        <Chip size="small" label={`Weighers ${staff.weighers ?? staffing?.weighers ?? 0}`} />
        <Chip size="small" label={`Sorters ${staff.sorters ?? staffing?.sorters ?? 0}`} />
        <Chip size="small" label={`Folders ${staff.folders ?? staffing?.folders ?? 0}`} />
        <Chip size="small" label={`Washers ${staff.washers ?? "—"}`} />
        <Chip size="small" label={`Dryers ${staff.dryers ?? "—"}`} />
        <Chip size="small" label={`1st fold-ready ${recommendation.first_fold_ready || "—"}`} />
        <Chip size="small" label={`All washed ${recommendation.all_washing_done || "—"}`} />
        <Chip size="small" label={`All dried ${recommendation.all_drying_done || "—"}`} />
        <Chip size="small" label={`All folded ${recommendation.all_folding_done || "—"}`} />
        <BottleneckChip stage={recommendation.main_bottleneck} />
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
        {recommendation.reason}
      </Typography>
    </Paper>
  );
}

function numField(key, label, inputs, onChange, { min = 0, step = 1 } = {}) {
  return (
    <TextField
      key={key}
      label={label}
      type="number"
      size="small"
      value={inputs[key]}
      onChange={(e) => onChange(key, e.target.value)}
      inputProps={{ min, step }}
      fullWidth
    />
  );
}

export default function ShiftCapacityPlannerPage() {
  const { t } = useI18n();
  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const [legacyTab, setLegacyTab] = useState(0);
  const [whatIfOpen, setWhatIfOpen] = useState(false);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const payload = useMemo(() => {
    const body = { ...inputs };
    ["weigher_count", "sorter_count"].forEach((k) => {
      if (body[k] === "" || body[k] == null) delete body[k];
      else body[k] = Number(body[k]);
    });
    [
      "bag_count",
      "avg_lbs_per_bag",
      "single_bag_load_pct",
      "two_bag_split_pct",
      "sorter_early_start_min",
      "sorter_break_after_bags",
      "sorter_break_duration_min",
      "washer_break_after_bags",
      "washer_break_duration_min",
      "washer_count",
      "dryer_count",
      "washer_capacity_lb",
      "dryer_capacity_lb",
      "wash_cycle_min",
      "dry_cycle_min",
      "weigh_min_per_bag",
      "sort_min_per_bag",
      "fold_min_per_bag",
      "folder_count",
      "batch_size",
      "load_washer_min",
      "unload_washer_min",
      "load_dryer_min",
      "unload_dryer_min",
      "washer_transfer_min",
    ].forEach((k) => {
      body[k] = Number(body[k]);
    });
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
  const opStrategyKeys = ["continuous_washing", "batch_washing", "hybrid_recommended"];
  const opStrategyKey = opStrategyKeys[tab] || "hybrid_recommended";
  const opData = operational?.strategies?.[opStrategyKey] || operational?.active_strategy;
  const opGuidance = opData?.guidance || operational?.guidance || {};
  const legacyStrategy = legacyTab === 0 ? "continuous_washing" : "dryer_push";
  const legacyData = result?.strategies?.[legacyStrategy];
  const legacySummary = legacyData?.summary || {};
  const inputsMeta = result?.inputs || {};
  const splitDist = inputsMeta.split_distribution;
  const resourceUtil = opData?.resource_utilization || result?.resource_utilization || [];

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 4 }}>
      <Box sx={{ bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg, color: "#fff", px: { xs: 2, md: 3 }, py: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <VeeWashLogo height={28} variant="light" />
          <Box>
            <Typography variant="h5" fontWeight={800}>
              {t("nav.shiftCapacityPlanner")}
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.9 }}>
              {t("shiftCapacityPlanner.subtitle")}
            </Typography>
          </Box>
        </Stack>
      </Box>

      <Box sx={{ px: { xs: 2, md: 3 }, pt: 2, maxWidth: 1400, mx: "auto" }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Button size="small" component={RouterLink} to="/performance" sx={{ textTransform: "none", fontWeight: 600 }}>
            {t("nav.shiftAnalysis")}
          </Button>
          <Button size="small" component={RouterLink} to="/performance/operations-timeline" sx={{ textTransform: "none", fontWeight: 600 }}>
            {t("nav.operationsTimeline")}
          </Button>
        </Stack>

        <Grid container spacing={2}>
          <Grid item xs={12} md={3}>
            <Paper elevation={0} sx={{ p: 2, borderRadius: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder, position: "sticky", top: 16 }}>
              <Typography variant="subtitle1" fontWeight={800} gutterBottom>
                {t("shiftCapacityPlanner.inputs")}
              </Typography>
              <Stack spacing={1.25}>
                <TextField label="Start time" size="small" value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} fullWidth />
                <TextField label="Target time" size="small" value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} fullWidth />
                {numField("bag_count", "Bag count", inputs, onChange, { min: 1 })}
                {numField("avg_lbs_per_bag", "Avg lb/bag", inputs, onChange, { min: 1 })}
                <Typography variant="caption" fontWeight={700} color="text.secondary">
                  Load split %
                </Typography>
                {numField("single_bag_load_pct", "Single-bag load %", inputs, onChange, { min: 0, max: 100 })}
                {numField("two_bag_split_pct", "2-bag split load %", inputs, onChange, { min: 0, max: 100 })}
                <Typography variant="caption" color="text.secondary">
                  Remainder → capacity-packed loads
                </Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel>Weighing handled by</InputLabel>
                  <Select
                    label="Weighing handled by"
                    value={inputs.weighing_handled_by}
                    onChange={(e) => onChange("weighing_handled_by", e.target.value)}
                  >
                    <MenuItem value="dedicated_weigher">Dedicated weigher</MenuItem>
                    <MenuItem value="sorter">Sorter</MenuItem>
                    <MenuItem value="washer">Washer</MenuItem>
                  </Select>
                </FormControl>
                {numField("washer_count", "Washers", inputs, onChange, { min: 1 })}
                {numField("dryer_count", "Dryers", inputs, onChange, { min: 1 })}
                {numField("washer_capacity_lb", "Washer cap (lb)", inputs, onChange, { min: 1 })}
                {numField("dryer_capacity_lb", "Dryer cap (lb)", inputs, onChange, { min: 1 })}
                {numField("wash_cycle_min", "Wash cycle (min)", inputs, onChange, { min: 1 })}
                {numField("dry_cycle_min", "Dry cycle (min)", inputs, onChange, { min: 1 })}
                {numField("weigh_min_per_bag", "Weigh min/bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("sort_min_per_bag", "Sort min/bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("fold_min_per_bag", "Fold min/bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("folder_count", "Folders", inputs, onChange, { min: 0 })}
                {inputs.weighing_handled_by === "dedicated_weigher" ? (
                  <TextField label="Weighers (blank=auto)" size="small" value={inputs.weigher_count} onChange={(e) => onChange("weigher_count", e.target.value)} fullWidth />
                ) : null}
                <TextField label="Sorters (blank=auto)" size="small" value={inputs.sorter_count} onChange={(e) => onChange("sorter_count", e.target.value)} fullWidth />
                <Typography variant="caption" fontWeight={700} color="text.secondary">
                  Operational simulation
                </Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel>Washing strategy</InputLabel>
                  <Select
                    label="Washing strategy"
                    value={inputs.washing_strategy}
                    onChange={(e) => onChange("washing_strategy", e.target.value)}
                  >
                    {WASHING_STRATEGIES.map((s) => (
                      <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" fullWidth>
                  <InputLabel>Batch size</InputLabel>
                  <Select
                    label="Batch size"
                    value={Number(inputs.batch_size)}
                    onChange={(e) => onChange("batch_size", e.target.value)}
                  >
                    {BATCH_SIZE_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>{n} bags</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                {numField("load_washer_min", "Load washer (min)", inputs, onChange, { min: 0 })}
                {numField("unload_washer_min", "Unload washer (min)", inputs, onChange, { min: 0 })}
                {numField("washer_transfer_min", "Transfer/load (min)", inputs, onChange, { min: 0 })}
                {numField("load_dryer_min", "Load dryer (min)", inputs, onChange, { min: 0 })}
                {numField("unload_dryer_min", "Unload dryer (min)", inputs, onChange, { min: 0 })}
                <Button
                  size="small"
                  onClick={() => setWhatIfOpen((v) => !v)}
                  endIcon={whatIfOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                  sx={{ justifyContent: "space-between", fontWeight: 700, textTransform: "none" }}
                >
                  What-if scenarios
                </Button>
                <Collapse in={whatIfOpen}>
                  <Stack spacing={1.25}>
                    {numField("sorter_early_start_min", "Sorter early start (min)", inputs, onChange, { min: 0 })}
                    {numField("sorter_break_after_bags", "Sorter break after bags", inputs, onChange, { min: 0 })}
                    {numField("sorter_break_duration_min", "Sorter break (min)", inputs, onChange, { min: 0 })}
                    {numField("washer_break_after_bags", "Washer break after bags", inputs, onChange, { min: 0 })}
                    {numField("washer_break_duration_min", "Washer break (min)", inputs, onChange, { min: 0 })}
                  </Stack>
                </Collapse>
                <Button variant="contained" startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <PlayArrowIcon />} onClick={runSim} disabled={loading} sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700 }}>
                  {t("shiftCapacityPlanner.run")}
                </Button>
              </Stack>
            </Paper>
          </Grid>

          <Grid item xs={12} md={9}>
            {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

            {result ? (
              <Stack spacing={2}>
                <SplitDistributionCard splitDist={splitDist} bagCount={inputsMeta.bag_count} />
                <WhatIfComparison whatIf={result.what_if} />

                <OperationalBatchCard operational={operational} />

                <Stack direction="row" flexWrap="wrap" gap={1}>
                  <TopCard label="Batch size" value={operational?.recommended_batch_size ?? "—"} sub={`Strategy ${inputs.washing_strategy}`} variant="total" />
                  <TopCard label="1st wash" value={opGuidance.first_wash_batch_start || "—"} sub={`Unload ${opGuidance.washer_return_to_unload || "—"}`} variant="pending" />
                  <TopCard label="Sort before wash" value={opGuidance.bags_sorted_before_first_wash ?? "—"} sub={opGuidance.sorting_continues_while_washing ? "Sort continues" : "Batch sort"} variant="info" />
                  <TopCard label="Switch to fold" value={opGuidance.switch_labor_to_folding || "—"} sub={`Folded ${opData?.summary?.bags_folded ?? "—"}`} variant="completed" />
                  <TopCard label="Wash loads" value={inputsMeta.total_wash_loads} sub={`Avg ${inputsMeta.avg_bags_per_wash_load} bags/load`} variant="snapshot" />
                </Stack>

                <Tabs value={tab} onChange={(_, v) => setTab(v)}>
                  <Tab label="Continuous" />
                  <Tab label="Batch" />
                  <Tab label="Hybrid" />
                </Tabs>

                <NextActionTimeline actions={opData?.next_actions || operational?.next_actions} />

                {(opData?.bottleneck_alerts || operational?.bottleneck_alerts || []).map((msg, i) => (
                  <Alert key={i} severity={i === 0 ? "warning" : "info"} sx={{ py: 0.25 }}>
                    {msg}
                  </Alert>
                ))}

                <ResourceUtilizationPanel utilization={resourceUtil} />

                <Typography variant="subtitle2" fontWeight={800}>
                  Order timeline
                </Typography>
                <OrderTimelineTable rows={opData?.order_timeline || operational?.order_timeline} />

                <TimelineLanes
                  washerTimeline={opData?.washer_timeline || operational?.washer_timeline}
                  dryerTimeline={opData?.dryer_timeline || operational?.dryer_timeline}
                />

                <StrategyCard recommendation={result.recommendation} staffing={staffing} />

                <Typography variant="subtitle2" fontWeight={800}>
                  Legacy milestone view
                </Typography>
                <Tabs value={legacyTab} onChange={(_, v) => setLegacyTab(v)}>
                  <Tab label="Continuous Washing" />
                  <Tab label="Dryer Push" />
                </Tabs>
                <MilestoneTable milestones={legacyData?.milestones} />
                {(legacyData?.alerts || []).map((msg, i) => (
                  <Alert key={`legacy-${i}`} severity="info" sx={{ py: 0.25 }}>{msg}</Alert>
                ))}
              </Stack>
            ) : loading ? (
              <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
                <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
              </Box>
            ) : null}
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}
