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
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import RemoveIcon from "@mui/icons-material/Remove";
import PlanningTimePicker from "../datetime/PlanningTimePicker";
import { simulateShiftCapacity } from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  BLOCK_SIZE_OPTIONS,
  DEFAULT_MANAGEMENT_INPUTS,
  MANAGEMENT_ROLES,
  newStaffingInterval,
} from "../../shiftPlanner/managementConstants";
import {
  buildManagementPayload,
  buildPlanningBlocks,
  buildPositionFlowDisplay,
  clockToHm,
  earlyMinutesBeforeTarget,
  formatManagementOutcome,
  getAdditionalForBlock,
  getBasePeopleForBlock,
  hmToClock,
  setBasePeopleForBlock,
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

function CompactNum({ label, value, onChange, min = 0, step = 1, suffix = "", width = 72 }) {
  const full = width === "100%";
  return (
    <TextField
      label={suffix ? `${label} (${suffix})` : label}
      type="number"
      size="small"
      fullWidth={full}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      inputProps={{ min, step }}
      sx={{
        ...fieldSx,
        width: full ? undefined : width,
        "& .MuiInputBase-input": { py: 0.6, fontSize: "0.85rem" },
      }}
    />
  );
}

function ClockField({ label, value, onChange }) {
  return (
    <PlanningTimePicker
      label={label}
      value={clockToHm(value)}
      onChange={(hm) => onChange(hmToClock(hm))}
      exactMinutes
      size="small"
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
              {isAdditional ? "Temporary staffing for this block" : "Base staffing for this block"}
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

function CompactSummary({ inputs, outcome, loading, hasStaffing }) {
  if (!hasStaffing) {
    return (
      <Box sx={{ ...stripSx, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography sx={{ fontWeight: 700, color: "text.secondary", fontSize: "0.95rem" }}>
            Add staffing to build the plan.
          </Typography>
          {loading ? <CircularProgress size={14} sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} /> : null}
        </Stack>
      </Box>
    );
  }
  if (!outcome) {
    return (
      <Box sx={{ ...stripSx, py: 1.5 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography sx={{ color: "text.secondary" }}>Running…</Typography>
          {loading ? <CircularProgress size={14} /> : null}
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
    <Box sx={stripSx}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={{ xs: 0.75, sm: 2 }}
        alignItems={{ xs: "flex-start", sm: "center" }}
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
        {loading ? <CircularProgress size={14} sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} /> : null}
      </Stack>
    </Box>
  );
}

function QueueBridge({ count, stageLabel }) {
  const n = Number(count) || 0;
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        px: { xs: 0.5, md: 0.75 },
        py: 0.25,
        minWidth: { xs: "100%", md: 72 },
        color: n > 0 ? VEEWASH_DASHBOARD.pendingDark : "text.disabled",
      }}
    >
      <Typography sx={{ fontSize: "0.68rem", fontWeight: 800, lineHeight: 1.2, textAlign: "center", letterSpacing: 0.2 }}>
        → {n} WAITING
      </Typography>
      <Typography sx={{ fontSize: "0.65rem", fontWeight: 700, lineHeight: 1.15, textAlign: "center" }}>
        TO {stageLabel} →
      </Typography>
    </Box>
  );
}

function StageCell({ display, highlight = false }) {
  if (!display) return null;
  return (
    <Box
      sx={{
        minWidth: { xs: "100%", md: 96 },
        flex: { md: "1 1 0" },
        px: 0.5,
        py: 0.5,
        borderRadius: 1,
        bgcolor: highlight ? "#fff7ed" : "transparent",
        textAlign: "center",
      }}
    >
      <Typography
        sx={{
          fontWeight: 800,
          fontSize: "0.68rem",
          letterSpacing: 0.5,
          color: "text.secondary",
          mb: 0.35,
        }}
      >
        {display.title}
      </Typography>
      <Stack direction="row" justifyContent="center" spacing={1.25} sx={{ mb: 0.2 }}>
        <Box sx={{ minWidth: 36 }}>
          <Typography sx={{ fontWeight: 800, fontSize: "1.15rem", lineHeight: 1.05 }}>
            {display.done}
          </Typography>
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: "0.58rem",
              letterSpacing: 0.4,
              color: "text.secondary",
              lineHeight: 1.1,
            }}
          >
            {display.doneLabel}
          </Typography>
        </Box>
        <Box sx={{ minWidth: 36 }}>
          <Typography sx={{ fontWeight: 800, fontSize: "1.15rem", lineHeight: 1.05 }}>
            {display.remaining}
          </Typography>
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: "0.58rem",
              letterSpacing: 0.4,
              color: "text.secondary",
              lineHeight: 1.1,
            }}
          >
            {display.remainingLabel}
          </Typography>
        </Box>
      </Stack>
      <Typography sx={{ fontSize: "0.68rem", color: "text.disabled", lineHeight: 1.2, fontWeight: 600 }}>
        {display.thisBlockLabel}
      </Typography>
    </Box>
  );
}

