import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RefreshIcon from "@mui/icons-material/Refresh";
import RemoveIcon from "@mui/icons-material/Remove";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import {
  getShiftCapacityPlannerSettings,
  saveShiftCapacityPlannerSettings,
  simulateShiftCapacity,
} from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  BLOCK_SIZE_OPTIONS,
  DEFAULT_MANAGEMENT_INPUTS,
  MANAGEMENT_HYBRIDS,
  MANAGEMENT_ROLES,
  newStaffingInterval,
} from "../../shiftPlanner/managementConstants";
import {
  applyPersistedPlannerParams,
  buildManagementPayload,
  buildPlanningBlocks,
  buildPositionInventoryDisplay,
  clockToHm,
  earlyMinutesBeforeTarget,
  formatManagementOutcome,
  buildSlotStaffingNotes,
  fillRestBasePeopleForRole,
  describeWorkCoverage,
  findWorkCoverageForHybrid,
  findWorkCoverageForRole,
  formatCollapsedSlotStaffLine,
  getAdditionalForBlock,
  getBasePeopleForBlock,
  getHybridPeopleForBlock,
  hmToClock,
  indexBlockPositionsByEnd,
  pickEditablePlannerParamSnapshot,
  pickPersistedPlannerParams,
  setBasePeopleForBlock,
  setHybridPeopleForBlock,
  validateManagementPlanInputs,
  validatePersistedPlannerParams,
  validateStaffingIntervals,
} from "../../shiftPlanner/managementHelpers";

const fieldSx = {
  "& .MuiOutlinedInput-root": { bgcolor: "#fff" },
  "& .MuiInputBase-input": { py: 0.75 },
};

const stripSx = {
  bgcolor: "#fff",
  border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
  borderRadius: 1.25,
  px: 1.5,
  py: 1.25,
  boxShadow: VEEWASH_DASHBOARD.cardShadow,
};

/** Slot shell: left accent marks the hour; staffing vs position bands differ. */
const slotCardSx = {
  ...stripSx,
  py: 1,
  borderLeft: `4px solid ${VEEWASH_DASHBOARD.primaryBlue}`,
  bgcolor: "#fafbfc",
};

const staffingBandSx = {
  bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
  border: `1px solid ${VEEWASH_DASHBOARD.primaryBlueBorder}`,
  borderRadius: 1,
  px: 1.25,
  py: 0.85,
  mb: 0.5,
};

const positionBandSx = {
  bgcolor: "#fff",
  border: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
  borderRadius: 1,
  px: 1.25,
  py: 0.85,
  mt: 0.25,
};

/** Keep SUMMARY + Recalculate at eye level while scrolling slots. */
const summaryStickySx = {
  ...stripSx,
  position: "sticky",
  top: 0,
  zIndex: 4,
  bgcolor: "#fff",
};

function CompactNum({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 1,
  suffix = "",
  width = 72,
  disabled = false,
}) {
  const full = width === "100%";
  return (
    <TextField
      label={suffix ? `${label} (${suffix})` : label}
      type="number"
      size="small"
      fullWidth={full}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      inputProps={{ min, max, step, readOnly: disabled }}
      sx={{
        ...fieldSx,
        width: full ? undefined : width,
        "& .MuiInputBase-input": { py: 0.6, fontSize: "0.85rem" },
        ...(disabled ? { "& .MuiOutlinedInput-root": { bgcolor: "#f8fafc" } } : null),
      }}
    />
  );
}

function ClockField({ label, value, onChange, disabled = false }) {
  return (
    <PlanningTimePicker
      label={label}
      value={clockToHm(value)}
      onChange={(hm) => onChange(hmToClock(hm))}
      exactMinutes
      size="small"
      disabled={disabled}
    />
  );
}

