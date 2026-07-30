import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
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
import CloseIcon from "@mui/icons-material/Close";
import { calculateProcessFlowIntervals } from "../api";
import { formatDateTime } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const DEFAULT_DRY = 40;
const DEFAULT_SORT = 0;
const DEFAULT_WASH = 0;
const MAX_SLOTS = 48;

function pad2(n) {
  return String(n).padStart(2, "0");
}

function parseTimeOnDate(dateEt, hhmm) {
  const raw = String(hhmm || "").trim();
  if (!raw || !dateEt) return null;
  const match = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) return null;
  const h = Number(match[1]);
  const m = Number(match[2]);
  const s = Number(match[3] || 0);
  if (h > 23 || m > 59 || s > 59) return null;
  return `${dateEt}T${pad2(h)}:${pad2(m)}:${pad2(s)}`;
}

function requireIntegerString(raw, { min, max, field }) {
  const text = String(raw ?? "").trim();
  if (!text) return { ok: false, error: `${field} is required.` };
  if (!/^-?\d+$/.test(text)) {
    return { ok: false, error: `${field} must be an integer.` };
  }
  const n = Number(text);
  if (!Number.isInteger(n) || n < min || n > max) {
    return { ok: false, error: `${field} must be between ${min} and ${max}.` };
  }
  return { ok: true, value: n };
}

function evenlySpaceTimes(startHhmm, endHhmm, slotCount) {
  const n = Number(slotCount);
  if (!Number.isFinite(n) || n < 1) return null;
  const startParts = String(startHhmm || "").match(/^(\d{1,2}):(\d{2})$/);
  const endParts = String(endHhmm || "").match(/^(\d{1,2}):(\d{2})$/);
  if (!startParts || !endParts) return null;
  const startMin = Number(startParts[1]) * 60 + Number(startParts[2]);
  const endMin = Number(endParts[1]) * 60 + Number(endParts[2]);
  if (endMin <= startMin) return null; // no silent overnight wrap
  if (n === 1) return [`${pad2(Math.floor(startMin / 60))}:${pad2(startMin % 60)}`];
  const step = (endMin - startMin) / (n - 1);
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const total = Math.round(startMin + step * i);
    out.push(`${pad2(Math.floor(total / 60))}:${pad2(total % 60)}`);
  }
  out[out.length - 1] = `${pad2(Math.floor(endMin / 60))}:${pad2(endMin % 60)}`;
  return out;
}

function validateSlotOrder(slotTimes) {
  for (let i = 1; i < slotTimes.length; i += 1) {
    const prev = slotTimes[i - 1];
    const curr = slotTimes[i];
    if (!prev || !curr) continue;
    if (curr <= prev) {
      return `Slot ${i + 1} must be later than Slot ${i}. Checkpoint times must be in chronological order.`;
    }
  }
  return "";
}

