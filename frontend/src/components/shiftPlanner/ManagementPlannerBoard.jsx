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
  formatBlockStaffingLine,
  formatDeficitLines,
  formatIntervalLine,
  formatManagementOutcome,
  formatStageProgress,
  intervalsForRole,
  validateStaffingIntervals,
} from "../../shiftPlanner/managementHelpers";

const fieldSx = {
  "& .MuiOutlinedInput-root": { bgcolor: "#fff" },
  "& .MuiInputBase-input": { py: 1 },
};

function OutcomeBanner({ outcome }) {
  if (!outcome) return null;
  const colors = {
    success: { bg: VEEWASH_DASHBOARD.tealLight, border: VEEWASH_DASHBOARD.tealBorder, fg: VEEWASH_DASHBOARD.tealDark },
    warning: { bg: VEEWASH_DASHBOARD.pendingLight, border: VEEWASH_DASHBOARD.pendingBorder, fg: VEEWASH_DASHBOARD.pendingDark },
    neutral: { bg: "#fff7ed", border: "rgba(180, 83, 9, 0.35)", fg: "#9a3412" },
  };
  const c = colors[outcome.tone] || colors.neutral;
  return (
    <Box
      sx={{
        bgcolor: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 1.5,
        px: 2.5,
        py: 2,
      }}
    >
      <Typography sx={{ fontWeight: 800, fontSize: "1.35rem", color: c.fg, lineHeight: 1.25 }}>
        {outcome.title}
      </Typography>
      {outcome.detail ? (
        <Typography sx={{ mt: 0.75, color: "text.secondary", fontWeight: 500 }}>{outcome.detail}</Typography>
      ) : null}
    </Box>
  );
}

function WaitingChip({ label, count }) {
  const n = Number(count) || 0;
  if (n <= 0) {
    return (
      <Typography component="span" sx={{ color: "text.disabled", fontSize: "0.85rem", mr: 1.5 }}>
        {label} 0
      </Typography>
    );
  }
  return (
    <Box
      component="span"
      sx={{
        display: "inline-block",
        bgcolor: VEEWASH_DASHBOARD.pendingLight,
        border: `1px solid ${VEEWASH_DASHBOARD.pendingBorder}`,
        color: VEEWASH_DASHBOARD.pendingDark,
        fontWeight: 700,
        fontSize: "0.85rem",
        px: 1,
        py: 0.25,
        borderRadius: 1,
        mr: 1,
        mb: 0.5,
      }}
    >
      {label} {n}
    </Box>
  );
}

function StaffingIntervalDialog({ open, draft, onClose, onSave, shiftStart, shiftEnd, existing }) {
  const [local, setLocal] = useState(draft);
  const [error, setError] = useState("");

  useEffect(() => {
    setLocal(draft);
    setError("");
  }, [draft, open]);

  const save = () => {
    const nextList = existing.map((row) => (row.id === local.id ? local : row));
    if (!existing.some((row) => row.id === local.id)) nextList.push(local);
    const v = validateStaffingIntervals(nextList, { startTime: shiftStart, endTime: shiftEnd });
    if (!v.ok) {
      const hit = v.errors.find((e) => e.intervalId === local.id) || v.errors[0];
      setError(hit?.message || "Invalid staffing interval");
      return;
    }
    onSave(local);
  };

  if (!local) return null;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ fontWeight: 800 }}>
        {existing.some((r) => r.id === local.id) ? "Edit staffing" : "Add staffing"}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 1 }}>
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
            <TextField
              label="Start"
              size="small"
              fullWidth
              value={local.start}
              onChange={(e) => setLocal((p) => ({ ...p, start: e.target.value }))}
              placeholder="9:15 AM"
              sx={fieldSx}
            />
            <TextField
              label="End"
              size="small"
              fullWidth
              value={local.end}
              onChange={(e) => setLocal((p) => ({ ...p, end: e.target.value }))}
              placeholder="10:00 AM"
              sx={fieldSx}
            />
          </Stack>
          <FormControl fullWidth size="small">
            <InputLabel>Type</InputLabel>
            <Select
              label="Type"
              value={local.mode}
              onChange={(e) => setLocal((p) => ({ ...p, mode: e.target.value }))}
            >
              <MenuItem value="base">Base</MenuItem>
              <MenuItem value="additional">Additional</MenuItem>
            </Select>
          </FormControl>
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

