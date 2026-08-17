import { useMemo, useState } from "react";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import RushFilterChips from "../shift/RushFilterChips";
import Step1MetricDrawer from "../shift/Step1MetricDrawer";
import TodayTapCard from "./TodayTapCard";
import ManagementRinseWfReviewSection from "./ManagementRinseWfReviewSection";
import {
  pickRinseSegments,
  pickWfSpecialty,
  pickWfSupplies,
  pickWfWeights,
  wfHeadline,
  wfIdentityLine,
} from "./todayRinseModel";

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtLbs(v) {
  if (v == null || Number.isNaN(Number(v))) return null;
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} lb`;
}

function fmtOz(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} oz`;
}

function BlockLabel({ children, hint }) {
  return (
    <Stack direction="row" alignItems="baseline" spacing={0.75} sx={{ mb: 0.75 }}>
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {children}
      </Typography>
      {hint ? (
        <Typography sx={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, color: "#94a3b8" }}>
          {hint}
        </Typography>
      ) : null}
    </Stack>
  );
}

function CardGrid({ children, columns = { xs: 2, sm: 4 } }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: `repeat(${columns.xs}, minmax(0, 1fr))`,
          sm: `repeat(${columns.sm}, minmax(0, 1fr))`,
        },
        gap: 0.75,
        mb: 1.5,
      }}
    >
      {children}
    </Box>
  );
}

const SUPPLY_ROWS = [
  { key: "Tide", label: "Tide" },
  { key: "Downy", label: "Downy" },
  { key: "OxiClean", label: "Oxi" },
  { key: "All Free & Clear", label: "All Free & Clear" },
];