function DetailDialog({ open, onClose, title, columns, bags }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ pr: 6, position: "relative" }}>
        {title}
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: "absolute", right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {!bags?.length ? (
          <Typography variant="body2" color="text.secondary">
            No bags in this interval.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: "grey.50" }}>
                {columns.map((c) => (
                  <TableCell key={c.key} sx={{ fontWeight: 700 }}>
                    {c.label}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {bags.map((bag, idx) => (
                <TableRow key={`${bag.bag_id}-${idx}`} hover>
                  {columns.map((c) => (
                    <TableCell key={c.key}>
                      {c.format ? c.format(bag[c.key], bag) : bag[c.key] || "—"}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function ProcessFlowAvailabilityCalculator({ dateEt, disabled = false }) {
  const [slotCount, setSlotCount] = useState(3);
  const [sortMins, setSortMins] = useState(String(DEFAULT_SORT));
  const [washMins, setWashMins] = useState(String(DEFAULT_WASH));
  const [dryMins, setDryMins] = useState(String(DEFAULT_DRY));
  const [slotTimes, setSlotTimes] = useState(() => Array(3).fill(""));
  const [spaceStart, setSpaceStart] = useState("");
  const [spaceEnd, setSpaceEnd] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState(null);
  const [viewDetail, setViewDetail] = useState(null);

  useEffect(() => {
    setResults(null);
    setError("");
    setViewDetail(null);
  }, [dateEt]);

  const orderError = useMemo(() => validateSlotOrder(slotTimes), [slotTimes]);

  const handleSlotCountChange = (raw) => {
    const n = Math.max(1, Math.min(MAX_SLOTS, Number.parseInt(String(raw), 10) || 1));
    setSlotCount(n);
    setSlotTimes((prev) => {
      const next = prev.slice(0, n);
      while (next.length < n) next.push("");
      return next;
    });
    setResults(null);
  };

  const handleReset = () => {
    setSortMins(String(DEFAULT_SORT));
    setWashMins(String(DEFAULT_WASH));
    setDryMins(String(DEFAULT_DRY));
    setSlotTimes(Array(slotCount).fill(""));
    setSpaceStart("");
    setSpaceEnd("");
    setError("");
    setResults(null);
    setViewDetail(null);
  };

  const handleEvenlySpace = () => {
    const spaced = evenlySpaceTimes(spaceStart, spaceEnd, slotCount);
    if (!spaced) {
      setError("Enter Start/End times with End later than Start (no overnight wrap).");
      return;
    }
    setError("");
    setSlotTimes(spaced);
    setResults(null);
  };

  const handleCalculate = async () => {
    setError("");
    const sort = requireIntegerString(sortMins, { min: 0, max: 1440, field: "Sort Assumption (Minutes)" });
    const wash = requireIntegerString(washMins, { min: 0, max: 1440, field: "Wash Assumption (Minutes)" });
    const dry = requireIntegerString(dryMins, { min: 1, max: 1440, field: "Dry Assumption (Minutes)" });
    if (!sort.ok || !wash.ok || !dry.ok) {
      setError(sort.error || wash.error || dry.error);
      return;
    }
    if (slotTimes.some((t) => !String(t || "").trim())) {
      setError("Enter a checkpoint time for every slot.");
      return;
    }
    const orderMsg = validateSlotOrder(slotTimes);
    if (orderMsg) {
      setError(orderMsg);
      return;
    }
    if (!dateEt) {
      setError("Select an ET operations date first.");
      return;
    }
    const checkpoints = slotTimes.map((t) => parseTimeOnDate(dateEt, t));
    if (checkpoints.some((c) => !c)) {
      setError("Each checkpoint must be a valid time (HH:MM).");
      return;
    }
    setLoading(true);
    try {
      const res = await calculateProcessFlowIntervals({
        date_et: dateEt,
        checkpoints,
        sort_assumption_minutes: sort.value,
        wash_assumption_minutes: wash.value,
        dry_assumption_minutes: dry.value,
      });
      setResults(res?.data || null);
    } catch (err) {
      setError(String(err?.response?.data?.error || err?.message || "Calculation failed."));
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const sections = results?.sections || [];
  const detailColumnsBySection = {
    ready_for_washing: [
      { key: "bag_id", label: "Bag ID" },
      { key: "sort_employee", label: "Sort Employee" },
      { key: "sort_scan_et", label: "Sort Scan Time ET", format: formatDateTime },
      { key: "sort_machine_rack", label: "Sort Machine/Rack" },
      { key: "ready_for_washing_et", label: "Ready-for-Washing Time ET", format: formatDateTime },
      { key: "confidence", label: "Confidence" },
    ],
    ready_for_drying: [
      { key: "bag_id", label: "Bag ID" },
      { key: "wash_employee", label: "Wash Employee" },
      { key: "wash_scan_et", label: "Wash Scan Time ET", format: formatDateTime },
      { key: "washer", label: "Washer" },
      { key: "ready_for_drying_et", label: "Ready-for-Drying Time ET", format: formatDateTime },
      { key: "confidence", label: "Confidence" },
    ],
    ready_for_folding: [
      { key: "bag_id", label: "Bag ID" },
      { key: "dry_employee", label: "Dry Employee" },
      { key: "dry_scan_et", label: "Dry Scan Time ET", format: formatDateTime },
      { key: "dryer", label: "Dryer" },
      { key: "ready_for_folding_et", label: "Ready-for-Folding Time ET", format: formatDateTime },
      { key: "confidence", label: "Confidence" },
    ],
  };

  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.5,
        mb: 2,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "rgba(25, 71, 149, 0.02)",
      }}
    >
      <Typography variant="subtitle1" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue} sx={{ mb: 0.5 }}>
        Stage Availability Calculator
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Sort and Wash minutes are planning assumptions (no configured operational duration — default 0).
        Dry minutes use the Scan Chronology Ready-to-Fold assumption (default 40), not the organization
        processing setting (45).
      </Typography>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <TextField
          size="small"
          type="number"
          label="Number of Time Slots"
          value={slotCount}
          onChange={(e) => handleSlotCountChange(e.target.value)}
          inputProps={{ min: 1, max: MAX_SLOTS, step: 1 }}
          disabled={disabled || loading}
          sx={{ minWidth: 160 }}
        />
        <TextField
          size="small"
          label="Sort Assumption (Minutes)"
          value={sortMins}
          onChange={(e) => {
            setSortMins(e.target.value);
            setResults(null);
          }}
          helperText="No configured assumption — 0 minutes"
          disabled={disabled || loading}
          sx={{ minWidth: 200 }}
        />
        <TextField
          size="small"
          label="Wash Assumption (Minutes)"
          value={washMins}
          onChange={(e) => {
            setWashMins(e.target.value);
            setResults(null);
          }}
          helperText="No configured assumption — 0 minutes"
          disabled={disabled || loading}
          sx={{ minWidth: 200 }}
        />
        <TextField
          size="small"
          label="Dry Assumption (Minutes)"
          value={dryMins}
          onChange={(e) => {
            setDryMins(e.target.value);
            setResults(null);
          }}
          helperText="Ready-to-Fold assumption (default 40)"
          disabled={disabled || loading}
          sx={{ minWidth: 200 }}
        />
        <Button
          size="small"
          variant="contained"
          onClick={handleCalculate}
          disabled={disabled || loading}
          sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}
        >
          {loading ? <CircularProgress size={16} color="inherit" /> : "Calculate"}
        </Button>
        <Button size="small" variant="outlined" onClick={handleReset} disabled={loading}>
          Reset
        </Button>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }} alignItems={{ sm: "center" }}>
        <Typography variant="body2" fontWeight={600}>
          Evenly Space Times
        </Typography>
        <TextField
          size="small"
          type="time"
          label="Start Time"
          value={spaceStart}
          onChange={(e) => setSpaceStart(e.target.value)}
          InputLabelProps={{ shrink: true }}
          inputProps={{ step: 60 }}
          disabled={disabled || loading}
        />
        <TextField
          size="small"
          type="time"
          label="End Time"
          value={spaceEnd}
          onChange={(e) => setSpaceEnd(e.target.value)}
          InputLabelProps={{ shrink: true }}
          inputProps={{ step: 60 }}
          disabled={disabled || loading}
        />
        <Button size="small" variant="outlined" onClick={handleEvenlySpace} disabled={disabled || loading}>
          Apply spacing
        </Button>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        {slotTimes.map((value, idx) => (
          <TextField
            key={`pf-slot-${idx}`}
            size="small"
            type="time"
            label={`Slot ${idx + 1}`}
            value={value}
            onChange={(e) => {
              setSlotTimes((prev) => {
                const next = [...prev];
                next[idx] = e.target.value;
                return next;
              });
              setResults(null);
            }}
            InputLabelProps={{ shrink: true }}
            inputProps={{ step: 60 }}
            disabled={disabled || loading}
            error={Boolean(orderError) && idx > 0 && value && slotTimes[idx - 1] && value <= slotTimes[idx - 1]}
          />
        ))}
      </Stack>

      {orderError ? (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {orderError}
        </Alert>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {sections.map((section) => (
        <Box key={section.id} sx={{ mt: 2 }}>
          <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
            {section.label}
          </Typography>
          <Collapse in={Boolean(section.slots?.length)}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}>
                    {["Slot", "Checkpoint Time", "Interval", "New Bags Ready", "Cumulative Bags Ready", "View Bags"].map(
                      (h) => (
                        <TableCell key={h} sx={{ color: "#fff", fontWeight: 700 }} align={h.includes("Bags Ready") ? "right" : "left"}>
                          {h}
                        </TableCell>
                      ),
                    )}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(section.slots || []).map((slot) => (
                    <Fragment key={`${section.id}-${slot.slot}`}>
                      <TableRow hover>
                        <TableCell>{slot.slot}</TableCell>
                        <TableCell>{slot.checkpoint_label}</TableCell>
                        <TableCell>{slot.interval_label}</TableCell>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>
                          {slot.newly_ready_count ?? 0}
                        </TableCell>
                        <TableCell align="right">{slot.cumulative_ready_count ?? 0}</TableCell>
                        <TableCell>
                          <Box
                            component="button"
                            type="button"
                            disabled={!slot.newly_ready_count}
                            onClick={() =>
                              setViewDetail({
                                sectionId: section.id,
                                title: `${section.label} — Slot ${slot.slot}`,
                                bags: slot.bags || [],
                              })
                            }
                            sx={{
                              border: 0,
                              background: "none",
                              p: 0,
                              color: VEEWASH_DASHBOARD.primaryBlue,
                              fontWeight: 700,
                              cursor: slot.newly_ready_count ? "pointer" : "default",
                              opacity: slot.newly_ready_count ? 1 : 0.45,
                              fontSize: "0.875rem",
                            }}
                          >
                            View {slot.newly_ready_count ?? 0} Bag{(slot.newly_ready_count ?? 0) === 1 ? "" : "s"}
                          </Box>
                        </TableCell>
                      </TableRow>
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Collapse>
        </Box>
      ))}

      <DetailDialog
        open={Boolean(viewDetail)}
        onClose={() => setViewDetail(null)}
        title={viewDetail?.title || ""}
        columns={detailColumnsBySection[viewDetail?.sectionId] || []}
        bags={viewDetail?.bags || []}
      />
    </Paper>
  );
}
