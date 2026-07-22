import { useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ShiftCountCard from "./ShiftCountCard";
import RushFilterChips from "./RushFilterChips";
import Step1MetricDrawer from "./Step1MetricDrawer";
import ShiftDayStatusBar from "./ShiftDayStatusBar";
import { SERVICE_FILTERS } from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { resolveStep1SegmentKeys } from "./veewashStep1SegmentKeys";

export { resolveStep1SegmentKeys };

const REASON_GROUPS = [
  {
    key: "COMPLETED_WITHOUT_RECOGNIZED_ENTRY",
    label: "Completed without entry",
  },
  {
    key: "WF_BULK_WORKITEM_REVIEW",
    label: "Bulk Workitems",
  },
  {
    key: "WF_ZERO_OR_MISSING_POST_WEIGHT",
    label: "Zero or missing WF post weight",
    legacyKeys: ["WF_ZERO_OR_MISSING_WEIGHT"],
  },
  {
    key: "SERVICE_CLASSIFICATION_MISMATCH",
    label: "Service classification mismatch",
  },
  {
    key: "DISAPPEARED_WITHOUT_COMPLETION",
    label: "Disappeared without completion",
  },
];

function BagList({ ids, onBagClick }) {
  const list = ids || [];
  if (list.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary">
        No bags in this category.
      </Typography>
    );
  }
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
      {list.map((id) => (
        <Chip
          key={id}
          label={id}
          size="small"
          onClick={onBagClick ? () => onBagClick(id) : undefined}
          sx={{
            fontFamily: "monospace",
            fontSize: "0.72rem",
            height: 22,
            bgcolor: "#f1f5f9",
            border: "1px solid #e2e8f0",
            cursor: onBagClick ? "pointer" : "default",
          }}
        />
      ))}
    </Stack>
  );
}

function emptySeg() {
  return {
    new_today: 0,
    carryover: 0,
    active_workload: 0,
    completed: 0,
    pending: 0,
    exceptions: { review_required: 0, total: 0 },
    bag_ids: { review_required: [] },
  };
}

function pickSeg(segments, key) {
  if (!key) return null;
  return segments?.[key] || emptySeg();
}

function ServiceFilterChips({ value, onChange }) {
  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {SERVICE_FILTERS.map(({ id, label }) => {
        const selected = value === id;
        return (
          <Chip
            key={id}
            size="small"
            label={label}
            onClick={() => onChange(id)}
            variant={selected ? "filled" : "outlined"}
            sx={{
              fontWeight: 600,
              bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlue : undefined,
              color: selected ? "#fff" : undefined,
              borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
              "&:hover": {
                bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlueDark : VEEWASH_DASHBOARD.primaryBlueLight,
              },
            }}
          />
        );
      })}
    </Stack>
  );
}

function MetricRow({ title, seg, showEntryMetrics = true, emphasize = false, onMetricClick }) {
  if (!seg) return null;
  const review = seg.exceptions?.review_required ?? seg.exceptions?.total ?? 0;
  const click = (metric, label) => () => onMetricClick?.(metric, `${title} · ${label}`);
  return (
    <Box sx={{ mb: emphasize ? 0 : 1.5 }}>
      <Typography
        variant="subtitle2"
        fontWeight={800}
        sx={{
          mb: 0.75,
          letterSpacing: 0.4,
          color: emphasize ? VEEWASH_DASHBOARD.primaryBlueDark : "text.primary",
        }}
      >
        {title}
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "repeat(2, 1fr)",
            sm: showEntryMetrics ? "repeat(3, 1fr)" : "repeat(2, 1fr)",
            md: showEntryMetrics ? "repeat(5, 1fr)" : "repeat(4, 1fr)",
          },
          gap: 1,
        }}
      >
        {showEntryMetrics ? (
          <>
            <ShiftCountCard label="New Today" value={seg.new_today} size="kpi" onClick={click("new_today", "New Today")} />
            <ShiftCountCard label="Carryover" value={seg.carryover} size="kpi" onClick={click("carryover", "Carryover")} />
          </>
        ) : (
          <ShiftCountCard
            label="Active Workload"
            value={seg.active_workload}
            size="kpi"
            variant="wf"
            onClick={click("active_workload", "Active Workload")}
          />
        )}
        <ShiftCountCard label="Completed" value={seg.completed} size="kpi" onClick={click("completed", "Completed")} />
        <ShiftCountCard
          label="Pending"
          value={seg.pending}
          size="kpi"
          variant="pending"
          onClick={click("pending", "Pending")}
        />
        <ShiftCountCard
          label="Review Required"
          value={review}
          size="kpi"
          warn={review > 0}
          onClick={click("review_required", "Review Required")}
        />
      </Box>
      {showEntryMetrics ? (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
          Active {seg.active_workload} = New {seg.new_today} + Carryover {seg.carryover}
          {" · "}
          Outcomes {seg.active_workload} = Completed {seg.completed} + Pending {seg.pending} + Review {review}
        </Typography>
      ) : (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
          Active {seg.active_workload} = Completed {seg.completed} + Pending {seg.pending} + Review {review}
        </Typography>
      )}
    </Box>
  );
}

