import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
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
import { calculateProcessFlowIntervals, getProcessingSettings } from "../api";
import { formatDateTime } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const DEFAULT_SORT = 10; // temporary Process Flow operational default
const DEFAULT_WASH_FALLBACK = 30; // matches org washing_minutes default
const DEFAULT_DRY = 40;
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
  if (endMin <= startMin) return null;
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

function statusChipColor(status) {
  if (status === "deficit") return "warning";
  if (status === "capacity_available") return "info";
  if (status === "balanced") return "success";
  return "default";
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
            No bags in this selection.
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
                      {c.format ? c.format(bag[c.key], bag) : bag[c.key] ?? "—"}
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

const AVAILABLE_COLS = [
  { key: "bag_id", label: "Bag ID" },
  { key: "arrival_time_et", label: "Available At ET", format: formatDateTime },
  { key: "arrival_employee", label: "Employee" },
  { key: "arrival_machine", label: "Machine/Rack" },
  { key: "departure_time_et", label: "Downstream Time ET", format: formatDateTime },
  { key: "sequence_status", label: "Sequence Status" },
];

const PROCESSED_COLS = [
  { key: "bag_id", label: "Bag ID" },
  { key: "arrival_time_et", label: "Available At ET", format: formatDateTime },
  { key: "processing_time_et", label: "Processing Time ET", format: formatDateTime },
  { key: "processing_employee", label: "Employee" },
  { key: "processing_machine", label: "Machine" },
  { key: "queue_wait_minutes", label: "Queue Wait (min)" },
  { key: "sequence_status", label: "Sequence Status" },
];

const WAITING_COLS = [
  { key: "bag_id", label: "Bag ID" },
  { key: "available_since_et", label: "Available Since ET", format: formatDateTime },
  { key: "minutes_waiting", label: "Minutes Waiting" },
  { key: "upstream_employee", label: "Upstream Employee" },
  { key: "upstream_machine", label: "Upstream Machine/Rack" },
  { key: "later_processing_time_et", label: "Later Processing Time ET", format: formatDateTime },
  { key: "sequence_status", label: "Sequence Status" },
];

export default function ProcessFlowAvailabilityCalculator({ dateEt, disabled = false }) {
  const [slotCount, setSlotCount] = useState(3);
  const [sortMins, setSortMins] = useState(String(DEFAULT_SORT));
  const [washMins, setWashMins] = useState(String(DEFAULT_WASH_FALLBACK));
  const [washDefault, setWashDefault] = useState(DEFAULT_WASH_FALLBACK);
  const [dryMins, setDryMins] = useState(String(DEFAULT_DRY));
  const [slotTimes, setSlotTimes] = useState(() => Array(3).fill(""));
  const [spaceStart, setSpaceStart] = useState("");
  const [spaceEnd, setSpaceEnd] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState(null);
  const [viewDetail, setViewDetail] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getProcessingSettings();
        const orgWash = Number(res?.data?.washing_minutes);
        if (!cancelled && Number.isFinite(orgWash) && orgWash >= 0) {
          setWashDefault(orgWash);
          setWashMins(String(orgWash));
        }
      } catch {
        // Keep fallback 30 — calculator backend also defaults from washing_minutes.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
    setWashMins(String(washDefault));
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
    const sort = requireIntegerString(sortMins, { min: 0, max: 1440, field: "Sort Duration (Minutes)" });
    const wash = requireIntegerString(washMins, { min: 0, max: 1440, field: "Wash Duration (Minutes)" });
    const dry = requireIntegerString(dryMins, { min: 1, max: 1440, field: "Dry Duration (Minutes)" });
    if (!sort.ok || !wash.ok || !dry.ok) {
      setError(sort.error || wash.error || dry.error);
      return;
    }
    if (!String(spaceStart || "").trim()) {
      setError("Enter Start Time. Slot 1 interval starts at Start Time (not midnight).");
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
    if (slotTimes[0] && spaceStart >= slotTimes[0]) {
      setError("Start Time must be earlier than Slot 1 checkpoint.");
      return;
    }
    const startTime = parseTimeOnDate(dateEt, spaceStart);
    const checkpoints = slotTimes.map((t) => parseTimeOnDate(dateEt, t));
    if (!startTime || checkpoints.some((c) => !c)) {
      setError("Start Time and each checkpoint must be valid times (HH:MM).");
      return;
    }
    setLoading(true);
    try {
      const res = await calculateProcessFlowIntervals({
        date_et: dateEt,
        start_time: startTime,
        checkpoints,
        sort_duration_minutes: sort.value,
        wash_duration_minutes: wash.value,
        dry_duration_minutes: dry.value,
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
        Inter-Stage Queue Calculator
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Durations are applied to actual stage start scans to calculate when bags become available for
        the next stage. Queue departures use actual Wash START, Dry START, and Folding Completion.
        Dry Duration default 40 is not the organization Dryer Time (45). Work-Starved Minutes measure
        queue availability only — not employee idle time.
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
          label="Sort Duration (Minutes)"
          value={sortMins}
          onChange={(e) => {
            setSortMins(e.target.value);
            setResults(null);
          }}
          helperText="Default operational assumption (10)"
          disabled={disabled || loading}
          sx={{ minWidth: 200 }}
        />
        <TextField
          size="small"
          label="Wash Duration (Minutes)"
          value={washMins}
          onChange={(e) => {
            setWashMins(e.target.value);
            setResults(null);
          }}
          helperText={`From org Wash Time (prefill ${washDefault})`}
          disabled={disabled || loading}
          sx={{ minWidth: 200 }}
        />
        <TextField
          size="small"
          label="Dry Duration (Minutes)"
          value={dryMins}
          onChange={(e) => {
            setDryMins(e.target.value);
            setResults(null);
          }}
          helperText="Ready-to-Fold = Dry START + minutes (default 40)"
          disabled={disabled || loading}
          sx={{ minWidth: 220 }}
        />
      </Stack>

      <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>
        Interval Start &amp; Checkpoints (ET)
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
        <TextField
          size="small"
          type="time"
          label="Start Time"
          value={spaceStart}
          onChange={(e) => {
            setSpaceStart(e.target.value);
            setResults(null);
          }}
          InputLabelProps={{ shrink: true }}
          inputProps={{ step: 60 }}
          helperText="Slot 1 starts here"
          disabled={disabled || loading}
        />
        <TextField
          size="small"
          type="time"
          label="End (evenly space)"
          value={spaceEnd}
          onChange={(e) => setSpaceEnd(e.target.value)}
          InputLabelProps={{ shrink: true }}
          inputProps={{ step: 60 }}
          disabled={disabled || loading}
        />
        <Button size="small" variant="outlined" onClick={handleEvenlySpace} disabled={disabled || loading}>
          Evenly space checkpoints
        </Button>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        {slotTimes.map((value, idx) => (
          <TextField
            key={`slot-${idx}`}
            size="small"
            type="time"
            label={`Slot ${idx + 1} Checkpoint`}
            value={value}
            onChange={(e) => {
              const next = [...slotTimes];
              next[idx] = e.target.value;
              setSlotTimes(next);
              setResults(null);
            }}
            InputLabelProps={{ shrink: true }}
            inputProps={{ step: 60 }}
            error={Boolean(orderError) && idx > 0 && value && slotTimes[idx - 1] && value <= slotTimes[idx - 1]}
            disabled={disabled || loading}
          />
        ))}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button
          variant="contained"
          onClick={handleCalculate}
          disabled={disabled || loading}
          startIcon={loading ? <CircularProgress size={16} color="inherit" /> : null}
        >
          Calculate Queues
        </Button>
        <Button variant="text" onClick={handleReset} disabled={loading}>
          Reset
        </Button>
      </Stack>

      {(error || orderError) && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {error || orderError}
        </Alert>
      )}

      {results?.work_starved_definition && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          {results.work_starved_definition}
          {results.is_today ? " Today intervals truncate at current ET." : ""}
        </Typography>
      )}

      {sections.map((section) => {
        const labels = section.labels || {};
        return (
          <Box key={section.id} sx={{ mb: 2.5 }}>
            <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.25 }}>
              {section.label}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {section.subtitle}
            </Typography>
            <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: "divider" }}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}>
                    {[
                      "Slot",
                      "Checkpoint",
                      "Interval",
                      labels.newly_available || "Newly Available",
                      labels.processed || "Processed",
                      "Waiting at Start",
                      "Waiting at End",
                      "Peak Waiting",
                      "Excess / Deficit",
                      "Work-Starved Minutes",
                      "Excluded",
                      "View Available",
                      "View Processed",
                      "View Waiting",
                      ...(section.id === "folding_queue" ? [labels.capacity || "Folder Capacity"] : []),
                    ].map((h) => (
                      <TableCell key={h} sx={{ color: "#fff", fontWeight: 700, whiteSpace: "nowrap" }}>
                        {h}
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(section.slots || []).map((slot) => (
                    <TableRow key={`${section.id}-${slot.slot_index}`} hover>
                      <TableCell>{slot.slot_index}</TableCell>
                      <TableCell>{formatDateTime(slot.checkpoint_et)}</TableCell>
                      <TableCell>
                        {slot.interval_label}
                        {slot.incomplete_interval || slot.future_interval ? (
                          <Chip size="small" label="Incomplete" sx={{ ml: 0.5 }} />
                        ) : null}
                      </TableCell>
                      <TableCell align="right">{slot.newly_available_count ?? 0}</TableCell>
                      <TableCell align="right">{slot.processed_count ?? 0}</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700 }}>
                        {slot.waiting_at_end ?? 0}
                      </TableCell>
                      <TableCell align="right">{slot.peak_waiting ?? 0}</TableCell>
                      <TableCell>
                        {slot.excess_deficit_label ? (
                          <Chip
                            size="small"
                            color={statusChipColor(slot.excess_deficit_status)}
                            label={slot.excess_deficit_label}
                          />
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell align="right">{slot.work_starved_minutes ?? 0}</TableCell>
                      <TableCell align="right">{slot.excluded_sequence_count ?? 0}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          disabled={!slot.newly_available_count}
                          onClick={() =>
                            setViewDetail({
                              title: `${section.label} — ${labels.newly_available} (Slot ${slot.slot_index})`,
                              columns: AVAILABLE_COLS,
                              bags: slot.bags_available || [],
                            })
                          }
                        >
                          View {slot.newly_available_count ?? 0}
                        </Button>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          disabled={!slot.processed_count}
                          onClick={() =>
                            setViewDetail({
                              title: `${section.label} — ${labels.processed} (Slot ${slot.slot_index})`,
                              columns: PROCESSED_COLS,
                              bags: slot.bags_processed || [],
                            })
                          }
                        >
                          View {slot.processed_count ?? 0}
                        </Button>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          disabled={!slot.waiting_at_end}
                          onClick={() =>
                            setViewDetail({
                              title: `${section.label} — ${labels.waiting} (Slot ${slot.slot_index})`,
                              columns: WAITING_COLS,
                              bags: slot.bags_waiting || [],
                            })
                          }
                        >
                          View {slot.waiting_at_end ?? 0}
                        </Button>
                      </TableCell>
                      {section.id === "folding_queue" ? (
                        <TableCell>
                          {slot.folder_capacity ? (
                            <Box>
                              <Typography variant="body2" fontWeight={700}>
                                {slot.folder_capacity.recommendation}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" display="block">
                                Bags: {slot.folder_capacity.available_bags}
                                {slot.folder_capacity.available_pounds != null
                                  ? ` · Lbs: ${slot.folder_capacity.available_pounds}`
                                  : ""}
                                {slot.folder_capacity.capacity_ratio != null
                                  ? ` · Ratio: ${slot.folder_capacity.capacity_ratio}`
                                  : ""}
                              </Typography>
                              {slot.folder_capacity.note ? (
                                <Typography variant="caption" color="warning.main" display="block">
                                  {slot.folder_capacity.note}
                                </Typography>
                              ) : null}
                            </Box>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        );
      })}

      <DetailDialog
        open={Boolean(viewDetail)}
        onClose={() => setViewDetail(null)}
        title={viewDetail?.title || ""}
        columns={viewDetail?.columns || []}
        bags={viewDetail?.bags || []}
      />
    </Paper>
  );
}
