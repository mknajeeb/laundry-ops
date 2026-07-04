import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { simulateShiftCapacity } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";
import {
  BatchTimelineTable,
  EmptyPlanMessage,
  LaborControls,
  NextBatchPanel,
  ResourceTimelineGrid,
  SummaryStrip,
  TopControls,
} from "../components/shiftPlanner/CommandBoard";
import { DEFAULT_INPUTS } from "../shiftPlanner/constants";
import {
  buildBatchOverride,
  buildPayload,
  commandBoardFromResult,
  isCommandBoardValid,
  mergeBatchOverride,
} from "../shiftPlanner/plannerHelpers";

export default function ShiftCapacityPlannerPage() {
  const { t } = useI18n();
  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasRun, setHasRun] = useState(false);
  const debounceRef = useRef(null);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const onToggleFlag = useCallback((flagKey) => {
    setInputs((prev) => {
      const flags = new Set(prev.strategy_flags || []);
      if (flags.has(flagKey)) flags.delete(flagKey);
      else flags.add(flagKey);
      return { ...prev, strategy_flags: [...flags] };
    });
  }, []);

  const runSim = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await simulateShiftCapacity(buildPayload(inputs));
      setResult(res.data);
      setHasRun(true);
    } catch (err) {
      setError(err.response?.data?.error || err.message || "Simulation failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [inputs]);

  useEffect(() => {
    runSim();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!hasRun) return undefined;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSim();
    }, 450);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [inputs.batch_overrides, inputs.strategy_flags]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyBatchOverride = (batchNumber, applyScope, fields) => {
    setInputs((prev) => ({
      ...prev,
      batch_overrides: mergeBatchOverride(
        prev.batch_overrides,
        buildBatchOverride(batchNumber, applyScope, fields),
      ),
    }));
  };

  const board = commandBoardFromResult(result);
  const valid = isCommandBoardValid(board);

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 3 }}>
      <Box sx={{ bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg, color: "#fff", px: { xs: 2, md: 3 }, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <VeeWashLogo height={26} variant="light" />
          <Box>
            <Typography variant="h6" fontWeight={800}>{t("nav.shiftCapacityPlanner")}</Typography>
            <Typography variant="caption" sx={{ opacity: 0.9 }}>
              Batch command board — timeline, resources, and next-batch staffing decisions
            </Typography>
          </Box>
        </Stack>
      </Box>

      <Box sx={{ px: { xs: 1.5, md: 2.5 }, pt: 1.5, maxWidth: 1600, mx: "auto" }}>
        <Button size="small" component={RouterLink} to="/performance" sx={{ mb: 1.5, textTransform: "none", fontWeight: 600 }}>
          ← {t("nav.shiftAnalysis")}
        </Button>

        {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}

        <Stack spacing={1.5}>
          <TopControls inputs={inputs} onChange={onChange} onToggleFlag={onToggleFlag} onRun={runSim} loading={loading} />
          <LaborControls inputs={inputs} onChange={onChange} />

          {loading && !board ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
              <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
            </Box>
          ) : (
            <>
              <EmptyPlanMessage hasRun={hasRun} valid={valid} />
              {valid ? (
                <>
                  <SummaryStrip summary={board.summary} />
                  <NextBatchPanel nextBatch={board.next_batch} />
                  <BatchTimelineTable rows={board.batch_timeline} onApplyOverride={applyBatchOverride} />
                  <ResourceTimelineGrid resourceTimeline={board.resource_timeline} />
                </>
              ) : null}
            </>
          )}
        </Stack>
      </Box>
    </Box>
  );
}
