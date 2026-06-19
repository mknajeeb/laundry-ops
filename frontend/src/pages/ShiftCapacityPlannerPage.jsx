import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Grid,
  Paper,
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
};

const MILESTONE_ORDER = ["8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"];

const STAGE_COLORS = {
  weighing: "#2563eb",
  sorting: "#7c3aed",
  washing: "#0891b2",
  waiting_dryer: "#ea580c",
  drying: "#d97706",
  folding: "#16a34a",
  none: "#64748b",
};

function TopCard({ label, value, sub, variant = "total" }) {
  const style = KPI_VARIANT_STYLES[variant] || KPI_VARIANT_STYLES.total;
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: style.border,
        bgcolor: style.bg,
        minWidth: 0,
        flex: "1 1 160px",
      }}
    >
      <Typography variant="caption" fontWeight={700} sx={{ color: style.accent, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography variant="h5" fontWeight={800} sx={{ lineHeight: 1.2, mt: 0.5, color: "#0f172a" }}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
          {sub}
        </Typography>
      ) : null}
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

function MilestoneTable({ milestones }) {
  const rows = MILESTONE_ORDER.filter((c) => milestones?.[c]).map((c) => ({ clock: c, ...milestones[c] }));
  if (!rows.length) return null;
  return (
    <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
      <Table size="small">
        <TableHead>
          <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
            <TableCell sx={{ fontWeight: 700 }}>Time</TableCell>
            <TableCell align="right">Weighed</TableCell>
            <TableCell align="right">Sorted</TableCell>
            <TableCell align="right">Wash start/done</TableCell>
            <TableCell align="right">Dry start/done</TableCell>
            <TableCell align="right">Ready fold</TableCell>
            <TableCell align="right">Folded</TableCell>
            <TableCell align="right">Wait dryer</TableCell>
            <TableCell>Bottleneck</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.clock} hover>
              <TableCell sx={{ fontWeight: 700 }}>{row.clock}</TableCell>
              <TableCell align="right">{row.bags_weighed}</TableCell>
              <TableCell align="right">{row.bags_sorted}</TableCell>
              <TableCell align="right">
                {row.washer_loads_started}/{row.washer_loads_completed}
              </TableCell>
              <TableCell align="right">
                {row.dryer_loads_started}/{row.dryer_loads_completed}
              </TableCell>
              <TableCell align="right">{row.bags_ready_for_folding}</TableCell>
              <TableCell align="right">{row.bags_folded}</TableCell>
              <TableCell align="right">{row.bags_waiting_for_dryer}</TableCell>
              <TableCell>
                <BottleneckChip stage={row.bottleneck} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function MachineLanes({ lanes }) {
  if (!lanes) return null;
  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>
          Washer lane (first loads)
        </Typography>
        <Stack spacing={1}>
          {(lanes.washers || []).map((w) => (
            <Paper key={w.load_id} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5, borderColor: STAGE_COLORS.washing }}>
              <Typography variant="body2" fontWeight={700}>
                Load #{w.load_id} · {w.bags} bags
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {w.start} → {w.end}
              </Typography>
            </Paper>
          ))}
        </Stack>
      </Grid>
      <Grid item xs={12} md={6}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>
          Dryer lane (first loads)
        </Typography>
        <Stack spacing={1}>
          {(lanes.dryers || []).map((d) => (
            <Paper key={d.load_id} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5, borderColor: STAGE_COLORS.drying }}>
              <Typography variant="body2" fontWeight={700}>
                Load #{d.load_id} · {d.bags} bags
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {d.start} → {d.end}
              </Typography>
            </Paper>
          ))}
        </Stack>
      </Grid>
    </Grid>
  );
}

