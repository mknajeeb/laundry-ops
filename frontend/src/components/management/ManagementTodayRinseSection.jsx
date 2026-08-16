import { useMemo, useState } from "react";
import { Alert, Box, Stack, Typography } from "@mui/material";
import RushFilterChips from "../shift/RushFilterChips";
import Step1MetricDrawer from "../shift/Step1MetricDrawer";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import TodayTapCard from "./TodayTapCard";
import {
  hdHeadline,
  hdIdentityLine,
  pickRinseSegments,
  pickWfSpecialty,
  wfHeadline,
  wfIdentityLine,
} from "./todayRinseModel";

function fmtInt(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
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

function CardGrid({ columns, children }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "repeat(2, minmax(0, 1fr))",
          sm: columns >= 5 ? "repeat(3, minmax(0, 1fr))" : `repeat(${columns}, minmax(0, 1fr))`,
          md: `repeat(${columns}, minmax(0, 1fr))`,
        },
        gap: 0.75,
      }}
    >
      {children}
    </Box>
  );
}

export default function ManagementTodayRinseSection({
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
    service: "all",
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

  const { wf: wfSeg, hd: hdSeg } = useMemo(
    () => pickRinseSegments(rinse, rushFilter),
    [rinse, rushFilter],
  );
  const specialty = useMemo(
    () => pickWfSpecialty(rinse, rushFilter),
    [rinse, rushFilter],
  );
  const wf = wfHeadline(wfSeg);
  const hd = hdHeadline(hdSeg, rinse?.hd_dashboard_totals);
  const comforter = specialty?.comforter_orders?.count ?? 0;
  const bathMat = specialty?.bath_mat_orders?.count ?? 0;
  const rejected = specialty?.rejected_orders?.count ?? 0;
  const split = specialty?.split_orders?.count ?? 0;

  const openMetric = (metric, title, opts = {}) => {
    if (snapshotUnavailable) return;
    const svc = String(opts.service || "wf").toLowerCase();
    setDrawer({
      open: true,
      metric,
      title,
      reasonCode: opts.reasonCode ?? null,
      service: svc === "hd" ? "hd" : "wf",
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
        service: "all",
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
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          color: "#64748b",
          mb: 1.25,
        }}
      >
        Rinse
      </Typography>

      {snapshotUnavailable ? (
        <Alert severity="warning" sx={{ mb: 1.25 }}>
          {rinse?.message || "Shift snapshot is not available yet."}
        </Alert>
      ) : null}

      <BlockLabel>Wash & Fold</BlockLabel>
      <CardGrid columns={4}>
        <TodayTapCard
          label="Workload"
          value={snapshotUnavailable ? "—" : fmtInt(wf.workload)}
          tone="workload"
          onClick={
            snapshotUnavailable
              ? undefined
              : () => openMetric("active_workload", "Wash & Fold · Workload", { service: "wf" })
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
              : () => openMetric("completed", "Wash & Fold · Completed", { service: "wf" })
          }
        />
        <TodayTapCard
          label="Pending"
          value={snapshotUnavailable ? "—" : fmtInt(wf.pending)}
          tone="pending"
          onClick={
            snapshotUnavailable
              ? undefined
              : () => openMetric("pending", "Wash & Fold · Pending", { service: "wf" })
          }
        />
        <TodayTapCard
          label="Review"
          value={snapshotUnavailable ? "—" : fmtInt(wf.review)}
          tone="review"
          warn={!snapshotUnavailable && wf.review > 0}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("review_required", "Wash & Fold · Review Required", {
                    service: "wf",
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
      <CardGrid columns={4}>
        <TodayTapCard
          label="Comforters"
          value={snapshotUnavailable ? "—" : fmtInt(comforter)}
          onClick={
            snapshotUnavailable
              ? undefined
              : () =>
                  openMetric("comforter_orders", "Comforters", {
                    service: "wf",
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
                    service: "wf",
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
                    service: "wf",
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
                    service: "wf",
                    queue: "split_orders",
                  })
          }
        />
      </CardGrid>

      <Box sx={{ mt: 2, pt: 1.5, borderTop: "1px solid #e5e7eb" }}>
        <BlockLabel>Hang Dry</BlockLabel>
        <CardGrid columns={5}>
          <TodayTapCard
            label="Orders"
            value={snapshotUnavailable ? "—" : fmtInt(hd.orders)}
            tone="hd"
            onClick={
              snapshotUnavailable
                ? undefined
                : () => openMetric("active_workload", "Hang Dry · Orders", { service: "hd" })
            }
          />
          <TodayTapCard
            label="Completed"
            value={snapshotUnavailable ? "—" : fmtInt(hd.completed)}
            tone="completed"
            onClick={
              snapshotUnavailable
                ? undefined
                : () => openMetric("completed", "Hang Dry · Completed", { service: "hd" })
            }
          />
          <TodayTapCard
            label="Review"
            value={snapshotUnavailable ? "—" : fmtInt(hd.review)}
            tone="review"
            warn={!snapshotUnavailable && hd.review > 0}
            onClick={
              snapshotUnavailable
                ? undefined
                : () =>
                    openMetric("review_required", "Hang Dry · Review Required", {
                      service: "hd",
                      queue: "review_required",
                    })
            }
          />
          <TodayTapCard
            label="Items"
            value={snapshotUnavailable ? "—" : fmtInt(hd.items)}
            tone="hd"
          />
          <TodayTapCard
            label="Revenue"
            value={snapshotUnavailable ? "—" : fmtMoney(hd.revenue)}
            tone="hd"
          />
        </CardGrid>
        {snapshotUnavailable ? null : (
          <Typography sx={{ mt: 0.6, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            {hdIdentityLine(hd)}
          </Typography>
        )}
      </Box>

      <Step1MetricDrawer
        open={drawer.open}
        onClose={() =>
          setDrawer({
            open: false,
            metric: null,
            title: "",
            reasonCode: null,
            service: "all",
            queue: null,
          })
        }
        selectedDateEt={selectedDateEt || rinse?.selected_date_et}
        metric={drawer.metric}
        queue={drawer.queue || drawer.metric}
        title={drawer.title}
        reasonCode={drawer.reasonCode}
        serviceFilter={drawer.service || "wf"}
        rushFilter={rushFilter}
        onCorrected={onRefresh}
        readOnly={readOnly}
      />
    </Box>
  );
}