function StaffingIntervalDialog({
  open,
  draft,
  onClose,
  onSave,
  planStart,
  planEnd,
  existing,
  modeLocked = false,
}) {
  const [local, setLocal] = useState(draft);
  const [error, setError] = useState("");

  useEffect(() => {
    setLocal(draft);
    setError("");
  }, [draft, open]);

  const save = () => {
    const nextList = existing.map((row) => (row.id === local.id ? local : row));
    if (!existing.some((row) => row.id === local.id)) nextList.push(local);
    const v = validateStaffingIntervals(nextList, { startTime: planStart, endTime: planEnd });
    if (!v.ok) {
      const hit = v.errors.find((e) => e.intervalId === local.id) || v.errors[0];
      setError(hit?.message || "Invalid staffing");
      return;
    }
    onSave(local);
  };

  if (!local) return null;
  const isAdditional = String(local.mode).toLowerCase() === "additional";
  const title = existing.some((r) => r.id === local.id)
    ? (isAdditional ? "Edit temporary staff" : "Edit base staffing")
    : (isAdditional ? "Add temporary staff" : "Set base staffing");

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ fontWeight: 800, py: 1.5 }}>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={1.25} sx={{ pt: 0.5 }}>
          {error ? <Alert severity="warning">{error}</Alert> : null}
          <FormControl fullWidth size="small">
            <InputLabel>Role</InputLabel>
            <Select
              label="Role"
              value={local.role}
              onChange={(e) => setLocal((p) => ({ ...p, role: e.target.value }))}
            >
              {MANAGEMENT_ROLES.map((r) => (
                <MenuItem key={r.id} value={r.id}>{r.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="People"
            type="number"
            size="small"
            fullWidth
            inputProps={{ min: 1, step: 1 }}
            value={local.people}
            onChange={(e) => setLocal((p) => ({ ...p, people: e.target.value }))}
            sx={fieldSx}
          />
          <Stack direction="row" spacing={1}>
            <Box sx={{ flex: 1 }}>
              <ClockField
                label="Start"
                value={local.start}
                onChange={(v) => setLocal((p) => ({ ...p, start: v }))}
              />
            </Box>
            <Box sx={{ flex: 1 }}>
              <ClockField
                label="End"
                value={local.end}
                onChange={(v) => setLocal((p) => ({ ...p, end: v }))}
              />
            </Box>
          </Stack>
          {!modeLocked ? (
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant={!isAdditional ? "contained" : "outlined"}
                onClick={() => setLocal((p) => ({ ...p, mode: "base" }))}
                sx={{ textTransform: "none", fontWeight: 700, flex: 1 }}
              >
                Base staffing
              </Button>
              <Button
                size="small"
                variant={isAdditional ? "contained" : "outlined"}
                onClick={() => setLocal((p) => ({ ...p, mode: "additional" }))}
                sx={{ textTransform: "none", fontWeight: 700, flex: 1 }}
              >
                Temporary
              </Button>
            </Stack>
          ) : (
            <Typography sx={{ fontSize: "0.8rem", color: "text.secondary" }}>
              {isAdditional ? "Temporary staffing for this slot" : "Base staffing for this slot"}
            </Typography>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={{ textTransform: "none" }}>Cancel</Button>
        <Button variant="contained" onClick={save} sx={{ textTransform: "none", fontWeight: 700 }}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RecalculateButton({ onClick, loading, disabled }) {
  return (
    <Button
      size="small"
      variant="contained"
      onClick={onClick}
      disabled={disabled || loading}
      startIcon={
        loading
          ? <CircularProgress size={14} color="inherit" />
          : <RefreshIcon sx={{ fontSize: 18 }} />
      }
      data-testid="recalculate-plan"
      aria-label="Recalculate plan"
      sx={{
        textTransform: "none",
        fontWeight: 800,
        px: 1.5,
        py: 0.55,
        minWidth: 132,
        ml: { sm: "auto" },
        bgcolor: VEEWASH_DASHBOARD.primaryBlue,
        "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
        boxShadow: "none",
      }}
    >
      {loading ? "Updating…" : "Recalculate"}
    </Button>
  );
}

function CompactSummary({ inputs, outcome, loading, hasStaffing, onRecalculate }) {
  if (!hasStaffing) {
    return (
      <Box sx={{ ...summaryStickySx, py: 1.5 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Typography sx={{ fontWeight: 700, color: "text.secondary", fontSize: "0.95rem", flex: 1 }}>
            Add staffing to build the plan.
          </Typography>
          <RecalculateButton onClick={onRecalculate} loading={loading} disabled />
        </Stack>
      </Box>
    );
  }
  if (!outcome) {
    return (
      <Box sx={{ ...summaryStickySx, py: 1.5 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
        >
          <Typography sx={{ color: "text.secondary", flex: 1 }}>
            {loading ? "Updating plan…" : "Plan not ready — recalculate."}
          </Typography>
          <RecalculateButton onClick={onRecalculate} loading={loading} />
        </Stack>
      </Box>
    );
  }

  const target = Number(outcome.targetBags ?? inputs.bag_count) || 0;
  const projected = Number(outcome.completedByTarget) || 0;
  const finish = outcome.projected || "—";
  const early = earlyMinutesBeforeTarget(inputs.target_time, outcome.projected);
  let statusText = outcome.statusLabel || "";
  if (outcome.status === "completed" && early != null) {
    statusText = `${early} min early`;
  }

  const toneColor = {
    success: VEEWASH_DASHBOARD.tealDark,
    warning: VEEWASH_DASHBOARD.pendingDark,
    neutral: "#9a3412",
  }[outcome.tone] || "text.primary";

  return (
    <Box sx={summaryStickySx} data-testid="planner-summary-bar">
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={{ xs: 0.75, sm: 1.5 }}
        alignItems={{ xs: "stretch", sm: "center" }}
        flexWrap="wrap"
        useFlexGap
      >
        <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", color: "text.secondary", letterSpacing: 0.4 }}>
          SUMMARY
        </Typography>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>
          {target} bags
        </Typography>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>
          Projected {projected} / {target}
        </Typography>
        <Typography sx={{ fontWeight: 700, fontSize: "0.95rem" }}>
          Finish {finish}
        </Typography>
        <Typography sx={{ fontWeight: 800, fontSize: "0.95rem", color: toneColor }}>
          {statusText}
        </Typography>
        <RecalculateButton onClick={onRecalculate} loading={loading} />
      </Stack>
      <Typography sx={{ mt: 0.45, fontSize: "0.68rem", color: "text.disabled", fontWeight: 600 }}>
        Auto-updates as you edit · use Recalculate anytime
      </Typography>
    </Box>
  );
}

const POSITION_TEAL = {
  band: "rgba(13, 148, 136, 0.08)",
  border: "rgba(13, 148, 136, 0.28)",
  label: "#0f766e",
  muted: "rgba(15, 118, 110, 0.55)",
};

const POSITION_AMBER = {
  band: "rgba(217, 119, 6, 0.09)",
  border: "rgba(217, 119, 6, 0.28)",
  label: "#b45309",
  muted: "rgba(180, 83, 9, 0.55)",
  chip: "rgba(15, 118, 110, 0.12)",
  chipText: "#0f766e",
};

function PositionFlow({ block, targetBags }) {
  const [selectedTimeSec, setSelectedTimeSec] = useState(null);
  const view = buildPositionInventoryDisplay(block, targetBags, { selectedTimeSec });
  if (!view) {
    return (
      <Typography sx={{ fontSize: "0.85rem", color: "text.disabled", py: 0.5 }}>
        No position yet for this slot.
      </Typography>
    );
  }
  const cols = view.columns || [];
  const checkpoints = view.checkpoints || [];
  const activeSec = view.selectedTimeSec;
  const stageGridColumns = {
    xs: "48px repeat(5, minmax(0, 1fr))",
    sm: "56px repeat(5, minmax(0, 1fr))",
    md: "60px repeat(5, minmax(0, 1fr))",
  };

  return (
    <Stack spacing={0.85} data-testid="position-two-row">
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Typography
          sx={{
            fontWeight: 800,
            fontSize: "0.72rem",
            letterSpacing: 0.4,
            color: "text.secondary",
          }}
          data-testid="position-selected-label"
        >
          POSITION · {view.selectedTime || "—"}
        </Typography>
        <Typography
          data-testid="position-reconciled"
          sx={{
            fontWeight: 650,
            fontSize: "0.65rem",
            color: view.reconciled ? "text.secondary" : VEEWASH_DASHBOARD.pendingDark,
          }}
        >
          {view.reconcileLabel}
        </Typography>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "repeat(2, minmax(0, 1fr))",
            sm: "repeat(3, minmax(0, 1fr))",
            md: "repeat(5, minmax(0, 1fr))",
          },
          gap: 0.65,
        }}
        data-testid="position-stage-columns"
      >
        {cols.map((col) => (
          <Box
            key={col.id}
            data-testid={`stage-col-${col.id}`}
            sx={{
              borderRadius: 1.25,
              border: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
              overflow: "hidden",
              minWidth: 0,
              px: 0.55,
              py: 0.55,
              bgcolor: "rgba(255,255,255,0.7)",
            }}
          >
            <Typography
              sx={{
                textAlign: "center",
                fontWeight: 800,
                fontSize: "0.68rem",
                letterSpacing: 0.5,
                color: "text.secondary",
                mb: 0.25,
              }}
            >
              {col.title}
            </Typography>
            <Typography
              data-testid={`total-done-${col.id}`}
              sx={{
                textAlign: "center",
                fontWeight: 800,
                fontSize: "1.35rem",
                lineHeight: 1.05,
                color: POSITION_TEAL.label,
              }}
            >
              {col.totalDone}
            </Typography>
            <Typography
              sx={{
                textAlign: "center",
                fontWeight: 700,
                fontSize: "0.55rem",
                letterSpacing: 0.3,
                color: POSITION_TEAL.label,
              }}
            >
              total done
            </Typography>
            <Typography
              data-testid={`this-15-${col.id}`}
              sx={{
                textAlign: "center",
                mt: 0.25,
                fontSize: "0.72rem",
                fontWeight: 800,
                color: col.this15 > 0 ? "text.primary" : "text.disabled",
              }}
            >
              {col.this15 > 0 ? `+${col.this15}` : "+0"}
              <Box component="span" sx={{ fontWeight: 650, fontSize: "0.58rem", color: "text.secondary", ml: 0.4 }}>
                this 15 min
              </Box>
            </Typography>
            {col.isTerminal ? (
              <Typography
                sx={{
                  textAlign: "center",
                  mt: 0.35,
                  fontSize: "0.62rem",
                  fontWeight: 700,
                  color: POSITION_TEAL.label,
                }}
              >
                {col.terminalText || `${col.totalDone} complete`}
              </Typography>
            ) : (
              <Typography
                data-testid={`waiting-next-${col.id}`}
                sx={{
                  textAlign: "center",
                  mt: 0.35,
                  fontSize: "0.68rem",
                  fontWeight: 750,
                  color: col.waitingNext > 0 ? POSITION_AMBER.label : "text.disabled",
                }}
              >
                {col.waitingNextText || `0 → ${col.waitingNextLabel || "next"}`}
              </Typography>
            )}
            {col.inProcess > 0 ? (
              <Typography
                data-testid={`in-process-${col.id}`}
                sx={{
                  textAlign: "center",
                  mt: 0.2,
                  fontSize: "0.62rem",
                  fontWeight: 650,
                  color: "text.secondary",
                }}
              >
                {col.inProcessText}
                {(col.inLabor != null || col.inCycle != null) && (col.inLabor > 0 || col.inCycle > 0) ? (
                  <Box component="span" sx={{ display: "block", fontSize: "0.55rem", color: "text.disabled" }}>
                    {[
                      col.inLabor > 0 ? `${col.inLabor} loading` : null,
                      col.inCycle > 0 ? `${col.inCycle} in cycle` : null,
                    ].filter(Boolean).join(" · ")}
                  </Box>
                ) : null}
              </Typography>
            ) : null}
          </Box>
        ))}
      </Box>

      {checkpoints.length ? (
        <Box data-testid="availability-15min">
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: "0.65rem",
              letterSpacing: 0.4,
              color: POSITION_AMBER.label,
              mb: 0.35,
            }}
          >
            15-MIN CHECKPOINTS
          </Typography>
          <Box
            data-testid="availability-15min-panel"
            sx={{
              borderRadius: 1.25,
              border: `1px solid ${POSITION_AMBER.border}`,
              bgcolor: "rgba(255,251,235,0.45)",
              overflow: "auto",
            }}
          >
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: stageGridColumns,
                gap: 0.35,
                alignItems: "end",
                px: 0.65,
                pt: 0.5,
                pb: 0.3,
                borderBottom: `1px solid ${POSITION_AMBER.border}`,
                minWidth: 520,
              }}
              data-testid="checkpoint-header"
            >
              <Typography sx={{ fontWeight: 800, fontSize: "0.55rem", color: "text.disabled" }}>
                TIME
              </Typography>
              {["WEIGH", "SORT", "WASH", "DRY", "FOLD"].map((t) => (
                <Typography
                  key={t}
                  sx={{ textAlign: "center", fontWeight: 800, fontSize: "0.55rem", color: "text.secondary" }}
                >
                  {t}
                </Typography>
              ))}
            </Box>
            {checkpoints.map((cp) => {
              const selected = Number(cp.time_sec) === Number(activeSec);
              return (
                <Box
                  key={cp.time_sec || cp.time}
                  component="button"
                  type="button"
                  onClick={() => setSelectedTimeSec(cp.time_sec)}
                  data-testid={`checkpoint-${cp.time}`}
                  data-selected={selected ? "true" : "false"}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: stageGridColumns,
                    gap: 0.35,
                    alignItems: "start",
                    width: "100%",
                    textAlign: "left",
                    cursor: "pointer",
                    border: 0,
                    borderBottom: `1px solid ${POSITION_AMBER.border}`,
                    bgcolor: selected ? "rgba(13, 148, 136, 0.10)" : "transparent",
                    px: 0.65,
                    py: 0.45,
                    minWidth: 520,
                    "&:last-child": { borderBottom: 0 },
                    "&:hover": { bgcolor: selected ? "rgba(13, 148, 136, 0.14)" : "rgba(217, 119, 6, 0.08)" },
                  }}
                >
                  <Typography sx={{ fontWeight: 800, fontSize: "0.68rem", color: selected ? POSITION_TEAL.label : "text.secondary" }}>
                    {cp.time}
                  </Typography>
                  {(cp.stages || []).map((stage) => (
                    <Box
                      key={stage.id}
                      data-testid={`checkpoint-${cp.time}-${stage.id}`}
                      sx={{ minWidth: 0, textAlign: "center" }}
                    >
                      <Typography sx={{ fontWeight: 800, fontSize: "0.78rem", color: POSITION_TEAL.label, lineHeight: 1.1 }}>
                        {stage.totalDone}
                      </Typography>
                      <Typography sx={{ fontSize: "0.55rem", fontWeight: 700, color: stage.this15 > 0 ? "text.primary" : "text.disabled" }}>
                        {stage.this15 > 0 ? `+${stage.this15}` : "+0"}
                      </Typography>
                      {!stage.isTerminal ? (
                        <Typography sx={{ fontSize: "0.55rem", fontWeight: 700, color: stage.waitingNext > 0 ? POSITION_AMBER.label : "text.disabled" }}>
                          {stage.waitingNext}→{stage.waitingNextLabel || "?"}
                        </Typography>
                      ) : (
                        <Typography sx={{ fontSize: "0.55rem", fontWeight: 700, color: POSITION_TEAL.label }}>
                          done
                        </Typography>
                      )}
                      <Typography sx={{ fontSize: "0.52rem", fontWeight: 650, color: stage.inProcess > 0 ? "text.secondary" : "text.disabled" }}>
                        {stage.inProcess > 0 ? `${stage.inProcess} in proc` : "—"}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              );
            })}
          </Box>
        </Box>
      ) : null}
    </Stack>
  );
}

function WorkCoverageHint({ rows, testId, processParams }) {
  if (!rows?.length) return null;
  return (
    <Stack spacing={0.35} sx={{ pl: 6.5, pb: 0.4 }} data-testid={testId || "work-coverage-hint"}>
      {rows.map((row) => {
        const d = describeWorkCoverage(row, { processParams });
        const color = d.level === "fully_utilized"
          ? VEEWASH_DASHBOARD.primaryBlueDark
          : d.level === "mostly_utilized"
            ? "text.secondary"
            : VEEWASH_DASHBOARD.pendingDark;
        return (
          <Tooltip key={`${row.role || row.hybrid}-${row.mode}-${row.start}-${row.end}-${row.index}`} title={d.detail || ""} arrow enterDelay={350}>
            <Box
              data-coverage-level={d.level}
              data-coverage-reason={d.reasonCode}
            >
              {d.lines.map((line, i) => {
                const isStatus = String(line).startsWith("Status:");
                return (
                  <Typography
                    key={`${line}-${i}`}
                    sx={{
                      fontSize: i === 0 || isStatus ? "0.7rem" : "0.66rem",
                      fontWeight: i === 0 || isStatus ? 700 : 600,
                      color,
                      lineHeight: 1.25,
                      whiteSpace: "pre-line",
                    }}
                  >
                    {line}
                  </Typography>
                );
              })}
            </Box>
          </Tooltip>
        );
      })}
    </Stack>
  );
}

function BlockRoleRow({
  role,
  blockStart,
  blockEnd,
  intervals,
  onBaseChange,
  onAddTemporary,
  onEdit,
  onRemove,
  showFillRest = false,
  onFillRest = null,
  coverageRows = [],
  processParams = null,
}) {
  const base = getBasePeopleForBlock(intervals, role.id, blockStart, blockEnd);
  const extras = getAdditionalForBlock(intervals, role.id, blockStart, blockEnd);
  const baseCoverage = base > 0
    ? findWorkCoverageForRole(coverageRows, role.id, blockStart, blockEnd, { mode: "base" })
    : [];
  const tempCoverage = extras.length
    ? findWorkCoverageForRole(coverageRows, role.id, blockStart, blockEnd, { mode: "additional" })
    : [];

  return (
    <Box
      sx={{
        borderBottom: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
        "&:last-child": { borderBottom: 0 },
      }}
    >
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        py: 0.45,
        minHeight: 36,
      }}
    >
      <Typography
        sx={{
          width: 52,
          flexShrink: 0,
          fontWeight: 800,
          fontSize: "0.72rem",
          letterSpacing: 0.4,
          color: "text.secondary",
        }}
      >
        {role.short.toUpperCase()}
      </Typography>

      <Stack direction="row" alignItems="center" spacing={0.25} sx={{ flexShrink: 0 }}>
        <IconButton
          size="small"
          aria-label={`Decrease ${role.label} staff`}
          onClick={() => onBaseChange(Math.max(0, base - 1))}
          sx={{ p: 0.35 }}
        >
          <RemoveIcon sx={{ fontSize: 16 }} />
        </IconButton>
        <Typography
          sx={{ width: 18, textAlign: "center", fontWeight: 800, fontSize: "0.95rem" }}
          aria-label={`${role.label} staff ${base}`}
        >
          {base}
        </Typography>
        <IconButton
          size="small"
          aria-label={`Increase ${role.label} staff`}
          onClick={() => onBaseChange(base + 1)}
          sx={{ p: 0.35 }}
        >
          <AddIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Stack>

      <Typography sx={{ fontSize: "0.78rem", color: "text.secondary", flexShrink: 0 }}>
        {base > 0 ? `${blockStart}–${blockEnd}` : "—"}
      </Typography>

      {showFillRest ? (
        <Button
          size="small"
          onClick={() => onFillRest?.(base)}
          aria-label={`Fill rest ${role.label}`}
          sx={{
            textTransform: "none",
            fontWeight: 600,
            fontSize: "0.75rem",
            color: "text.secondary",
            minWidth: 0,
            px: 0.5,
            py: 0.25,
            flexShrink: 0,
            "&:hover": { bgcolor: "transparent", color: VEEWASH_DASHBOARD.primaryBlue, textDecoration: "underline" },
          }}
        >
          Fill rest
        </Button>
      ) : null}

      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ flex: 1, minWidth: 0 }}>
        {extras.map((row) => (
          <Box
            key={row.id}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0.25,
              bgcolor: VEEWASH_DASHBOARD.tealLight,
              border: `1px solid ${VEEWASH_DASHBOARD.tealBorder}`,
              borderRadius: 1,
              px: 0.6,
              py: 0.1,
            }}
          >
            <Typography sx={{ fontSize: "0.75rem", fontWeight: 700 }}>
              +{row.people} {row.start}–{row.end}
            </Typography>
            <IconButton size="small" onClick={() => onEdit(row)} sx={{ p: 0.15 }}>
              <EditOutlinedIcon sx={{ fontSize: 14 }} />
            </IconButton>
            <IconButton size="small" onClick={() => onRemove(row.id)} sx={{ p: 0.15 }}>
              <DeleteOutlineIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Box>
        ))}
      </Stack>

      <Button
        size="small"
        startIcon={<AddIcon sx={{ fontSize: 14 }} />}
        onClick={() => onAddTemporary(role.id)}
        sx={{ textTransform: "none", fontWeight: 700, fontSize: "0.75rem", flexShrink: 0, minWidth: 0, px: 0.75 }}
      >
        Temp
      </Button>
    </Stack>
    <WorkCoverageHint
      rows={baseCoverage}
      testId={`work-coverage-${role.id}-base`}
      processParams={processParams}
    />
    <WorkCoverageHint
      rows={tempCoverage}
      testId={`work-coverage-${role.id}-temp`}
      processParams={processParams}
    />
    </Box>
  );
}