function PositionFlow({ block, targetBags, stallRole }) {
  const flow = buildPositionFlowDisplay(block, targetBags);
  if (!flow) {
    return (
      <Typography sx={{ fontSize: "0.85rem", color: "text.disabled", py: 0.5 }}>
        No flow yet for this block.
      </Typography>
    );
  }
  const washStall = stallRole === "washer";

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: { xs: "column", md: "row" },
        alignItems: { xs: "stretch", md: "center" },
        gap: { xs: 0.25, md: 0 },
        overflow: "hidden",
      }}
    >
      <StageCell display={flow.stages.weigh} />
      <QueueBridge count={flow.waiting.to_sort} stageLabel="SORT" />
      <StageCell display={flow.stages.sort} />
      <QueueBridge count={flow.waiting.to_wash} stageLabel="WASH" />
      <StageCell display={flow.stages.wash} highlight={washStall} />
      <QueueBridge count={flow.waiting.to_dry} stageLabel="DRY" />
      <StageCell display={flow.stages.dry} />
      <QueueBridge count={flow.waiting.to_fold} stageLabel="FOLD" />
      <StageCell display={flow.stages.fold} />
    </Box>
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
}) {
  const base = getBasePeopleForBlock(intervals, role.id, blockStart);
  const extras = getAdditionalForBlock(intervals, role.id, blockStart, blockEnd);

  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        py: 0.45,
        borderBottom: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
        "&:last-child": { borderBottom: 0 },
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
          aria-label={`Decrease ${role.label}`}
          onClick={() => onBaseChange(Math.max(0, base - 1))}
          sx={{ p: 0.35 }}
        >
          <RemoveIcon sx={{ fontSize: 16 }} />
        </IconButton>
        <Typography sx={{ width: 18, textAlign: "center", fontWeight: 800, fontSize: "0.95rem" }}>
          {base}
        </Typography>
        <IconButton
          size="small"
          aria-label={`Increase ${role.label}`}
          onClick={() => onBaseChange(base + 1)}
          sx={{ p: 0.35 }}
        >
          <AddIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Stack>

      <Typography sx={{ fontSize: "0.78rem", color: "text.secondary", flexShrink: 0 }}>
        {base > 0 ? `${blockStart}–${blockEnd}` : "—"}
      </Typography>

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
  );
}

function SectionLabel({ time, kind }) {
  return (
    <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 0.75 }}>
      <Typography sx={{ fontWeight: 800, fontSize: "0.95rem" }}>
        {time}
      </Typography>
      <Typography
        sx={{
          fontWeight: 800,
          fontSize: "0.72rem",
          letterSpacing: 0.6,
          color: kind === "staffing" ? VEEWASH_DASHBOARD.primaryBlue : "text.secondary",
        }}
      >
        — {kind === "staffing" ? "STAFFING" : "POSITION"}
      </Typography>
    </Stack>
  );
}