/** Management Rinse WF — WF-only operational home. */
export default function ManagementRinseWfSection({
  rinse,
  review: reviewProp,
  supplies: suppliesProp,
  suppliesLoading = false,
  suppliesError = "",
  onRetrySupplies,
  selectedDateEt,
  onRefresh,
}) {
  const [rushFilter, setRushFilter] = useState("all");
  const [drawer, setDrawer] = useState({
    open: false,
    metric: null,
    title: "",
    reasonCode: null,
    service: "wf",
    queue: null,
  });

  const snapshotUnavailable = Boolean(
    rinse?.data_unavailable
      || rinse?.snapshot_available === false
      || rinse?.snapshot_missing,
  );
  const readOnly = Boolean(
    rinse?.shift_day?.read_only
      || String(rinse?.shift_day?.status || "").toUpperCase() === "CLOSED",
  );

  const { wf: wfSeg } = useMemo(
    () => pickRinseSegments(rinse, rushFilter),
    [rinse, rushFilter],
  );
  const specialty = useMemo(
    () => pickWfSpecialty(rinse, rushFilter),
    [rinse, rushFilter],
  );
  const weights = useMemo(
    () => pickWfWeights(rinse, rushFilter),
    [rinse, rushFilter],
  );
  const supplies = useMemo(
    () => pickWfSupplies(rinse, suppliesProp),
    [rinse, suppliesProp],
  );
  const wf = wfHeadline(wfSeg);
  // Dashboard cards: order counts. Order detail / Review list: item quantities.
  const comforterOrders = specialty?.comforter_orders?.order_count
    ?? specialty?.comforter_orders?.count
    ?? 0;
  const comforterQty = specialty?.comforter_orders?.total_quantity ?? null;
  const bathMatOrders = specialty?.bath_mat_orders?.order_count
    ?? specialty?.bath_mat_orders?.count
    ?? 0;
  const bathMatQty = specialty?.bath_mat_orders?.total_quantity ?? null;
  const rejected = specialty?.rejected_orders?.count ?? 0;
  const split = specialty?.split_orders?.count ?? 0;
  const suppliesAvailable = Boolean(supplies?.available);
  const suppliesPending = Boolean(suppliesLoading) || (Boolean(supplies?.deferred) && !suppliesAvailable);
  const reviewSummary = reviewProp || rinse?.review || null;

  const openMetric = (metric, title, opts = {}) => {
    if (snapshotUnavailable) return;
    setDrawer({
      open: true,
      metric,
      title,
      reasonCode: opts.reasonCode ?? null,
      service: "wf",
      queue: opts.queue || metric,
    });
  };

  const onRushChange = (next) => {
    if (drawer.open) {
      setDrawer({
        open: false,
        metric: null,
        title: "",
        reasonCode: null,
        service: "wf",
        queue: null,
      });
    }
    setRushFilter(next);
  };

  return (
    <Box>
      {snapshotUnavailable ? (
        <Alert severity="warning" sx={{ mb: 1.25 }}>
          {rinse?.message || "Shift snapshot is not available yet."}
        </Alert>
      ) : null}

      <Box sx={{ mb: 1.25 }}>
        <RushFilterChips value={rushFilter} onChange={onRushChange} disabled={snapshotUnavailable} />
      </Box>

      <BlockLabel>Workload</BlockLabel>
      <CardGrid>
        <TodayTapCard
          label="Workload"
          value={snapshotUnavailable ? "—" : fmtInt(wf.workload)}
          tone="workload"
          onClick={
            snapshotUnavailable
              ? undefined
              : () => openMetric("active_workload", "Rinse WF · Workload", { queue: "active_workload" })
          }
        />
        <TodayTapCard
          label="Completed"
          value={snapshotUnavailable ? "—" : fmtInt(wf.completed)}
          tone="completed"
          onClick={
            snapshotUnavailable
              ? undefined
              : () => openMetric("completed", "Rinse WF · Completed", { queue: "completed" })
          }
        />
        <TodayTapCard
          label="Pending"
          value={snapshotUnavailable ? "—" : fmtInt(wf.pending)}
          tone="pending"
          onClick={
            snapshotUnavailable
              ? undefined
              : () => openMetric("pending", "Rinse WF · Pending", { queue: "pending" })
          }
        />
        <TodayTapCard
          label="Review Required"
          value={snapshotUnavailable ? "—" : fmtInt(wf.review)}
          tone="review"
          warn={!snapshotUnavailable && wf.review > 0}
          onClick={
            snapshotUnavailable
              ? undefined
              : () => {
                  const el = document.getElementById("management-rinse-wf-review");
                  el?.scrollIntoView({ behavior: "smooth", block: "start" });
                }
          }
        />
      </CardGrid>
      {snapshotUnavailable ? null : (
        <Typography sx={{ mt: -1, mb: 1.5, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
          {wfIdentityLine(wf)}
        </Typography>
      )}

      <BlockLabel>Processed pounds</BlockLabel>
      <CardGrid columns={{ xs: 2, sm: 2 }}>
        <TodayTapCard
          label="PRE Weight"
          value={snapshotUnavailable ? "—" : (fmtLbs(weights.preLbs) || "—")}
          sub={
            snapshotUnavailable
              ? undefined
              : `${fmtInt(weights.preBagCount)} bag${weights.preBagCount === 1 ? "" : "s"}`
          }
          tone="workload"
        />
        <TodayTapCard
          label="POST Weight"
          value={snapshotUnavailable ? "—" : (fmtLbs(weights.postLbs) || "—")}
          sub={
            snapshotUnavailable
              ? undefined
              : `${fmtInt(weights.postBagCount)} bag${weights.postBagCount === 1 ? "" : "s"}`
          }
          tone="completed"
        />
      </CardGrid>

      <BlockLabel>Specialty / Quality</BlockLabel>
      <CardGrid>
        <TodayTapCard
          label="Comforter Orders"
          value={snapshotUnavailable ? "—" : fmtInt(comforterOrders)}
          sub={
            snapshotUnavailable || comforterQty == null
              ? undefined
              : `${fmtInt(comforterQty)} item${Number(comforterQty) === 1 ? "" : "s"}`
          }
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("comforter_orders", "Comforter Orders", {
                    queue: "comforter_orders",
                  })
          }
        />
        <TodayTapCard
          label="Bath Mat Orders"
          value={snapshotUnavailable ? "—" : fmtInt(bathMatOrders)}
          sub={
            snapshotUnavailable || bathMatQty == null
              ? undefined
              : `${fmtInt(bathMatQty)} item${Number(bathMatQty) === 1 ? "" : "s"}`
          }
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("bath_mat_orders", "Bath Mat Orders", {
                    queue: "bath_mat_orders",
                  })
          }
        />
        <TodayTapCard
          label="Rejects"
          value={snapshotUnavailable ? "—" : fmtInt(rejected)}
          warn={!snapshotUnavailable && rejected > 0}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("rejected_orders", "Rejected Orders", {
                    queue: "rejected_orders",
                  })
          }
        />
        <TodayTapCard
          label="Splits"
          value={snapshotUnavailable ? "—" : fmtInt(split)}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("split_orders", "Split Orders", {
                    queue: "split_orders",
                  })
          }
        />
      </CardGrid>

      <Box id="management-rinse-wf-review">
        <ManagementRinseWfReviewSection
          selectedDateEt={selectedDateEt || rinse?.selected_date_et}
          rushFilter={rushFilter}
          reviewSummary={reviewSummary}
          snapshotUnavailable={snapshotUnavailable}
          readOnly={readOnly}
          onRefresh={onRefresh}
        />
      </Box>

      <BlockLabel hint="DAY TOTALS">Supplies</BlockLabel>
      <CardGrid>
        {SUPPLY_ROWS.map((row) => (
          <TodayTapCard
            key={row.key}
            label={row.label}
            value={
              suppliesPending
                ? "…"
                : snapshotUnavailable || !suppliesAvailable
                  ? "—"
                  : fmtOz(supplies?.[row.key]?.ounces)
            }
            sub={
              suppliesPending
                ? "Loading…"
                : snapshotUnavailable || !suppliesAvailable
                  ? undefined
                  : `${fmtInt(supplies?.[row.key]?.doses)} dose${
                      Number(supplies?.[row.key]?.doses) === 1 ? "" : "s"
                    }`
            }
          />
        ))}
      </CardGrid>
      {suppliesError && !suppliesPending ? (
        <Box sx={{ mt: -0.5, mb: 1 }}>
          <Button
            size="small"
            variant="text"
            onClick={onRetrySupplies}
            sx={{ textTransform: "none", fontWeight: 700, px: 0.5 }}
          >
            Retry Supplies
          </Button>
        </Box>
      ) : null}

      <Step1MetricDrawer
        open={drawer.open}
        onClose={() =>
          setDrawer({
            open: false,
            metric: null,
            title: "",
            reasonCode: null,
            service: "wf",
            queue: null,
          })
        }
        selectedDateEt={selectedDateEt || rinse?.selected_date_et}
        metric={drawer.metric}
        queue={drawer.queue || drawer.metric}
        title={drawer.title}
        reasonCode={drawer.reasonCode}
        serviceFilter="wf"
        rushFilter={rushFilter}
        onCorrected={onRefresh}
        readOnly={readOnly}
      />
    </Box>
  );
}
