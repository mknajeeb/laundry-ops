import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
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
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { getOperationsTimeline } from "../api";
import { todayRange, yesterdayRange } from "../utils/foldingDateRange";
import { formatDateTime, formatFoldingDuration } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import VeeWashLogo from "../components/VeeWashLogo";

const DATE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "custom", label: "Custom ET" },
];

const TABS = [
  { id: "shift_timeline", label: "Shift Timeline" },
  { id: "order_journey", label: "Order Journey" },
  { id: "employee_activity", label: "Employee Activity" },
];

const CATEGORY_COLORS = {
  sorting: "#7c3aed",
  weighing: "#2563eb",
  washing: "#0891b2",
  drying: "#ea580c",
  folding: "#16a34a",
  other: "#64748b",
};

function formatDurationSeconds(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s <= 0) return "0m";
  return formatFoldingDuration(s);
}

function SummaryCard({ label, value, sub }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
        minWidth: 0,
        flex: "1 1 140px",
      }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, mt: 0.25 }}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}

function CategoryChip({ category }) {
  const color = CATEGORY_COLORS[category] || CATEGORY_COLORS.other;
  return (
    <Chip
      size="small"
      label={category || "other"}
      sx={{
        bgcolor: `${color}18`,
        color,
        fontWeight: 700,
        textTransform: "capitalize",
        fontSize: "0.7rem",
      }}
    />
  );
}