export default function ManagementPlannerBoard({ initialInputs = null } = {}) {
  const [inputs, setInputs] = useState(() => ({
    ...DEFAULT_MANAGEMENT_INPUTS,
    ...(initialInputs || {}),
  }));
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [draft, setDraft] = useState(null);
  const [modeLocked, setModeLocked] = useState(true);
  const debounceRef = useRef(null);
  const seqRef = useRef(0);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const planBlocks = useMemo(
    () => buildPlanningBlocks(inputs.start_time, inputs.target_time, inputs.planning_block_size_min),
    [inputs.start_time, inputs.target_time, inputs.planning_block_size_min],
  );

  const positionByEnd = useMemo(() => {
    const map = {};
    (result?.block_positions || []).forEach((b) => {
      map[b.block_end] = b;
      map[b.block_start] = b;
    });
    return map;
  }, [result]);

  const runSim = useCallback(async (nextInputs) => {
    const payloadInputs = nextInputs || inputs;
    const horizonEnd = payloadInputs.target_time;
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
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSim(inputs);
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [inputs]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasStaffing = (inputs.staffing_intervals || []).length > 0;
  const outcome = useMemo(
    () => (result && hasStaffing ? formatManagementOutcome({ ...result, inputs }) : null),
    [result, inputs, hasStaffing],
  );
  const targetBags = Number(inputs.bag_count) || 0;
  const stallRole = outcome?.firstBlockingRole || null;

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

  return (
    <Stack spacing={1.5}>
      {/* PLAN */}
      <Box sx={stripSx}>
        <Typography sx={{ fontWeight: 800, fontSize: "0.8rem", letterSpacing: 0.4, color: "text.secondary", mb: 1 }}>
          PLAN
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)", md: "1.1fr 1.2fr 1.2fr 1fr 0.9fr 0.9fr" },
            gap: 1,
          }}
        >
          <CompactNum
            label="Target bags"
            value={inputs.bag_count}
            onChange={(v) => onChange("bag_count", v)}
            min={1}
            width="100%"
          />
          <ClockField
            label="Start time"
            value={inputs.start_time}
            onChange={(v) => onChange("start_time", v)}
          />
          <ClockField
            label="Target finish"
            value={inputs.target_time}
            onChange={(v) => onChange("target_time", v)}
          />
          <FormControl size="small" fullWidth>
            <InputLabel>Block size</InputLabel>
            <Select
              label="Block size"
              value={inputs.planning_block_size_min}
              onChange={(e) => onChange("planning_block_size_min", Number(e.target.value))}
              sx={{ bgcolor: "#fff" }}
            >
              {BLOCK_SIZE_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <CompactNum
            label="Washers"
            value={inputs.washer_count}
            onChange={(v) => onChange("washer_count", v)}
            min={1}
            width="100%"
          />
          <CompactNum
            label="Dryers"
            value={inputs.dryer_count}
            onChange={(v) => onChange("dryer_count", v)}
            min={1}
            width="100%"
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
          <CompactNum label="Weigh" value={inputs.weigh_sec_per_bag} onChange={(v) => onChange("weigh_sec_per_bag", v)} min={1} suffix="s" width={84} />
          <CompactNum label="Sort" value={inputs.sort_min_per_bag} onChange={(v) => onChange("sort_min_per_bag", v)} min={0} step={0.5} suffix="m" width={84} />
          <CompactNum label="Wash labor" value={inputs.load_washer_min} onChange={(v) => onChange("load_washer_min", v)} min={0} step={0.5} suffix="m" width={96} />
          <CompactNum label="Wash cycle" value={inputs.wash_cycle_min} onChange={(v) => onChange("wash_cycle_min", v)} min={1} suffix="m" width={96} />
          <CompactNum label="Dry labor" value={inputs.load_dryer_min} onChange={(v) => onChange("load_dryer_min", v)} min={0} step={0.5} suffix="m" width={92} />
          <CompactNum label="Dry cycle" value={inputs.dry_cycle_min} onChange={(v) => onChange("dry_cycle_min", v)} min={1} suffix="m" width={92} />
          <CompactNum label="Fold" value={inputs.fold_min_per_bag} onChange={(v) => onChange("fold_min_per_bag", v)} min={0} step={0.5} suffix="m" width={84} />
        </Stack>
        <Typography sx={{ mt: 0.75, fontSize: "0.78rem", color: "text.secondary" }}>
          Machines · Washers {inputs.washer_count} · Dryers {inputs.dryer_count}
        </Typography>
      </Box>

      <CompactSummary
        inputs={inputs}
        outcome={outcome}
        loading={loading}
        hasStaffing={hasStaffing}
      />

      {error ? <Alert severity="error" sx={{ py: 0.5 }}>{error}</Alert> : null}

      {/* Block sequence: STAFFING → POSITION */}
      <Stack spacing={1.25}>
        {planBlocks.map((pb) => {
          const pos = positionByEnd[pb.block_end] || null;
          const blockStall = hasStaffing && stallRole ? stallRole : null;
          return (
            <Box key={`${pb.block_start}-${pb.block_end}`}>
              <Box sx={{ ...stripSx, py: 1 }}>
                <SectionLabel time={pb.block_start} kind="staffing" />
                {MANAGEMENT_ROLES.map((role) => (
                  <BlockRoleRow
                    key={role.id}
                    role={role}
                    blockStart={pb.block_start}
                    blockEnd={pb.block_end}
                    intervals={inputs.staffing_intervals}
                    onBaseChange={(n) => changeBase(role.id, pb.block_start, pb.block_end, n)}
                    onAddTemporary={(roleId) => openTemporary(roleId, pb.block_start, pb.block_end)}
                    onEdit={openEdit}
                    onRemove={removeInterval}
                  />
                ))}
              </Box>

              <Box sx={{ textAlign: "center", py: 0.35, color: "text.disabled", fontSize: "0.85rem" }}>
                ↓
              </Box>

              <Box sx={stripSx}>
                <SectionLabel time={pb.block_end} kind="position" />
                {hasStaffing ? (
                  <PositionFlow block={pos} targetBags={targetBags} stallRole={blockStall} />
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
