import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import { simulateShiftCapacity } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";
import {
  AddStaffDialogFields,
  AvailabilitySection,
  BagTableAndTimelinesSection,
  EmployeesSection,
  OrdersSection,
  ProcessingTimesSection,
  ReadyByBatchSection,
  RecommendationsSection,
  ResultsSummarySection,
  ShiftSetupSection,
  StrategySection,
} from "../components/shiftPlanner/DesPlannerBoard";
import EditBatchDialog from "../components/shiftPlanner/EditBatchDialog";
import ManagementPlannerBoard from "../components/shiftPlanner/ManagementPlannerBoard";
import { DEFAULT_INPUTS } from "../shiftPlanner/constants";
import {
  buildPayload,
  newEmployee,
  resetBatchOverrides,
  summaryDelta,
  upsertBatchOverride,
} from "../shiftPlanner/plannerHelpers";

/**
 * Production senior-management planner = Management experience only.
 * Advanced DES planner remains available via ?advanced=1 (no UI toggle).
 */
export default function ShiftCapacityPlannerPage() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const showAdvanced = searchParams.get("advanced") === "1";

  const [inputs, setInputs] = useState(DEFAULT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasRun, setHasRun] = useState(false);
  const [dismissed, setDismissed] = useState([]);
  const [undoStack, setUndoStack] = useState([]);
  const [impact, setImpact] = useState(null);
  const [addStaffOpen, setAddStaffOpen] = useState(false);
  const [editBatch, setEditBatch] = useState(null);
  const [staffDraft, setStaffDraft] = useState(() => ({
    ...newEmployee("washer", "8:30 AM"),
    sim_mode: "continue_from_time",
  }));

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const runSim = useCallback(async (overrideInputs) => {
    const payloadInputs = overrideInputs || inputs;
    setLoading(true);
    setError("");
    try {
      const res = await simulateShiftCapacity(buildPayload(payloadInputs));
      setResult(res.data);
      setHasRun(true);
      if (res.data?.simulation_valid === false && (res.data?.validation_errors || []).length) {
        setError((res.data.validation_errors || []).join(" · "));
      }
      return res.data;
    } catch (err) {
      setError(err.response?.data?.error || err.message || "Simulation failed");
      setResult(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [inputs]);

  useEffect(() => {
    if (!showAdvanced) return;
    runSim();
  }, [showAdvanced]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyInputsAndRerun = async (nextInputs) => {
    setUndoStack((stack) => [
      ...stack,
      { inputs: structuredClone(inputs), result, impact },
    ]);
    setInputs(nextInputs);
    const beforeSummary = result?.summary;
    const after = await runSim(nextInputs);
    if (beforeSummary && after?.summary) {
      setImpact(summaryDelta(beforeSummary, after.summary));
    }
    return after;
  };

  const onAddStaff = (emp) => {
    setInputs((prev) => ({ ...prev, employees: [...(prev.employees || []), emp] }));
  };

  const saveAddStaff = async () => {
    const emp = {
      ...staffDraft,
      id: staffDraft.id || `E-NEW-${Date.now()}`,
      active: true,
    };
    const next = {
      ...inputs,
      employees: [...(inputs.employees || []), emp],
      sim_mode: staffDraft.sim_mode || "continue_from_time",
      continue_from_time: staffDraft.start_time,
    };
    setAddStaffOpen(false);
    await applyInputsAndRerun(next);
  };

  const onApplyRecommendation = async (patch, label, dismissId) => {
    if (label === "dismiss" && dismissId) {
      setDismissed((d) => [...d, dismissId]);
      return;
    }
    if (!patch) return;
    const next = { ...inputs, apply_action: patch };
    Object.entries(patch).forEach(([k, v]) => {
      if (k !== "staffing_event" && k !== "batch_override" && k !== "reset_override") next[k] = v;
    });
    await applyInputsAndRerun(next);
    setInputs((prev) => {
      const cleaned = { ...prev };
      delete cleaned.apply_action;
      return cleaned;
    });
  };

  const onApplyBatchOverride = async (overridePatch) => {
    setEditBatch(null);
    const next = {
      ...inputs,
      batch_overrides: upsertBatchOverride(inputs.batch_overrides, overridePatch),
    };
    await applyInputsAndRerun(next);
  };

  const onResetBatchOverride = async (batchNumber) => {
    setEditBatch(null);
    const next = {
      ...inputs,
      batch_overrides: resetBatchOverrides(inputs.batch_overrides, batchNumber),
    };
    await applyInputsAndRerun(next);
  };

  const onUndo = async () => {
    const prev = undoStack[undoStack.length - 1];
    if (!prev) return;
    setUndoStack((stack) => stack.slice(0, -1));
    setInputs(prev.inputs);
    setImpact(null);
    setError("");
    await runSim(prev.inputs);
  };

  const recommendations = (result?.recommendations || []).filter((r) => !dismissed.includes(r.id));
  const allBagIds = (result?.bag_rows || []).map((r) => r.bag_id);

  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 3 }}>
      <Box sx={{ bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg, color: "#fff", px: { xs: 2, md: 3 }, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <VeeWashLogo height={26} variant="light" />
          <Box>
            <Typography variant="h6" fontWeight={800}>{t("nav.shiftCapacityPlanner")}</Typography>
            <Typography variant="caption" sx={{ opacity: 0.9 }}>
              {showAdvanced
                ? "Advanced DES planner (internal)"
                : "Staff the shift and see what happens"}
            </Typography>
          </Box>
        </Stack>
      </Box>

      <Box sx={{ px: { xs: 1.5, md: 2.5 }, pt: 1.5, maxWidth: showAdvanced ? 1600 : 1100, mx: "auto" }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5, flexWrap: "wrap" }}>
          <Button size="small" component={RouterLink} to="/management/rinse-wf" sx={{ textTransform: "none", fontWeight: 600 }}>
            ← Management
          </Button>
          {showAdvanced && undoStack.length ? (
            <Button size="small" variant="outlined" onClick={onUndo} sx={{ textTransform: "none", fontWeight: 700 }}>
              Undo last change
            </Button>
          ) : null}
        </Stack>

        {!showAdvanced ? (
          <ManagementPlannerBoard />
        ) : (
          <>
            {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
            {impact ? (
              <Alert
                severity="info"
                sx={{ mb: 1.5 }}
                action={<Button color="inherit" size="small" onClick={onUndo}>Undo</Button>}
              >
                Before → after: ready {impact.bags_ready_by_target?.before} → {impact.bags_ready_by_target?.after};
                {" "}folded {impact.bags_folded_by_target?.before} → {impact.bags_folded_by_target?.after};
                {" "}complete {impact.final_completion_time?.before} → {impact.final_completion_time?.after}.
              </Alert>
            ) : null}

            <Stack spacing={1.5}>
              <ShiftSetupSection inputs={inputs} onChange={onChange} />
              <EmployeesSection
                inputs={inputs}
                onChange={onChange}
                onAddStaff={onAddStaff}
                onOpenAddStaff={() => {
                  setStaffDraft({ ...newEmployee("washer", "8:30 AM"), sim_mode: "continue_from_time" });
                  setAddStaffOpen(true);
                }}
              />
              <ProcessingTimesSection inputs={inputs} onChange={onChange} />
              <OrdersSection inputs={inputs} onChange={onChange} />
              <StrategySection inputs={inputs} onChange={onChange} />

              <Box>
                <Button
                  variant="contained"
                  size="large"
                  onClick={() => runSim()}
                  disabled={loading}
                  sx={{ textTransform: "none", fontWeight: 800, px: 3 }}
                >
                  {loading ? "Running…" : "F. Run simulation"}
                </Button>
              </Box>

              {loading && !result ? (
                <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
                  <CircularProgress sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
                </Box>
              ) : null}

              {hasRun && result ? (
                <>
                  <ResultsSummarySection
                    summary={result.summary}
                    simulationValid={result.simulation_valid}
                    overlapErrors={result.overlap_errors}
                    validationErrors={result.validation_errors}
                  />
                  <ReadyByBatchSection
                    rows={result.ready_to_fold_by_batch}
                    bagsMoved={result.bags_moved}
                    onEditBatch={setEditBatch}
                  />
                  <AvailabilitySection rows={result.availability_30min} />
                  <RecommendationsSection
                    recommendations={recommendations}
                    onApply={onApplyRecommendation}
                    impact={impact}
                    onUndo={onUndo}
                  />
                  <BagTableAndTimelinesSection rows={result.bag_rows} result={result} />
                </>
              ) : null}
            </Stack>

            <Dialog open={addStaffOpen} onClose={() => setAddStaffOpen(false)} maxWidth="xs" fullWidth>
              <DialogTitle>Add Staff During Shift</DialogTitle>
              <DialogContent>
                <AddStaffDialogFields draft={staffDraft} setDraft={setStaffDraft} />
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setAddStaffOpen(false)} sx={{ textTransform: "none" }}>Cancel</Button>
                <Button variant="contained" onClick={saveAddStaff} sx={{ textTransform: "none", fontWeight: 700 }}>
                  Apply to current scenario
                </Button>
              </DialogActions>
            </Dialog>

            <EditBatchDialog
              open={Boolean(editBatch)}
              batch={editBatch}
              employees={inputs.employees}
              washerCount={Number(inputs.washer_count) || 4}
              dryerCount={Number(inputs.dryer_count) || 4}
              allBagIds={allBagIds}
              onClose={() => setEditBatch(null)}
              onApply={onApplyBatchOverride}
              onReset={onResetBatchOverride}
            />
          </>
        )}
      </Box>
    </Box>
  );
}
