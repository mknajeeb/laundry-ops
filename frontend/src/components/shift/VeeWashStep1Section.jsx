import { useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
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

function MetricRow({
  title,
  seg,
  emphasize = false,
  onMetricClick,
  membershipHelper = null,
  pendingTrusted = true,
  rowService = "all",
  hdDashboardTotals = null,
}) {
  if (!seg) return null;
  const review = seg.exceptions?.review_required ?? seg.exceptions?.total ?? 0;
  const isHd = String(title || "").toUpperCase().startsWith("HD");
  const total =
    (isHd && hdDashboardTotals?.total_hd_orders != null
      ? hdDashboardTotals.total_hd_orders
      : null) ??
    seg.total_workload ??
    seg.active_workload ??
    Number(seg.completed || 0) + Number(seg.pending || 0) + Number(review || 0);
  const totalLabel = isHd ? "Total HD Orders" : "Total Workload";
  const doneLabel = isHd ? "Completed" : "Completed";
  const basePending = isHd ? "Review Required" : "Pending";
  const pendingLabel = isHd
    ? "Review Required"
    : pendingTrusted
      ? basePending
      : "Pending — provisional";
  const pendingValue = isHd ? review : seg.pending;
  const completedValue = isHd
    ? hdDashboardTotals?.completed ?? seg.completed
    : seg.completed;
  // Bind drawer service to the KPI row (WF/HD/TOTAL), not the page Service chip alone.
  const click = (metric, label) => () =>
    onMetricClick?.(metric, `${title} · ${label}`, { service: rowService, queue: metric });
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
            sm: isHd ? "repeat(3, 1fr)" : "repeat(4, 1fr)",
            md: isHd ? "repeat(5, 1fr)" : "repeat(4, 1fr)",
          },
          gap: 1,
        }}
      >
        <ShiftCountCard
          label={totalLabel}
          value={total}
          size="kpi"
          variant="wf"
          onClick={click("active_workload", totalLabel)}
        />
        {isHd ? (
          <ShiftCountCard
            label="Review Required"
            value={pendingValue}
            size="kpi"
            warn={pendingValue > 0}
            onClick={click("review_required", "Review Required")}
          />
        ) : (
          <ShiftCountCard
            label={pendingLabel}
            value={pendingTrusted ? seg.pending : seg.pending}
            sub={pendingTrusted ? undefined : "Pending count may be incomplete"}
            size="kpi"
            variant="pending"
            warn={!pendingTrusted}
            onClick={click("pending", pendingLabel)}
          />
        )}
        <ShiftCountCard
          label={doneLabel}
          value={completedValue}
          size="kpi"
          onClick={click("completed", doneLabel)}
        />
        {isHd ? (
          <>
            <ShiftCountCard
              label="Total Items"
              value={hdDashboardTotals?.total_items ?? 0}
              size="kpi"
            />
            <ShiftCountCard
              label="HD Revenue"
              value={
                (hdDashboardTotals?.hd_revenue ?? hdDashboardTotals?.total_revenue) != null
                  ? `$${Number(
                      hdDashboardTotals?.hd_revenue ?? hdDashboardTotals?.total_revenue
                    ).toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}`
                  : "$0.00"
              }
              size="kpi"
            />
          </>
        ) : (
          <ShiftCountCard
            label="Review Required"
            value={review}
            size="kpi"
            warn={review > 0}
            onClick={click("review_required", "Review Required")}
          />
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
        {isHd
          ? `Total ${total} = Completed ${completedValue} + Review Required ${pendingValue} · Items/HD Revenue from completed reviews only`
          : `Total ${total} = ${doneLabel} ${seg.completed} + ${basePending} ${seg.pending} + Review ${review}`}
        {membershipHelper ? ` · ${membershipHelper}` : ""}
        {!pendingTrusted && !isHd ? " · Pending provisional" : ""}
      </Typography>
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
  const [drawer, setDrawer] = useState({
    open: false,
    metric: null,
    title: "",
    reasonCode: null,
    service: "all",
    queue: null,
  });
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

  const openMetric = (metric, title, opts = null) => {
    const options = typeof opts === "string" || opts == null ? { reasonCode: opts } : opts;
    const svc = String(options?.service || "all").toLowerCase();
    setDrawer({
      open: true,
      metric,
      title,
      reasonCode: options?.reasonCode ?? null,
      service: svc === "wf" || svc === "hd" ? svc : "all",
      queue: options?.queue || metric,
    });
  };

  const onServiceFilterChange = (next) => {
    setServiceFilter(next);
    if (drawer.open) {
      setDrawer({ open: false, metric: null, title: "", reasonCode: null, service: "all", queue: null });
    }
  };

  const onRushFilterChange = (next) => {
    if (drawer.open) {
      setDrawer({ open: false, metric: null, title: "", reasonCode: null, service: "all", queue: null });
    }
    onRushChange?.(next);
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
  const dataFreshness = summary?.data_freshness || dayMeta?.data_freshness || null;
  const pendingTrusted = !(
    dataFreshness
    && (
      dataFreshness.trust_pending_from_missing_completion === false
      || dataFreshness.pending_trust === "provisional"
      || (dataFreshness.status && dataFreshness.status !== "ok")
    )
  );

  return (
    <Box sx={{ mb: 2.5 }}>
      <ShiftDayStatusBar
        selectedDateEt={selectedDateEt || summary.selected_date_et}
        shiftDay={dayMeta}
        dataFreshness={dataFreshness}
        validation={{
          review_required_count: reviewCount,
          totals: {
            active: totalSeg.active_workload,
            completed: totalSeg.completed,
            pending: totalSeg.pending,
            review_required: reviewCount,
            wf: {
              total: wfSeg?.total_workload ?? wfSeg?.active_workload,
              completed: wfSeg?.completed,
              pending: wfSeg?.pending,
              review_required: wfSeg?.exceptions?.review_required,
            },
            hd: {
              total: hdSeg?.total_workload ?? hdSeg?.active_workload,
              completed: hdSeg?.completed,
              pending: hdSeg?.pending,
              review_required: hdSeg?.exceptions?.review_required,
            },
            membership: summary?.membership || dayMeta?.membership || null,
          },
        }}
        isToday={isToday}
        onChanged={onRefresh}
      />
      {summary?.step1_history_unavailable ? (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          {summary.message ||
            "Step-1 daily workload tracking started July 23, 2026. Earlier operational snapshots were retired."}
        </Alert>
      ) : null}
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
            WF/HD append-only daily membership · Completion canonical · Review Required is for genuine exceptions only.
          </Typography>
          {summary?.membership?.fresh_start_no_prior_day_carryover ||
          summary?.membership?.excluded_prior_day_carryin_count > 0 ||
          summary?.membership?.prior_day_carryover_count === 0 ? (
            <Typography variant="caption" fontWeight={700} sx={{ display: "block", mt: 0.5, color: "#bbf7d0" }}>
              Fresh start — no prior-day carryover
            </Typography>
          ) : null}
          {summary?.membership ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
              Opening scrape admits:{" "}
              {summary.membership.opening_scrape_admit_count ?? summary.membership.baseline_count ?? "—"}
              {summary.membership.baseline_delayed ? " (delayed)" : ""} · Added during day:{" "}
              {summary.membership.added_during_day_count ?? summary.membership.added_later_count ?? "—"} · Total:{" "}
              {summary.membership.total_count ?? "—"}
              {summary.membership.excluded_prior_day_carryin_count
                ? ` · Excluded prior-day portal carry-in ${summary.membership.excluded_prior_day_carryin_count}`
                : ""}
              {summary.membership.baseline_presence_run_id
                ? ` · scrape #${summary.membership.baseline_presence_run_id}`
                : ""}
            </Typography>
          ) : null}
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
              <ServiceFilterChips value={serviceFilter} onChange={onServiceFilterChange} />
            </Box>
            <Box>
              <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
                Rush
              </Typography>
              <RushFilterChips value={rushFilter} onChange={onRushFilterChange} />
            </Box>
          </Stack>

          {wfSeg ? (
            <MetricRow
              title="WF"
              seg={wfSeg}
              rowService="wf"
              onMetricClick={openMetric}
              pendingTrusted={pendingTrusted}
            />
          ) : null}
          {hdSeg ? (
            <MetricRow
              title="HD"
              seg={hdSeg}
              rowService="hd"
              onMetricClick={openMetric}
              pendingTrusted={pendingTrusted}
              hdDashboardTotals={summary?.hd_dashboard_totals || null}
              membershipHelper={
                summary?.hd_policy?.no_carryover
                  ? "Date-scoped · estimated delivery date · no HD carryover"
                  : null
              }
            />
          ) : null}

          {(() => {
            const svcKey = serviceFilter === "wf" || serviceFilter === "hd" ? serviceFilter : "all";
            const specialty =
              summary?.specialty_metrics?.[svcKey] || summary?.specialty_metrics?.all || null;
            if (!specialty) return null;
            const comforter = specialty.comforter_orders || {};
            const bathMat = specialty.bath_mat_orders || {};
            const rejected = specialty.rejected_orders || {};
            const split = specialty.split_orders || {};
            return (
              <Box
                sx={{
                  mt: 1.25,
                  pt: 1.25,
                  borderTop: "1px solid",
                  borderColor: "divider",
                }}
              >
                <Typography
                  variant="subtitle2"
                  fontWeight={800}
                  sx={{ mb: 0.75, letterSpacing: 0.4 }}
                >
                  Specialty
                </Typography>
                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: {
                      xs: "repeat(1, 1fr)",
                      sm: "repeat(2, 1fr)",
                      md: "repeat(4, 1fr)",
                    },
                    gap: 1,
                  }}
                >
                  <ShiftCountCard
                    label="# of Comforters"
                    value={comforter.count ?? 0}
                    size="kpi"
                    onClick={() =>
                      openMetric("comforter_orders", "# of Comforters", {
                        service: svcKey,
                        queue: "comforter_orders",
                      })
                    }
                  />
                  <ShiftCountCard
                    label="# of Bath Mats"
                    value={bathMat.count ?? 0}
                    size="kpi"
                    onClick={() =>
                      openMetric("bath_mat_orders", "# of Bath Mats", {
                        service: svcKey,
                        queue: "bath_mat_orders",
                      })
                    }
                  />
                  <ShiftCountCard
                    label="Rejected Orders"
                    value={rejected.count ?? 0}
                    size="kpi"
                    warn={(rejected.count ?? 0) > 0}
                    onClick={() =>
                      openMetric("rejected_orders", "Rejected Orders", {
                        service: svcKey,
                        queue: "rejected_orders",
                      })
                    }
                  />
                  <ShiftCountCard
                    label="Split Orders"
                    value={split.count ?? 0}
                    size="kpi"
                    onClick={() =>
                      openMetric("split_orders", "Split Orders", {
                        service: svcKey,
                        queue: "split_orders",
                      })
                    }
                  />
                </Box>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                  Distinct orders in current service filter · card count matches drawer list
                </Typography>
              </Box>
            );
          })()}

          <Box
            sx={{
              mt: 0.5,
              pt: 1.25,
              borderTop: "1px solid",
              borderColor: "divider",
            }}
          >
            <MetricRow
              title="TOTAL"
              seg={totalSeg}
              emphasize
              rowService={serviceFilter === "wf" || serviceFilter === "hd" ? serviceFilter : "all"}
              onMetricClick={openMetric}
              pendingTrusted={pendingTrusted}
              membershipHelper={
                summary?.membership
                  ? `${
                      summary.membership.fresh_start_no_prior_day_carryover
                        ? "Fresh start — no prior-day carryover · "
                        : ""
                    }Opening scrape admits: ${
                      summary.membership.opening_scrape_admit_count ?? summary.membership.baseline_count ?? "—"
                    } · Added during day: ${
                      summary.membership.added_during_day_count ?? summary.membership.added_later_count ?? "—"
                    } · Total: ${summary.membership.total_count ?? totalSeg.active_workload ?? "—"}`
                  : null
              }
            />
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
            onClick={() =>
              reviewCount > 0 &&
              openMetric("review_required", "Review Required", {
                service: serviceFilter === "wf" || serviceFilter === "hd" ? serviceFilter : "all",
                queue: "review_required",
              })
            }
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
                      onBagClick={() =>
                        openMetric("review_required", label, {
                          service: serviceFilter === "wf" || serviceFilter === "hd" ? serviceFilter : "all",
                          reasonCode: key,
                          queue: "review_required",
                        })
                      }
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
        onClose={() =>
          setDrawer({ open: false, metric: null, title: "", reasonCode: null, service: "all", queue: null })
        }
        selectedDateEt={selectedDateEt || summary.selected_date_et}
        metric={drawer.metric}
        queue={drawer.queue || drawer.metric}
        title={drawer.title}
        reasonCode={drawer.reasonCode}
        serviceFilter={drawer.service || "all"}
        rushFilter={rushFilter}
        onCorrected={onRefresh}
        readOnly={readOnly}
      />
    </Box>
  );
}