function StrategyPanel({ strategyKey, data, recommended }) {
  const summary = data?.summary || {};
  const isRec = recommended === strategyKey;
  const label = strategyKey === "continuous_washing" ? "Continuous Washing" : "Dryer Push";
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: isRec ? VEEWASH_DASHBOARD.tealBorder : VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: isRec ? VEEWASH_DASHBOARD.tealLight : "#fff",
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h6" fontWeight={800}>
          {label}
        </Typography>
        {isRec ? <Chip size="small" label="Recommended" color="success" sx={{ fontWeight: 700 }} /> : null}
      </Stack>
      <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
        <Chip label={`First ready: ${summary.first_bags_ready || "—"}`} size="small" />
        <Chip label={`Ready @9: ${summary.ready_by_9_am ?? "—"}`} size="small" />
        <Chip label={`Ready @10: ${summary.ready_by_10_am ?? "—"}`} size="small" />
        <Chip label={`All ready: ${summary.all_ready || "—"}`} size="small" />
        <Chip label={`All folded: ${summary.all_folded || "—"}`} size="small" />
        <BottleneckChip stage={summary.bottleneck} />
      </Stack>
      <MilestoneTable milestones={data?.milestones} />
      <Box sx={{ mt: 2 }}>
        <MachineLanes lanes={data?.machine_lanes} />
      </Box>
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
  const activeStrategy = tab === 0 ? "continuous_washing" : "dryer_push";
  const activeData = result?.strategies?.[activeStrategy];
  const rec = result?.recommendation?.recommended;

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

      <Box sx={{ px: { xs: 2, md: 3 }, pt: 2, maxWidth: 1280, mx: "auto" }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          <Button size="small" component={RouterLink} to="/performance" sx={{ textTransform: "none", fontWeight: 600 }}>
            {t("nav.shiftAnalysis")}
          </Button>
          <Button size="small" component={RouterLink} to="/performance/operations-timeline" sx={{ textTransform: "none", fontWeight: 600 }}>
            {t("nav.operationsTimeline")}
          </Button>
        </Stack>

        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <Paper elevation={0} sx={{ p: 2, borderRadius: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.primaryBlueBorder }}>
              <Typography variant="subtitle1" fontWeight={800} gutterBottom>
                {t("shiftCapacityPlanner.inputs")}
              </Typography>
              <Stack spacing={1.5}>
                <TextField label="Start time" size="small" value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} fullWidth />
                <TextField label="Target time" size="small" value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} fullWidth />
                {numField("bag_count", "Bag count", inputs, onChange, { min: 1 })}
                {numField("avg_lbs_per_bag", "Avg lbs / bag", inputs, onChange, { min: 1 })}
                {numField("washer_count", "Washers", inputs, onChange, { min: 1 })}
                {numField("dryer_count", "Dryers", inputs, onChange, { min: 1 })}
                {numField("washer_capacity_lb", "Washer capacity (lb)", inputs, onChange, { min: 1 })}
                {numField("dryer_capacity_lb", "Dryer capacity (lb)", inputs, onChange, { min: 1 })}
                {numField("wash_cycle_min", "Wash cycle (min)", inputs, onChange, { min: 1 })}
                {numField("dry_cycle_min", "Dry cycle (min)", inputs, onChange, { min: 1 })}
                {numField("weigh_min_per_bag", "Weigh min / bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("sort_min_per_bag", "Sort min / bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("fold_min_per_bag", "Fold min / bag", inputs, onChange, { min: 0.1, step: 0.1 })}
                {numField("folder_count", "Folders", inputs, onChange, { min: 0 })}
                <TextField label="Weighers (blank = auto)" size="small" value={inputs.weigher_count} onChange={(e) => onChange("weigher_count", e.target.value)} fullWidth />
                <TextField label="Sorters (blank = auto)" size="small" value={inputs.sorter_count} onChange={(e) => onChange("sorter_count", e.target.value)} fullWidth />
                <Button variant="contained" startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <PlayArrowIcon />} onClick={runSim} disabled={loading} sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700 }}>
                  {t("shiftCapacityPlanner.run")}
                </Button>
              </Stack>
            </Paper>
          </Grid>

          <Grid item xs={12} md={8}>
            {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

            {result ? (
              <>
                <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 2 }}>
                  <TopCard label="Suggested weighers" value={staffing?.weighers} sub={`Using ${staffing?.using_weighers}`} variant="total" />
                  <TopCard label="Suggested sorters" value={staffing?.sorters} sub={`Using ${staffing?.using_sorters}`} variant="info" />
                  <TopCard label="Suggested folders" value={staffing?.folders} sub={`Using ${staffing?.using_folders}`} variant="completed" />
                  <TopCard
                    label="First bags ready"
                    value={activeData?.summary?.first_bags_ready || "—"}
                    sub={`${activeData?.summary?.ready_by_9_am ?? 0} ready by 9 AM`}
                    variant="pending"
                  />
                  <TopCard
                    label="Est. all folded"
                    value={activeData?.summary?.all_folded || "—"}
                    sub={`Bottleneck: ${activeData?.summary?.bottleneck || "—"}`}
                    variant="snapshot"
                  />
                </Stack>

                {result.recommendation ? (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    <strong>{result.recommendation.label}</strong> — {result.recommendation.reason}
                  </Alert>
                ) : null}

                <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
                  <Tab label="Continuous Washing" />
                  <Tab label="Dryer Push" />
                </Tabs>

                <StrategyPanel strategyKey={activeStrategy} data={activeData} recommended={rec} />

                <Paper elevation={0} sx={{ p: 2, mt: 2, borderRadius: 2, border: "1px solid", borderColor: VEEWASH_DASHBOARD.snapshotBorder, bgcolor: VEEWASH_DASHBOARD.snapshotBg }}>
                  <Typography variant="subtitle1" fontWeight={800} gutterBottom>
                    {t("shiftCapacityPlanner.playbook")}
                  </Typography>
                  <Divider sx={{ mb: 1.5 }} />
                  <Stack spacing={0.75}>
                    {(activeData?.playbook || []).map((line, i) => (
                      <Typography key={i} variant="body2" sx={{ lineHeight: 1.5 }}>
                        {line}
                      </Typography>
                    ))}
                  </Stack>
                </Paper>

                <Box sx={{ mt: 2 }}>
                  <Typography variant="caption" color="text.secondary">
                    {result.inputs?.bags_per_wash_load} bags/load · {result.inputs?.total_wash_loads} wash loads
                    {staffing?.wash_dry_helpers ? ` · +${staffing.wash_dry_helpers} wash/dry helper(s) suggested` : ""}
                  </Typography>
                </Box>
              </>
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