function HybridRoleRow({
  hybrid,
  blockStart,
  blockEnd,
  intervals,
  onChange,
  coverageRows = [],
  processParams = null,
}) {
  const count = getHybridPeopleForBlock(intervals, hybrid.id, blockStart, blockEnd);
  const hybridCoverage = count > 0
    ? findWorkCoverageForHybrid(coverageRows, hybrid.id, blockStart, blockEnd)
    : [];
  return (
    <Box
      sx={{
        borderBottom: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
        "&:last-child": { borderBottom: 0 },
      }}
    >
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        py: 0.35,
        minHeight: 32,
      }}
    >
      <Typography
        sx={{
          width: 140,
          flexShrink: 0,
          fontWeight: 700,
          fontSize: "0.72rem",
          color: "text.secondary",
        }}
      >
        {hybrid.label}
      </Typography>
      <Stack direction="row" alignItems="center" spacing={0.25} sx={{ flexShrink: 0 }}>
        <IconButton
          size="small"
          aria-label={`Decrease ${hybrid.label} hybrid staff`}
          onClick={() => onChange(Math.max(0, count - 1))}
          sx={{ p: 0.35 }}
        >
          <RemoveIcon sx={{ fontSize: 16 }} />
        </IconButton>
        <Typography
          sx={{ width: 18, textAlign: "center", fontWeight: 800, fontSize: "0.95rem" }}
          aria-label={`${hybrid.label} hybrid staff ${count}`}
        >
          {count}
        </Typography>
        <IconButton
          size="small"
          aria-label={`Increase ${hybrid.label} hybrid staff`}
          onClick={() => onChange(count + 1)}
          sx={{ p: 0.35 }}
        >
          <AddIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Stack>
      <Typography sx={{ fontSize: "0.72rem", color: "text.disabled" }}>
        {count > 0 ? "shared calendar" : "—"}
      </Typography>
    </Stack>
    <WorkCoverageHint
      rows={hybridCoverage}
      testId={`work-coverage-hybrid-${hybrid.id}`}
      processParams={processParams}
    />
    </Box>
  );
}

