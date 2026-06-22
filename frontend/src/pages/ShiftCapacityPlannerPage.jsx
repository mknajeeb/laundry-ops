import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Grid,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import { simulateShiftCapacity } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";
import PlannerInputsPanel from "../components/shiftPlanner/PlannerInputsPanel";
import {
  ActionPlanPanel,
  BatchCommandCenter,
  CompactBatchTable,
  DecisionSummaryCards,
  NextBatchDecisionCard,
  QuickScenarioButtons,
  RunningMilestoneTable,
  ScenarioCompareTable,
} from "../components/shiftPlanner/PlannerResults";
import { DEFAULT_INPUTS, PLANNER_TABS, QUICK_SCENARIOS } from "../shiftPlanner/constants";
import {
  applyOperationalStrategy,
  applyScenarioPatch,
  buildBatchOverride,
  buildPayload,
  mergeBatchOverride,
} from "../shiftPlanner/plannerHelpers";

export default function ShiftCapacityPlannerPage() {
  const { t } = useI18n();
  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [mainTab, setMainTab] = useState(0);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const onStrategyChange = useCallback((strategyValue) => {
    setInputs((prev) => ({
      ...applyOperationalStrategy({ ...prev, operational_strategy: strategyValue }, strategyValue),
      operational_strategy: strategyValue,
    }));
  }, []);

  const runSim = useCallback(async (includeScenarios = false) => {
    setLoading(true);
    setError("");
    try {
      const res = await simulateShiftCapacity(buildPayload(inputs, { includeScenarios }));
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.error || err.message || "Simulation failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [inputs]);

  useEffect(() => {
    runSim(false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (mainTab === 2 && result && !(result.operational?.scenario_comparisons?.length)) {
      runSim(true);
    }
  }, [mainTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const operational = result?.operational;
  const pack = operational?.decision_pack || operational;
  const inputsMeta = result?.inputs || {};
  const timeRows = operational?.time_milestone_rows || operational?.active_strategy?.time_milestone_rows || [];
  const batchRows = pack?.batch_command_center || operational?.batch_milestone_rows || [];

  const applyQuickScenario = (scenario) => {
    setInputs((prev) => applyScenarioPatch(prev, scenario.patch));
  };

  const applyBatchOverride = (batchNumber, applyScope, fields) => {
    setInputs((prev) => ({
      ...prev,
      batch_overrides: mergeBatchOverride(
        prev.batch_overrides,
        buildBatchOverride(batchNumber, applyScope, fields),
      ),
    }));
  };

  useEffect(() => {
    if (inputs.batch_overrides?.length) {
      runSim(mainTab === 2);
    }
  }, [inputs.batch_overrides]); // eslint-disable-line react-hooks/exhaustive-deps

  const planPanel = (
    <Paper
      elevation={0}
      sx={{
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        overflow: "hidden",
      }}
    >
      <Box sx={{ px: 1.5, py: 1.25, borderBottom: "1px solid #e2e8f0", bgcolor: "#f8fafc" }}>
        <Typography variant="subtitle1" fontWeight={800}>Shift inputs</Typography>
        <Typography variant="caption" color="text.secondary">
          One panel — no duplicate fields across tabs
        </Typography>
      </Box>
      <Box sx={{ p: 1.5, maxHeight: { lg: "calc(100vh - 220px)" }, overflow: "auto" }}>
        <PlannerInputsPanel inputs={inputs} onChange={onChange} onStrategyChange={onStrategyChange} />
      </Box>
      <Box sx={{ p: 1.5, borderTop: "1px solid #e2e8f0" }}>
        <Button
          variant="contained"
          fullWidth
          startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
          onClick={() => runSim(mainTab === 2)}
          disabled={loading}
          sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, fontWeight: 700 }}
        >
          Run simulation
        </Button>
      </Box>
    </Paper>
  );

  const resultsPanel = result ? (
    <Stack spacing={1.5}>
      <NextBatchDecisionCard decision={pack?.next_batch_decision} />
      <DecisionSummaryCards summary={pack?.decision_summary} inputsMeta={inputsMeta} />
      <ActionPlanPanel
        actions={pack?.action_plan}
        staffing={result?.staffing}
        optimizer={operational?.strategy_optimizer}
      />
      <RunningMilestoneTable rows={timeRows} />
      <CompactBatchTable rows={batchRows} />
      <BatchCommandCenter batches={batchRows} onApplyOverride={applyBatchOverride} />
    </Stack>
  ) : null;

  const comparePanel = (
    <Stack spacing={1.5}>
      <Paper elevation={0} sx={{ p: 1.5, border: "1px solid #e2e8f0", borderRadius: 2 }}>
        <Typography variant="subtitle2" fontWeight={800} gutterBottom>Quick scenarios</Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          Apply a change and re-run — compares against your current setup without duplicating inputs.
        </Typography>
        <QuickScenarioButtons scenarios={QUICK_SCENARIOS} onApply={applyQuickScenario} disabled={loading} />
      </Paper>
      <ScenarioCompareTable rows={operational?.scenario_comparisons} loading={loading && mainTab === 2} />
    </Stack>
  );

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 3 }}>
      <Box sx={{ bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg, color: "#fff", px: { xs: 2, md: 3 }, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <VeeWashLogo height={26} variant="light" />
          <Box>
            <Typography variant="h6" fontWeight={800}>{t("nav.shiftCapacityPlanner")}</Typography>
            <Typography variant="caption" sx={{ opacity: 0.9 }}>
              Operational batch planner — ready, folded, bottleneck, and next-batch staffing decisions
            </Typography>
          </Box>
        </Stack>
      </Box>

      <Box sx={{ px: { xs: 1.5, md: 2.5 }, pt: 1.5, maxWidth: 1500, mx: "auto" }}>
        <Button size="small" component={RouterLink} to="/performance" sx={{ mb: 1.5, textTransform: "none", fontWeight: 600 }}>
          ← {t("nav.shiftAnalysis")}
        </Button>

        {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
        {result?.timing_model?.guidance_only_fields?.length ? (
          <Alert severity="warning" sx={{ mb: 1.5 }}>
            Guidance only — does not change simulation timing yet:{" "}
            {result.timing_model.guidance_only_fields.join(", ")}
          </Alert>
        ) : null}

        <Tabs
          value={mainTab}
          onChange={(_, v) => setMainTab(v)}
          sx={{ mb: 1.5, minHeight: 40, "& .MuiTab-root": { minHeight: 40, textTransform: "none", fontWeight: 600 } }}
        >
          {PLANNER_TABS.map((label) => (
            <Tab key={label} label={label} />
          ))}
        </Tabs>

        {mainTab === 0 ? (
          <Grid container spacing={2}>
            <Grid item xs={12} lg={4}>{planPanel}</Grid>
            <Grid item xs={12} lg={8}>
              {loading && !result ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
                  <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
                </Box>
              ) : result ? (
                <Stack spacing={1.5}>
                  <NextBatchDecisionCard decision={pack?.next_batch_decision} />
                  <DecisionSummaryCards summary={pack?.decision_summary} inputsMeta={inputsMeta} />
                  <ActionPlanPanel
                    actions={pack?.action_plan?.slice(0, 4)}
                    staffing={result?.staffing}
                    optimizer={operational?.strategy_optimizer}
                  />
                </Stack>
              ) : (
                <Alert severity="info">Configure inputs and click Run simulation.</Alert>
              )}
            </Grid>
          </Grid>
        ) : null}

        {mainTab === 1 ? (
          <Grid container spacing={2}>
            <Grid item xs={12} lg={4}>{planPanel}</Grid>
            <Grid item xs={12} lg={8}>
              {loading && !result ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
                  <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
                </Box>
              ) : resultsPanel}
            </Grid>
          </Grid>
        ) : null}

        {mainTab === 2 ? (
          <Grid container spacing={2}>
            <Grid item xs={12} lg={4}>{planPanel}</Grid>
            <Grid item xs={12} lg={8}>{comparePanel}</Grid>
          </Grid>
        ) : null}
      </Box>
    </Box>
  );
}