export default function VeeWashStep1Section({
  summary,
  segment = "all",
  onRushChange,
  selectedDateEt,
  onRefresh,
  isToday = false,
  shiftDay,
}) {
  const [serviceFilter, setServiceFilter] = useState("all");
  const [drawer, setDrawer] = useState({ open: false, metric: null, title: "", reasonCode: null });
  const rushFilter = segment || "all";
  const segments = summary?.segments || {};
  const dayMeta = shiftDay || summary?.shift_day || {};
  const readOnly = Boolean(dayMeta.read_only || String(dayMeta.status || "").toUpperCase() === "CLOSED");

  const keys = useMemo(
    () => resolveStep1SegmentKeys(serviceFilter, rushFilter),
    [serviceFilter, rushFilter],
  );

  const wfSeg = pickSeg(segments, keys.wf);
  const hdSeg = pickSeg(segments, keys.hd);
  const totalSeg = pickSeg(segments, keys.total) || emptySeg();

  const reviewIds = totalSeg.bag_ids?.review_required
    || totalSeg.bag_ids?.disappeared_without_completion
    || [];
  const reviewCount = totalSeg.exceptions?.review_required ?? reviewIds.length ?? 0;
  const reviewByReason = summary?.review_by_reason || {};

  const openMetric = (metric, title, reasonCode = null) => {
    setDrawer({ open: true, metric, title, reasonCode });
  };

  if (!summary) return null;

  const otherReasonIds = Object.entries(reviewByReason)
    .filter(
      ([k]) =>
        !REASON_GROUPS.some(
          (g) => g.key === k || (g.legacyKeys || []).includes(k),
        ),
    )
    .flatMap(([, ids]) => ids || []);

  const dayLabel = isToday ? "Today's Workload" : `Workload · ${selectedDateEt || summary.selected_date_et || ""}`;

  return (
    <Box sx={{ mb: 2.5 }}>
      <ShiftDayStatusBar
        selectedDateEt={selectedDateEt || summary.selected_date_et}
        shiftDay={dayMeta}
        dataFreshness={summary.data_freshness || dayMeta.data_freshness || null}
        validation={{
          review_required_count: reviewCount,
          totals: {
            active: totalSeg.active_workload,
            completed: totalSeg.completed,
            pending: totalSeg.pending,
            review_required: reviewCount,
            wf: {
              new_today: wfSeg?.new_today,
              carryover: wfSeg?.carryover,
              completed: wfSeg?.completed,
              pending: wfSeg?.pending,
              review_required: wfSeg?.exceptions?.review_required,
            },
            hd: {
              new_today: hdSeg?.new_today,
              carryover: hdSeg?.carryover,
              completed: hdSeg?.completed,
              pending: hdSeg?.pending,
              review_required: hdSeg?.exceptions?.review_required,
            },
          },
        }}
        isToday={isToday}
        onChanged={onRefresh}
      />
      <Paper
        elevation={0}
        sx={{
          mb: 1.5,
          borderRadius: 2,
          overflow: "hidden",
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
          bgcolor: "#ffffff",
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Box
          sx={{
            px: { xs: 1.25, sm: 1.75 },
            py: { xs: 1, sm: 1.25 },
            bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
            color: "#fff",
          }}
        >
          <Stack direction="row" alignItems="center" spacing={0.75}>
            <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.125rem" }}>
              {dayLabel}
            </Typography>
            <Chip
              label="Step 1"
              size="small"
              sx={{
                height: 20,
                fontSize: "0.68rem",
                fontWeight: 700,
                bgcolor: "rgba(255,255,255,0.2)",
                color: "#fff",
              }}
            />
          </Stack>
          <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block", maxWidth: 640 }}>
            WF/HD Dirty entry · Completion canonical · Review Required includes CWO, zero-weight WF, and disappearances.
          </Typography>
        </Box>

        <Box sx={{ p: { xs: 1.25, sm: 1.75 } }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1.25}
            justifyContent="space-between"
            alignItems={{ xs: "stretch", sm: "center" }}
            sx={{ mb: 1.5 }}
          >
            <Box>
              <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
                Service
              </Typography>
              <ServiceFilterChips value={serviceFilter} onChange={setServiceFilter} />
            </Box>
            <Box>
              <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
                Rush
              </Typography>
              <RushFilterChips value={rushFilter} onChange={onRushChange} />
            </Box>
          </Stack>

          {wfSeg ? <MetricRow title="WF" seg={wfSeg} showEntryMetrics onMetricClick={openMetric} /> : null}
          {hdSeg ? <MetricRow title="HD" seg={hdSeg} showEntryMetrics onMetricClick={openMetric} /> : null}

          <Box
            sx={{
              mt: 0.5,
              pt: 1.25,
              borderTop: "1px solid",
              borderColor: "divider",
            }}
          >
            <MetricRow title="TOTAL" seg={totalSeg} showEntryMetrics={false} emphasize onMetricClick={openMetric} />
          </Box>
        </Box>
      </Paper>

      <Paper
        elevation={0}
        sx={{
          p: { xs: 1.25, sm: 1.75 },
          mb: 1.25,
          borderRadius: 2,
          border: "1px solid",
          borderColor: reviewCount > 0 ? "#fca5a5" : VEEWASH_DASHBOARD.monitoringBorder,
          bgcolor: reviewCount > 0 ? "#fef2f2" : VEEWASH_DASHBOARD.monitoringBg,
          boxShadow: "none",
        }}
      >
        <Accordion
          disableGutters
          elevation={0}
          disabled={reviewCount === 0}
          sx={{
            bgcolor: "transparent",
            "&:before": { display: "none" },
          }}
        >
          <AccordionSummary
            expandIcon={reviewCount > 0 ? <ExpandMoreIcon /> : null}
            sx={{ px: 0, minHeight: 36, "&.Mui-disabled": { opacity: 1 } }}
            onClick={() => reviewCount > 0 && openMetric("review_required", "Review Required")}
          >
            <Typography variant="subtitle2" fontWeight={800} sx={{ color: reviewCount > 0 ? "#991b1b" : "text.primary" }}>
              Review Required · {reviewCount}
            </Typography>
          </AccordionSummary>
          {reviewCount > 0 ? (
            <AccordionDetails sx={{ px: 0, pt: 0, pb: 0.5 }}>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                One count per bag. Click a group or open the drawer for chronology and corrections.
              </Typography>
              {REASON_GROUPS.map(({ key, label, legacyKeys = [] }) => {
                const ids = [
                  ...new Set([
                    ...(reviewByReason[key] || []),
                    ...legacyKeys.flatMap((lk) => reviewByReason[lk] || []),
                  ]),
                ];
                if (!ids.length) return null;
                return (
                  <Box key={key} sx={{ mb: 1 }}>
                    <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.35 }}>
                      {label} · {ids.length}
                    </Typography>
                    <BagList
                      ids={ids}
                      onBagClick={() => openMetric("review_required", label, key)}
                    />
                  </Box>
                );
              })}
              {otherReasonIds.length > 0 ? (
                <Box sx={{ mb: 1 }}>
                  <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.35 }}>
                    Other discrepancies · {otherReasonIds.length}
                  </Typography>
                  <BagList ids={otherReasonIds} onBagClick={() => openMetric("review_required", "Other discrepancies")} />
                </Box>
              ) : null}
            </AccordionDetails>
          ) : null}
        </Accordion>
      </Paper>

      <Step1MetricDrawer
        open={drawer.open}
        onClose={() => setDrawer((d) => ({ ...d, open: false }))}
        selectedDateEt={selectedDateEt || summary.selected_date_et}
        metric={drawer.metric}
        title={drawer.title}
        reasonCode={drawer.reasonCode}
        serviceFilter={serviceFilter}
        rushFilter={rushFilter}
        onCorrected={onRefresh}
        readOnly={readOnly}
      />
    </Box>
  );
}