function SlotCardHeader({ slotLabel, staffOpen, onToggle }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.75 }} flexWrap="wrap" useFlexGap>
      <Typography
        sx={{ fontWeight: 800, fontSize: "0.95rem", color: VEEWASH_DASHBOARD.primaryBlueDark }}
        data-testid="slot-range"
      >
        {slotLabel}
      </Typography>
      <Button
        size="small"
        onClick={onToggle}
        endIcon={staffOpen ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
        aria-expanded={staffOpen}
        aria-label={staffOpen ? "Collapse staffing" : "Expand staffing"}
        sx={{
          textTransform: "none",
          fontWeight: 700,
          fontSize: "0.72rem",
          minWidth: 0,
          px: 0.75,
          py: 0.15,
          ml: "auto",
        }}
      >
        {staffOpen ? "Collapse staffing" : "Expand staffing"}
      </Button>
    </Stack>
  );
}

function SlotStaffingNotes({ notes }) {
  if (!notes?.length) return null;
  return (
    <Stack spacing={0.4} sx={{ mt: 0.65 }} data-testid="slot-staffing-notes">
      {notes.map((note) => (
        <Typography
          key={`${note.tone}-${note.text}`}
          sx={{
            fontSize: "0.72rem",
            fontWeight: 650,
            lineHeight: 1.35,
            color: note.tone === "warning" ? VEEWASH_DASHBOARD.pendingDark : "text.secondary",
            bgcolor: note.tone === "warning" ? "#fff7ed" : "rgba(255,255,255,0.65)",
            border: `1px solid ${
              note.tone === "warning" ? "rgba(146, 64, 14, 0.25)" : VEEWASH_DASHBOARD.primaryBlueBorder
            }`,
            borderRadius: 0.75,
            px: 0.85,
            py: 0.45,
          }}
        >
          {note.text}
        </Typography>
      ))}
    </Stack>
  );
}