function BagDetailDialog({ open, bagId, bagDetail, onClose }) {
  if (!open) return null;
  const history = bagDetail?.scan_history || [];
  const stages = bagDetail?.processing_timeline || [];

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h6" fontWeight={800}>
          Bag {bagId}
        </Typography>
        <IconButton onClick={onClose} size="small" aria-label="close">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {stages.length > 0 ? (
          <>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Processing timeline
            </Typography>
            <Stack spacing={1} sx={{ mb: 2 }}>
              {stages.map((st) => (
                <Paper key={st.stage} variant="outlined" sx={{ p: 1, borderRadius: 1.5 }}>
                  <Stack direction="row" justifyContent="space-between" flexWrap="wrap" gap={0.5}>
                    <Typography variant="body2" fontWeight={700} textTransform="capitalize">
                      {st.stage}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {formatDurationSeconds(st.duration_seconds)}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    {formatDateTime(st.start_et)} → {formatDateTime(st.end_et) || "—"}
                  </Typography>
                </Paper>
              ))}
            </Stack>
          </>
        ) : null}

        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
          Complete scan history
        </Typography>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time (ET)</TableCell>
                <TableCell>Employee</TableCell>
                <TableCell>Activity</TableCell>
                <TableCell>Rack</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {history.map((row, i) => (
                <TableRow key={`${row.event_id}-${i}`}>
                  <TableCell>{formatDateTime(row.timestamp_et)}</TableCell>
                  <TableCell>{row.employee || "—"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap">
                      <CategoryChip category={row.activity_category} />
                      <Typography variant="caption">{row.activity_label}</Typography>
                    </Stack>
                  </TableCell>
                  <TableCell>{row.rack || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </DialogContent>
    </Dialog>
  );
}

export default function OperationsTimelinePage() {
  const [datePreset, setDatePreset] = useState("today");
  const [customDate, setCustomDate] = useState(todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(todayRange().start);
  const [activeTab, setActiveTab] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedBagId, setSelectedBagId] = useState(null);

  const load = useCallback(async (dateEt) => {
    if (!dateEt) return;
    setLoading(true);
    setError("");
    try {
      const res = await getOperationsTimeline({ date_et: dateEt });
      setData(res.data);
      setActiveDateEt(dateEt);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load operations timeline");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(activeDateEt);
  }, []);

  const applyDate = (preset, dateEt) => {
    setDatePreset(preset);
    if (dateEt) {
      setCustomDate(dateEt);
      load(dateEt);
    }
  };

  const handlePresetChange = (_, value) => {
    if (!value) return;
    if (value === "today") applyDate("today", todayRange().start);
    else if (value === "yesterday") applyDate("yesterday", yesterdayRange().start);
    else setDatePreset("custom");
  };

  const summary = data?.summary || {};
  const shiftTimeline = data?.shift_timeline || [];
  const orderJourneys = data?.order_journeys || [];
  const employeeActivity = data?.employee_activity || [];
  const bags = data?.bags || {};

  const bagDetail = selectedBagId ? bags[selectedBagId] : null;

  const categoryLegend = useMemo(() => data?.activity_category_mapping || {}, [data]);

  const openBag = (bagId) => setSelectedBagId(bagId);

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 1200, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <VeeWashLogo height={28} />
        <Typography variant="h5" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
          Shift Operations Timeline
        </Typography>
      </Stack>

      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
        <Button size="small" component={RouterLink} to="/performance" sx={{ textTransform: "none", fontWeight: 600 }}>
          Shift Analysis
        </Button>
        <Button
          size="small"
          component={RouterLink}
          to="/performance/sorting-chronology"
          sx={{ textTransform: "none" }}
        >
          Sorting Chronology
        </Button>
        <Button size="small" component={RouterLink} to="/performance/daily-roster" sx={{ textTransform: "none" }}>
          Daily Roster
        </Button>
      </Stack>

      <Paper
        elevation={0}
        sx={{
          p: 1.5,
          mb: 2,
          borderRadius: 2,
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        }}
      >
        <ToggleButtonGroup
          exclusive
          size="small"
          value={datePreset}
          onChange={handlePresetChange}
          sx={{ flexWrap: "wrap", gap: 0.5, mb: datePreset === "custom" ? 1 : 0 }}
        >
          {DATE_PRESETS.map(({ id, label }) => (
            <ToggleButton key={id} value={id} disabled={loading} sx={{ textTransform: "none", fontWeight: 600 }}>
              {label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        {datePreset === "custom" ? (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              type="date"
              size="small"
              label="ET date"
              value={customDate}
              onChange={(e) => setCustomDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
            <Button
              size="small"
              variant="contained"
              disabled={loading}
              onClick={() => applyDate("custom", customDate)}
              sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}
            >
              Apply
            </Button>
          </Stack>
        ) : null}
      </Paper>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading && !data ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress />
        </Box>
      ) : null}

      {data ? (
        <>
          <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
            <SummaryCard label="First Activity" value={formatDateTime(summary.first_activity_et) || "—"} />
            <SummaryCard label="Last Activity" value={formatDateTime(summary.last_activity_et) || "—"} />
            <SummaryCard label="Active Orders" value={summary.total_active_orders ?? 0} />
            <SummaryCard label="Total Scans" value={summary.total_scans ?? 0} />
            <SummaryCard label="Sorting Time" value={formatDurationSeconds(summary.total_sorting_seconds)} />
            <SummaryCard label="Washing Time" value={formatDurationSeconds(summary.total_washing_seconds)} />
            <SummaryCard label="Drying Time" value={formatDurationSeconds(summary.total_drying_seconds)} />
            <SummaryCard label="Folding Time" value={formatDurationSeconds(summary.total_folding_seconds)} />
          </Stack>

          <Paper elevation={0} sx={{ mb: 2, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
            <Tabs
              value={activeTab}
              onChange={(_, v) => setActiveTab(v)}
              variant="scrollable"
              scrollButtons="auto"
              sx={{ borderBottom: 1, borderColor: "divider" }}
            >
              {TABS.map((t) => (
                <Tab key={t.id} label={t.label} sx={{ textTransform: "none", fontWeight: 600 }} />
              ))}
            </Tabs>

            <Box sx={{ p: { xs: 1, sm: 1.5 } }}>
              {activeTab === 0 ? (
                shiftTimeline.length === 0 ? (
                  <Alert severity="info">No scan activity for {activeDateEt}.</Alert>
                ) : (
                  <TableContainer>
                    <Table size="small" sx={{ minWidth: 520 }}>
                      <TableHead>
                        <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
                          <TableCell>Time</TableCell>
                          <TableCell>Employee</TableCell>
                          <TableCell>Bag ID</TableCell>
                          <TableCell>Activity</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {shiftTimeline.map((row) => (
                          <TableRow key={`${row.index}-${row.event_id}`} hover>
                            <TableCell>{formatDateTime(row.timestamp_et)}</TableCell>
                            <TableCell>{row.employee || "—"}</TableCell>
                            <TableCell>
                              <Button
                                size="small"
                                onClick={() => openBag(row.bag_id)}
                                sx={{ textTransform: "none", fontWeight: 700, p: 0, minWidth: 0 }}
                              >
                                {row.bag_id}
                              </Button>
                            </TableCell>
                            <TableCell>
                              <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap">
                                <CategoryChip category={row.activity_category} />
                                <Typography variant="caption">{row.activity_label}</Typography>
                              </Stack>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )
              ) : null}

              {activeTab === 1 ? (
                orderJourneys.length === 0 ? (
                  <Alert severity="info">No orders for {activeDateEt}.</Alert>
                ) : (
                  <Stack spacing={1.5}>
                    {orderJourneys.map((j) => (
                      <Paper
                        key={j.bag_id}
                        variant="outlined"
                        sx={{ p: 1.5, borderRadius: 2, cursor: "pointer" }}
                        onClick={() => openBag(j.bag_id)}
                      >
                        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1}>
                          <Typography variant="subtitle1" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
                            {j.bag_id}
                          </Typography>
                          <Chip size="small" label={`${j.scan_count_on_day} scans`} />
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                          {formatDateTime(j.first_activity_et)} → {formatDateTime(j.last_activity_et)} (
                          {formatDurationSeconds(j.elapsed_seconds)})
                        </Typography>
                        {j.stages?.length > 0 ? (
                          <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1 }}>
                            {j.stages.map((st) => (
                              <Chip
                                key={st.stage}
                                size="small"
                                label={`${st.stage}: ${formatDurationSeconds(st.duration_seconds)}`}
                                variant="outlined"
                                sx={{ textTransform: "capitalize" }}
                              />
                            ))}
                          </Stack>
                        ) : null}
                      </Paper>
                    ))}
                  </Stack>
                )
              ) : null}

              {activeTab === 2 ? (
                employeeActivity.length === 0 ? (
                  <Alert severity="info">No employee activity for {activeDateEt}.</Alert>
                ) : (
                  <Stack spacing={2}>
                    {employeeActivity.map((emp) => (
                      <Paper key={emp.employee} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                        <Typography variant="subtitle1" fontWeight={800}>
                          {emp.employee}
                        </Typography>
                        <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ my: 1 }}>
                          {Object.entries(emp.time_by_category_seconds || {}).map(([cat, sec]) =>
                            sec > 0 ? (
                              <Chip
                                key={cat}
                                size="small"
                                label={`${cat}: ${formatDurationSeconds(sec)}`}
                                sx={{ textTransform: "capitalize" }}
                              />
                            ) : null
                          )}
                        </Stack>
                        {emp.blocks?.map((blk, i) => (
                          <Box
                            key={`${emp.employee}-blk-${i}`}
                            sx={{
                              borderLeft: `4px solid ${CATEGORY_COLORS[blk.category] || CATEGORY_COLORS.other}`,
                              pl: 1,
                              py: 0.5,
                              mb: 0.5,
                            }}
                          >
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                              <CategoryChip category={blk.category} />
                              <Typography variant="body2">
                                {formatDateTime(blk.start_et)} – {formatDateTime(blk.end_et)}
                              </Typography>
                              <Typography variant="caption" color="text.secondary">
                                {formatDurationSeconds(blk.duration_seconds)} · {blk.scan_count} scans
                              </Typography>
                            </Stack>
                          </Box>
                        ))}
                        {emp.idle_gaps?.length > 0 ? (
                          <Typography variant="caption" color="warning.dark" sx={{ mt: 0.5, display: "block" }}>
                            Idle gaps:{" "}
                            {emp.idle_gaps
                              .map((g) => formatDurationSeconds(g.duration_seconds))
                              .join(", ")}
                          </Typography>
                        ) : null}
                      </Paper>
                    ))}
                  </Stack>
                )
              ) : null}
            </Box>
          </Paper>

          {Object.keys(categoryLegend).length > 0 ? (
            <Paper elevation={0} sx={{ p: 1.5, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
              <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                Activity category mapping
              </Typography>
              <Stack spacing={0.25}>
                {Object.entries(categoryLegend).map(([cat, desc]) => (
                  <Typography key={cat} variant="caption" color="text.secondary">
                    <Box component="span" sx={{ fontWeight: 700, textTransform: "capitalize" }}>
                      {cat}
                    </Box>
                    : {desc}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          ) : null}
        </>
      ) : null}

      <BagDetailDialog
        open={Boolean(selectedBagId)}
        bagId={selectedBagId}
        bagDetail={bagDetail}
        onClose={() => setSelectedBagId(null)}
      />
    </Box>
  );
}