function RoleStaffingSection({ role, intervals, onAdd, onEdit, onRemove }) {
  const rows = intervalsForRole(intervals, role.id);
  const bases = rows.filter((r) => String(r.mode).toLowerCase() !== "additional");
  const extras = rows.filter((r) => String(r.mode).toLowerCase() === "additional");

  return (
    <Box
      sx={{
        borderBottom: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
        py: 1.25,
        "&:last-child": { borderBottom: 0 },
      }}
    >
      <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={1}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontWeight: 800, letterSpacing: 0.4, fontSize: "0.8rem", color: "text.secondary" }}>
            {role.label.toUpperCase()}
          </Typography>
          {!rows.length ? (
            <Typography sx={{ color: "text.disabled", fontSize: "0.9rem", mt: 0.25 }}>No staffing</Typography>
          ) : (
            <Stack spacing={0.35} sx={{ mt: 0.35 }}>
              {[...bases, ...extras].map((row) => (
                <Stack key={row.id} direction="row" alignItems="center" spacing={0.5}>
                  <Typography sx={{ fontSize: "0.95rem", fontWeight: 600, flex: 1 }}>
                    {formatIntervalLine(row)}
                  </Typography>
                  <IconButton size="small" aria-label="Edit staffing" onClick={() => onEdit(row)}>
                    <EditOutlinedIcon fontSize="small" />
                  </IconButton>
                  <IconButton size="small" aria-label="Remove staffing" onClick={() => onRemove(row.id)}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
            </Stack>
          )}
        </Box>
        <Button
          size="small"
          startIcon={<AddIcon />}
          onClick={() => onAdd(role.id)}
          sx={{ textTransform: "none", fontWeight: 700, flexShrink: 0 }}
        >
          Add
        </Button>
      </Stack>
    </Box>
  );
}

function BlockCard({ block }) {
  const notYet = Number(block.not_yet_weighed) || 0;
  const waiting = [
    ["Not yet weighed", notYet],
    ["Waiting to Sort", block.waiting_to_sort],
    ["Waiting to Wash", block.waiting_to_wash],
    ["Waiting to Dry", block.waiting_to_dry],
    ["Waiting to Fold", block.waiting_to_fold],
  ];
  const hasQueue = waiting.some(([, n]) => (Number(n) || 0) > 0);

  return (
    <Box
      sx={{
        bgcolor: "#fff",
        border: `1px solid ${hasQueue ? VEEWASH_DASHBOARD.pendingBorder : VEEWASH_DASHBOARD.snapshotBorder}`,
        borderRadius: 1.5,
        px: 2,
        py: 1.5,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Typography sx={{ fontWeight: 800, mb: 0.5 }}>
        {block.block_start} – {block.block_end}
      </Typography>
      <Typography sx={{ fontSize: "0.88rem", color: "text.secondary", mb: 1.25 }}>
        {formatBlockStaffingLine(block.staffing)}
      </Typography>

      <Stack spacing={0.35} sx={{ mb: 1.25 }}>
        <Typography sx={{ fontSize: "0.92rem" }}>
          {formatStageProgress("Weighed", block.weighed_total, block.weighed_this_block)}
        </Typography>
        <Typography sx={{ fontSize: "0.92rem" }}>
          {formatStageProgress("Sorted", block.sorted_total, block.sorted_this_block)}
        </Typography>
        <Typography sx={{ fontSize: "0.92rem" }}>
          {formatStageProgress("Washed", block.washed_total, block.washed_this_block)}
        </Typography>
        <Typography sx={{ fontSize: "0.92rem" }}>
          {formatStageProgress("Dried", block.dried_total, block.dried_this_block)}
        </Typography>
        <Typography sx={{ fontSize: "0.92rem" }}>
          {formatStageProgress("Folded", block.folded_total ?? block.completed_total, block.folded_this_block ?? block.completed_this_block)}
        </Typography>
      </Stack>

      <Box sx={{ mb: 0.75 }}>
        {waiting.map(([label, n]) => (
          <WaitingChip key={label} label={label} count={n} />
        ))}
      </Box>

      {((Number(block.in_wash_cycle) || 0) > 0 || (Number(block.in_dry_cycle) || 0) > 0) ? (
        <Typography sx={{ fontSize: "0.85rem", color: "text.secondary" }}>
          {[
            (Number(block.in_wash_cycle) || 0) > 0 ? `In Wash Cycle ${block.in_wash_cycle}` : null,
            (Number(block.in_dry_cycle) || 0) > 0 ? `In Dry Cycle ${block.in_dry_cycle}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </Typography>
      ) : null}
    </Box>
  );
}

export default function ManagementPlannerBoard({ initialInputs = null } = {}) {
  const [inputs, setInputs] = useState(() => initialInputs || DEFAULT_MANAGEMENT_INPUTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [clientErrors, setClientErrors] = useState([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [draft, setDraft] = useState(null);
  const debounceRef = useRef(null);
  const seqRef = useRef(0);

  const onChange = useCallback((key, value) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }, []);

  const runSim = useCallback(async (nextInputs) => {
    const payloadInputs = nextInputs || inputs;
    const client = validateStaffingIntervals(payloadInputs.staffing_intervals, {
      startTime: payloadInputs.start_time,
      endTime: payloadInputs.end_time,
    });
    setClientErrors(client.errors.map((e) => e.message));
    // Still call backend when client validation fails only if intervals empty of hard errors?
    // Prefer: block network when client invalid to avoid noise; empty plan is valid.
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
      // API wraps DES under des.*; prefer promoted top-level management fields.
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
        setError((res.data.validation_errors || []).map((e) => (typeof e === "string" ? e : e.message || e.code)).join(" · "));
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

  // Debounced auto-run on input changes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSim(inputs);
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [inputs]); // eslint-disable-line react-hooks/exhaustive-deps

  const outcome = useMemo(
    () => (result ? formatManagementOutcome({ ...result, inputs }) : null),
    [result, inputs],
  );
  const deficitLines = useMemo(
    () => formatDeficitLines(result?.staffing_deficits || []),
    [result],
  );
  const blocks = result?.block_positions || [];

  const openAdd = (roleId) => {
    setDraft(
      newStaffingInterval(roleId, {
        start: inputs.start_time,
        end: inputs.target_time,
        mode: "base",
      }),
    );
    setDialogOpen(true);
  };

  const openEdit = (row) => {
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

  return (
    <Stack spacing={2}>
      {/* Plan */}
      <Box
        sx={{
          bgcolor: "#fff",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
          borderRadius: 1.5,
          px: 2,
          py: 1.75,
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Typography sx={{ fontWeight: 800, mb: 1.25 }}>Plan</Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(5, 1fr)" },
            gap: 1.25,
          }}
        >
          <TextField
            label="Target bags"
            type="number"
            size="small"
            value={inputs.bag_count}
            onChange={(e) => onChange("bag_count", e.target.value)}
            inputProps={{ min: 1 }}
            sx={fieldSx}
          />
          <TextField
            label="Shift start"
            size="small"
            value={inputs.start_time}
            onChange={(e) => onChange("start_time", e.target.value)}
            sx={fieldSx}
          />
          <TextField
            label="Target time"
            size="small"
            value={inputs.target_time}
            onChange={(e) => onChange("target_time", e.target.value)}
            sx={fieldSx}
          />
          <TextField
            label="Shift end"
            size="small"
            value={inputs.end_time}
            onChange={(e) => onChange("end_time", e.target.value)}
            helperText="Staffing cannot extend past this"
            FormHelperTextProps={{ sx: { mx: 0 } }}
            sx={fieldSx}
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
        </Box>
      </Box>

      {/* Staffing */}
      <Box
        sx={{
          bgcolor: "#fff",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
          borderRadius: 1.5,
          px: 2,
          py: 1.5,
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 0.5 }}>
          <Typography sx={{ fontWeight: 800 }}>Staffing</Typography>
          <Typography sx={{ fontSize: "0.8rem", color: "text.secondary" }}>
            Exact times · Base + Additional · no named employees
          </Typography>
        </Stack>
        {MANAGEMENT_ROLES.map((role) => (
          <RoleStaffingSection
            key={role.id}
            role={role}
            intervals={inputs.staffing_intervals}
            onAdd={openAdd}
            onEdit={openEdit}
            onRemove={removeInterval}
          />
        ))}
      </Box>

      {error ? <Alert severity="error">{error}</Alert> : null}
      {clientErrors.length > 1 ? (
        <Alert severity="warning">{clientErrors.slice(0, 3).join(" · ")}</Alert>
      ) : null}

      {/* Outcome */}
      <Box>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 800 }}>Outcome</Typography>
          {loading ? <CircularProgress size={16} sx={{ color: VEEWASH_DASHBOARD.primaryBlue }} /> : null}
        </Stack>
        {outcome ? <OutcomeBanner outcome={outcome} /> : (
          <Typography color="text.secondary">Run a plan to see results.</Typography>
        )}
        {deficitLines.length ? (
          <Stack spacing={0.5} sx={{ mt: 1.25 }}>
            {deficitLines.map((line) => (
              <Typography key={line} sx={{ fontSize: "0.9rem", color: "text.secondary" }}>
                {line}
              </Typography>
            ))}
          </Stack>
        ) : null}
      </Box>

      {/* Timeline */}
      <Box>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>Timeline</Typography>
        {!blocks.length && !loading ? (
          <Typography color="text.secondary">No block positions yet.</Typography>
        ) : (
          <Stack spacing={1.25}>
            {blocks.map((block) => (
              <BlockCard key={`${block.block_start}-${block.block_end}`} block={block} />
            ))}
          </Stack>
        )}
      </Box>

      <StaffingIntervalDialog
        open={dialogOpen}
        draft={draft}
        existing={inputs.staffing_intervals}
        shiftStart={inputs.start_time}
        shiftEnd={inputs.end_time}
        onClose={() => setDialogOpen(false)}
        onSave={saveInterval}
      />
    </Stack>
  );
}