export default function ManagementPlannerBoard({ initialInputs = null, skipSettingsLoad = false } = {}) {
  const [inputs, setInputs] = useState(() => ({
    ...DEFAULT_MANAGEMENT_INPUTS,
    ...(initialInputs || {}),
  }));
  const [savedParams, setSavedParams] = useState(() =>
    pickPersistedPlannerParams({ ...DEFAULT_MANAGEMENT_INPUTS, ...(initialInputs || {}) }),
  );
  const [settingsReady, setSettingsReady] = useState(Boolean(skipSettingsLoad || initialInputs));
  const [paramsEditing, setParamsEditing] = useState(false);
  const [editSnapshot, setEditSnapshot] = useState(null);
  const [savingParams, setSavingParams] = useState(false);
  const [paramError, setParamError] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [draft, setDraft] = useState(null);
  const [modeLocked, setModeLocked] = useState(true);
  /** Per-block staffing strip open state; default expanded. */
  const [staffingExpanded, setStaffingExpanded] = useState({});
  const debounceRef = useRef(null);
  const seqRef = useRef(0);
  const paramsLocked = !paramsEditing;

  useEffect(() => {
    if (skipSettingsLoad || initialInputs) {
      setSettingsReady(true);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getShiftCapacityPlannerSettings();
        if (cancelled) return;
        const saved = pickPersistedPlannerParams(res.data || {});
        setSavedParams(saved);
        setInputs((prev) => applyPersistedPlannerParams(prev, saved));
      } catch {
        if (cancelled) return;
        setSavedParams(pickPersistedPlannerParams(DEFAULT_MANAGEMENT_INPUTS));
      } finally {
        if (!cancelled) setSettingsReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [skipSettingsLoad, initialInputs]);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const beginEditParams = () => {
    setEditSnapshot(pickEditablePlannerParamSnapshot(inputs));
    setParamError("");
    setParamsEditing(true);
  };

  const cancelEditParams = () => {
    if (editSnapshot) {
      setInputs((prev) => ({ ...prev, ...editSnapshot }));
    } else {
      setInputs((prev) => applyPersistedPlannerParams(prev, savedParams));
    }
    setParamError("");
    setParamsEditing(false);
    setEditSnapshot(null);
  };

  const saveParams = async () => {
    const persistedCheck = validatePersistedPlannerParams(inputs);
    if (!persistedCheck.ok) {
      setParamError(persistedCheck.errors[0]?.message || "Fix parameters before saving");
      return;
    }
    const planCheck = validateManagementPlanInputs(inputs);
    if (!planCheck.ok) {
      setParamError(planCheck.errors[0]?.message || "Fix parameters before saving");
      return;
    }
    setSavingParams(true);
    setParamError("");
    try {
      const res = await saveShiftCapacityPlannerSettings(persistedCheck.normalized);
      const saved = pickPersistedPlannerParams(res.data || persistedCheck.normalized);
      setSavedParams(saved);
      setInputs((prev) => applyPersistedPlannerParams(prev, saved));
      setParamsEditing(false);
      setEditSnapshot(null);
    } catch (err) {
      setParamError(err.response?.data?.error || err.message || "Failed to save parameters");
    } finally {
      setSavingParams(false);
    }
  };

  const planBlocks = useMemo(
    () => buildPlanningBlocks(inputs.start_time, inputs.target_time, inputs.planning_block_size_min),
    [inputs.start_time, inputs.target_time, inputs.planning_block_size_min],
  );

  const positionByEnd = useMemo(
    () => indexBlockPositionsByEnd(result?.block_positions),
    [result],
  );

  const runSim = useCallback(async (nextInputs) => {
    const payloadInputs = nextInputs || inputs;
    const horizonEnd = payloadInputs.target_time;
    const planCheck = validateManagementPlanInputs(payloadInputs);
    if (!planCheck.ok) {
      setError(planCheck.errors[0]?.message || "Fix plan parameters");
      return null;
    }
    const client = validateStaffingIntervals(payloadInputs.staffing_intervals, {
      startTime: payloadInputs.start_time,
      endTime: horizonEnd,
    });
    if (!client.ok) {
      setError(client.errors[0]?.message || "Fix staffing before running");
      return null;
    }

    const seq = ++seqRef.current;
    setLoading(true);
    setError("");
    try {
      const res = await simulateShiftCapacity(buildManagementPayload(payloadInputs));
      if (seq !== seqRef.current) return null;
      const raw = res.data || {};
      const des = raw.des && typeof raw.des === "object" ? raw.des : {};
      const merged = {
        ...raw,
        block_positions: raw.block_positions || des.block_positions || [],
        staffing_plan: raw.staffing_plan || des.staffing_plan || {},
        management_outcome:
          raw.management_outcome
          || des.management_outcome
          || raw.summary?.management_outcome
          || null,
        staffing_deficits:
          raw.staffing_deficits
          || des.staffing_deficits
          || raw.summary?.staffing_deficits
          || [],
        work_coverage: raw.work_coverage || des.work_coverage || [],
        summary: raw.summary || des.summary || {},
      };
      setResult(merged);
      if (res.data?.simulation_valid === false && (res.data?.validation_errors || []).length) {
        setError(
          (res.data.validation_errors || [])
            .map((e) => (typeof e === "string" ? e : e.message || e.code))
            .join(" · "),
        );
      }
      return res.data;
    } catch (err) {
      if (seq !== seqRef.current) return null;
      setError(err.response?.data?.error || err.message || "Simulation failed");
      setResult(null);
      return null;
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [inputs]);

  useEffect(() => {
    if (!settingsReady) return undefined;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSim(inputs);
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [inputs, settingsReady]); // eslint-disable-line react-hooks/exhaustive-deps

  const recalculateNow = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    runSim(inputs);
  }, [inputs, runSim]);

  const hasStaffing = (
    (inputs.staffing_intervals || []).length > 0
    || (inputs.hybrid_intervals || []).length > 0
  );
  const outcome = useMemo(
    () => (result && hasStaffing ? formatManagementOutcome({ ...result, inputs }) : null),
    [result, inputs, hasStaffing],
  );
  const targetBags = Number(inputs.bag_count) || 0;

  const openTemporary = (roleId, blockStart, blockEnd) => {
    setModeLocked(true);
    setDraft(
      newStaffingInterval(roleId, {
        start: blockStart,
        end: blockEnd,
        mode: "additional",
        people: 1,
      }),
    );
    setDialogOpen(true);
  };

  const openEdit = (row) => {
    setModeLocked(true);
    setDraft({ ...row });
    setDialogOpen(true);
  };

  const saveInterval = (row) => {
    setInputs((prev) => {
      const list = [...(prev.staffing_intervals || [])];
      const idx = list.findIndex((r) => r.id === row.id);
      const nextRow = {
        ...row,
        people: Number(row.people),
        mode: String(row.mode || "base").toLowerCase() === "additional" ? "additional" : "base",
      };
      if (idx >= 0) list[idx] = nextRow;
      else list.push(nextRow);
      return { ...prev, staffing_intervals: list };
    });
    setDialogOpen(false);
  };

  const removeInterval = (id) => {
    setInputs((prev) => ({
      ...prev,
      staffing_intervals: (prev.staffing_intervals || []).filter((r) => r.id !== id),
    }));
  };

  const changeBase = (roleId, blockStart, blockEnd, people) => {
    setInputs((prev) => ({
      ...prev,
      staffing_intervals: setBasePeopleForBlock(
        prev.staffing_intervals,
        roleId,
        blockStart,
        blockEnd,
        people,
      ),
    }));
  };

  const changeHybrid = (hybridId, blockStart, blockEnd, people) => {
    setInputs((prev) => ({
      ...prev,
      hybrid_intervals: setHybridPeopleForBlock(
        prev.hybrid_intervals,
        hybridId,
        blockStart,
        blockEnd,
        people,
      ),
    }));
  };

  const fillRest = (roleId, people) => {
    setInputs((prev) => ({
      ...prev,
      staffing_intervals: fillRestBasePeopleForRole(
        prev.staffing_intervals,
        roleId,
        planBlocks,
        people,
      ),
    }));
  };

  if (!settingsReady) {
    return (
      <Box sx={{ ...stripSx, py: 2, display: "flex", alignItems: "center", gap: 1 }}>
        <CircularProgress size={16} sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} />
        <Typography sx={{ fontSize: "0.9rem", color: "text.secondary" }}>
          Loading saved parameters…
        </Typography>
      </Box>
    );
  }

  const headerBtnSx = {
    textTransform: "none",
    fontWeight: 700,
    fontSize: "0.8rem",
    minWidth: 0,
    px: 1,
    py: 0.35,
  };

  return (
    <Stack spacing={1.5}>
      {/* PLAN */}
      <Box sx={stripSx}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          spacing={1}
          sx={{ mb: 1 }}
        >
          <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", letterSpacing: 0.4, color: "text.secondary" }}>
            PLAN
          </Typography>
          {!paramsEditing ? (
            <Button size="small" onClick={beginEditParams} sx={headerBtnSx}>
              Edit Parameters
            </Button>
          ) : (
            <Stack direction="row" spacing={0.75} alignItems="center">
              <Button
                size="small"
                variant="contained"
                onClick={saveParams}
                disabled={savingParams}
                sx={headerBtnSx}
              >
                {savingParams ? "Saving…" : "Save Parameters"}
              </Button>
              <Button
                size="small"
                onClick={cancelEditParams}
                disabled={savingParams}
                sx={headerBtnSx}
              >
                Cancel
              </Button>
            </Stack>
          )}
        </Stack>
        {paramError ? <Alert severity="warning" sx={{ py: 0.25, mb: 1 }}>{paramError}</Alert> : null}
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)", md: "1fr 1fr 1.2fr 1.2fr 1fr" },
            gap: 1,
          }}
        >
          <CompactNum
            label="Target bags"
            value={inputs.bag_count}
            onChange={(v) => onChange("bag_count", v)}
            min={1}
            width="100%"
            disabled={paramsLocked}
          />
          <CompactNum
            label="Avg Bag Weight"
            value={inputs.avg_lbs_per_bag}
            onChange={(v) => onChange("avg_lbs_per_bag", v)}
            min={0.1}
            step={0.1}
            suffix="lb"
            width="100%"
            disabled={paramsLocked}
          />
          <ClockField
            label="Start time"
            value={inputs.start_time}
            onChange={(v) => onChange("start_time", v)}
            disabled={paramsLocked}
          />
          <ClockField
            label="Target finish"
            value={inputs.target_time}
            onChange={(v) => onChange("target_time", v)}
            disabled={paramsLocked}
          />
          <FormControl size="small" fullWidth disabled={paramsLocked}>
            <InputLabel>Block size</InputLabel>
            <Select
              label="Block size"
              value={inputs.planning_block_size_min}
              onChange={(e) => onChange("planning_block_size_min", Number(e.target.value))}
              sx={{ bgcolor: paramsLocked ? "#f8fafc" : "#fff" }}
            >
              {BLOCK_SIZE_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Box>

      {/* MACHINES — hardware capacity only; not wash/dry staffing */}
      <Box sx={stripSx}>
        <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", letterSpacing: 0.4, color: "text.secondary" }}>
            MACHINES
          </Typography>
          <Typography sx={{ fontSize: "0.72rem", color: "text.disabled" }}>
            Hardware only — wash/dry still need staff in STAFFING below
          </Typography>
        </Stack>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" },
            gap: 1,
          }}
        >
          <CompactNum
            label="Washers"
            value={inputs.washer_count}
            onChange={(v) => onChange("washer_count", v)}
            min={1}
            suffix="machines"
            width="100%"
            disabled={paramsLocked}
          />
          <CompactNum
            label="2-Washer Split"
            value={inputs.two_washer_split_pct}
            onChange={(v) => onChange("two_washer_split_pct", v)}
            min={0}
            max={100}
            step={0.1}
            suffix="%"
            width="100%"
            disabled={paramsLocked}
          />
          <CompactNum
            label="Dryers"
            value={inputs.dryer_count}
            onChange={(v) => onChange("dryer_count", v)}
            min={1}
            suffix="machines"
            width="100%"
            disabled={paramsLocked}
          />
          <CompactNum
            label="2-Dryer Split"
            value={inputs.two_dryer_split_pct}
            onChange={(v) => onChange("two_dryer_split_pct", v)}
            min={0}
            max={100}
            step={0.1}
            suffix="%"
            width="100%"
            disabled={paramsLocked}
          />
        </Box>
      </Box>

      {/* PROCESS */}
      <Box sx={stripSx}>
        <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", letterSpacing: 0.4, color: "text.secondary", mb: 1 }}>
          PROCESS
        </Typography>
        <Stack
          direction="row"
          flexWrap="wrap"
          useFlexGap
          spacing={0.75}
          alignItems="flex-start"
        >
          <CompactNum label="Weigh" value={inputs.weigh_sec_per_bag} onChange={(v) => onChange("weigh_sec_per_bag", v)} min={1} suffix="s" width={84} disabled={paramsLocked} />
          <CompactNum label="Sort" value={inputs.sort_min_per_bag} onChange={(v) => onChange("sort_min_per_bag", v)} min={0} step={0.5} suffix="m" width={84} disabled={paramsLocked} />
          <CompactNum label="Wash labor" value={inputs.load_washer_min} onChange={(v) => onChange("load_washer_min", v)} min={0} step={0.5} suffix="m" width={96} disabled={paramsLocked} />
          <CompactNum label="Wash cycle" value={inputs.wash_cycle_min} onChange={(v) => onChange("wash_cycle_min", v)} min={1} suffix="m" width={96} disabled={paramsLocked} />
          <CompactNum label="Dry labor" value={inputs.load_dryer_min} onChange={(v) => onChange("load_dryer_min", v)} min={0} step={0.5} suffix="m" width={92} disabled={paramsLocked} />
          <CompactNum label="Dry cycle" value={inputs.dry_cycle_min} onChange={(v) => onChange("dry_cycle_min", v)} min={1} suffix="m" width={92} disabled={paramsLocked} />
          <CompactNum label="Fold" value={inputs.fold_min_per_bag} onChange={(v) => onChange("fold_min_per_bag", v)} min={0} step={0.5} suffix="m" width={84} disabled={paramsLocked} />
        </Stack>
      </Box>

      <CompactSummary
        inputs={inputs}
        outcome={outcome}
        loading={loading}
        hasStaffing={hasStaffing}
        onRecalculate={recalculateNow}
      />

      {error ? <Alert severity="error" sx={{ py: 0.5 }}>{error}</Alert> : null}

      {planBlocks.length > 1 ? (
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            size="small"
            onClick={() => {
              const next = {};
              planBlocks.forEach((pb) => { next[pb.block_start] = false; });
              setStaffingExpanded(next);
            }}
            sx={{ textTransform: "none", fontWeight: 700, fontSize: "0.75rem" }}
          >
            Collapse all staffing
          </Button>
          <Button
            size="small"
            onClick={() => {
              const next = {};
              planBlocks.forEach((pb) => { next[pb.block_start] = true; });
              setStaffingExpanded(next);
            }}
            sx={{ textTransform: "none", fontWeight: 700, fontSize: "0.75rem" }}
          >
            Expand all staffing
          </Button>
        </Stack>
      ) : null}

      {/* One card = one time slot: start staffing + end POSITION */}
      <Stack spacing={1.25}>
        {planBlocks.map((pb, blockIndex) => {
          const pos = positionByEnd[pb.block_end] || null;
          const isFirstStaffingBlock = blockIndex === 0;
          const staffOpen = staffingExpanded[pb.block_start] !== false;
          const staffLine = formatCollapsedSlotStaffLine(
            inputs.staffing_intervals,
            inputs.hybrid_intervals,
            pb.block_start,
            pb.block_end,
          );
          const staffingNotes = buildSlotStaffingNotes(
            inputs.staffing_intervals,
            inputs.hybrid_intervals,
            pb.block_start,
            pb.block_end,
          );
          const slotLabel = `${pb.block_start} → ${pb.block_end}`;
          return (
            <Box
              key={`${pb.block_start}-${pb.block_end}`}
              sx={slotCardSx}
              data-testid="planning-slot-card"
              data-slot-start={pb.block_start}
              data-slot-end={pb.block_end}
            >
              <SlotCardHeader
                slotLabel={slotLabel}
                staffOpen={staffOpen}
                onToggle={() =>
                  setStaffingExpanded((prev) => ({
                    ...prev,
                    [pb.block_start]: !staffOpen,
                  }))
                }
              />

              <Box sx={staffingBandSx}>
                <Typography
                  sx={{
                    fontWeight: 800,
                    fontSize: "0.68rem",
                    letterSpacing: 0.5,
                    color: VEEWASH_DASHBOARD.primaryBlueDark,
                    mb: 0.35,
                  }}
                >
                  STAFFING
                </Typography>
                {!staffOpen ? (
                  <Typography
                    sx={{ fontSize: "0.8rem", color: "text.secondary", fontWeight: 600 }}
                    data-testid="collapsed-staff-line"
                  >
                    STAFF: {staffLine}
                  </Typography>
                ) : (
                  <Box data-testid="expanded-staffing">
                    {MANAGEMENT_ROLES.map((role) => (
                      <BlockRoleRow
                        key={role.id}
                        role={role}
                        blockStart={pb.block_start}
                        blockEnd={pb.block_end}
                        intervals={inputs.staffing_intervals}
                        coverageRows={
                          (pos?.staffing?.work_coverage)
                          || result?.work_coverage
                          || []
                        }
                        processParams={inputs}
                        onBaseChange={(n) => changeBase(role.id, pb.block_start, pb.block_end, n)}
                        onAddTemporary={(roleId) => openTemporary(roleId, pb.block_start, pb.block_end)}
                        onEdit={openEdit}
                        onRemove={removeInterval}
                        showFillRest={isFirstStaffingBlock && planBlocks.length > 1}
                        onFillRest={(people) => fillRest(role.id, people)}
                      />
                    ))}
                    <Typography
                      sx={{
                        mt: 0.85,
                        mb: 0.25,
                        fontWeight: 700,
                        fontSize: "0.65rem",
                        letterSpacing: 0.4,
                        color: "text.disabled",
                      }}
                    >
                      Hybrid
                    </Typography>
                    {MANAGEMENT_HYBRIDS.map((hybrid) => (
                      <HybridRoleRow
                        key={hybrid.id}
                        hybrid={hybrid}
                        blockStart={pb.block_start}
                        blockEnd={pb.block_end}
                        intervals={inputs.hybrid_intervals}
                        coverageRows={
                          (pos?.staffing?.work_coverage)
                          || result?.work_coverage
                          || []
                        }
                        processParams={inputs}
                        onChange={(n) => changeHybrid(hybrid.id, pb.block_start, pb.block_end, n)}
                      />
                    ))}
                  </Box>
                )}
                <SlotStaffingNotes notes={staffingNotes} />
              </Box>

              <Box
                sx={{
                  textAlign: "center",
                  py: 0.35,
                  color: "text.disabled",
                  fontSize: "0.85rem",
                }}
              >
                ↓
              </Box>

              <Box sx={positionBandSx}>
                <Typography
                  sx={{
                    fontWeight: 800,
                    fontSize: "0.72rem",
                    letterSpacing: 0.5,
                    color: "text.secondary",
                    mb: 0.5,
                  }}
                  data-testid="slot-position-label"
                >
                  {pb.block_end} POSITION
                </Typography>
                {hasStaffing ? (
                  <PositionFlow block={pos} targetBags={targetBags} />
                ) : (
                  <Typography sx={{ fontSize: "0.85rem", color: "text.disabled" }}>
                    Position appears after staffing is set.
                  </Typography>
                )}
              </Box>
            </Box>
          );
        })}
        {!planBlocks.length ? (
          <Typography color="text.secondary">Set start and target finish to build blocks.</Typography>
        ) : null}
      </Stack>

      <StaffingIntervalDialog
        open={dialogOpen}
        draft={draft}
        existing={inputs.staffing_intervals}
        planStart={inputs.start_time}
        planEnd={inputs.target_time}
        modeLocked={modeLocked}
        onClose={() => setDialogOpen(false)}
        onSave={saveInterval}
      />
    </Stack>
  );
}
