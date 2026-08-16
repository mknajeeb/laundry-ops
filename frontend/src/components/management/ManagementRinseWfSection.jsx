import { useMemo, useState } from "react";
import { Alert, Box, Stack, Typography } from "@mui/material";
import RushFilterChips from "../shift/RushFilterChips";
import Step1MetricDrawer from "../shift/Step1MetricDrawer";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import TodayTapCard from "./TodayTapCard";
import {
  pickRinseSegments,
  pickWfSpecialty,
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

function BlockLabel({ children }) {
  return (
    <Typography
      sx={{
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: 0.8,
        textTransform: "uppercase",
        color: "#64748b",
        mb: 0.75,
      }}
    >
      {children}
    </Typography>
  );
}

function CardGrid({ children }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "repeat(2, minmax(0, 1fr))",
          sm: "repeat(4, minmax(0, 1fr))",
        },
        gap: 0.75,
      }}
    >
      {children}
    </Box>
  );
}

/** Modernized WF Shift Analysis compartment — WF only; same drawers/endpoints. */
export default function ManagementRinseWfSection({
  rinse,
  lbsProcessed = null,
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
  const wf = wfHeadline(wfSeg);
  const comforter = specialty?.comforter_orders?.count ?? 0;
  const bathMat = specialty?.bath_mat_orders?.count ?? 0;
  const rejected = specialty?.rejected_orders?.count ?? 0;
  const split = specialty?.split_orders?.count ?? 0;

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
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: "#fff",
      }}
    >
      {snapshotUnavailable ? (
        <Alert severity="warning" sx={{ mb: 1.25 }}>
          {rinse?.message || "Shift snapshot is not available yet."}
        </Alert>
      ) : null}

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
          sub={fmtLbs(lbsProcessed)}
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
              : () =>
                  openMetric("review_required", "Rinse WF · Review Required", {
                    queue: "review_required",
                  })
          }
        />
      </CardGrid>
      {snapshotUnavailable ? null : (
        <Typography sx={{ mt: 0.6, mb: 1, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
          {wfIdentityLine(wf)}
        </Typography>
      )}

      <Stack direction="row" alignItems="center" sx={{ mb: 1.5 }} spacing={1}>
        <RushFilterChips value={rushFilter} onChange={onRushChange} disabled={snapshotUnavailable} />
      </Stack>

      <BlockLabel>Specialty / Quality</BlockLabel>
      <CardGrid>
        <TodayTapCard
          label="Comforters"
          value={snapshotUnavailable ? "—" : fmtInt(comforter)}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("comforter_orders", "Comforters", {
                    queue: "comforter_orders",
                  })
          }
        />
        <TodayTapCard
          label="Bath Mats"
          value={snapshotUnavailable ? "—" : fmtInt(bathMat)}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("bath_mat_orders", "Bath Mats", {
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
