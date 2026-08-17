import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import RushFilterChips from "../shift/RushFilterChips";
import Step1MetricDrawer from "../shift/Step1MetricDrawer";
import TodayTapCard from "./TodayTapCard";
import ManagementRinseWfReviewSection from "./ManagementRinseWfReviewSection";
import { getManagementTodaySuppliesDetail } from "../../api";
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

function fmtQty(v, unit) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const u = unit ? ` ${unit}` : "";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}${u}`;
}

function fmtMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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

const FALLBACK_SUPPLY_ROWS = [
  { legacy_report_key: "Tide", label: "Tide" },
  { legacy_report_key: "Downy", label: "Downy" },
  { legacy_report_key: "OxiClean", label: "Oxi" },
  { legacy_report_key: "All Free & Clear", label: "All Free & Clear" },
];

/** Management Rinse WF — WF-only operational home. */
export default function ManagementRinseWfSection({
  rinse,
  review: reviewProp,
  supplies: suppliesProp,
  suppliesLoading = false,
  suppliesError = "",
  onRetrySupplies,
  rushFilter: rushFilterProp,
  onRushFilterChange,
  selectedDateEt,
  onRefresh,
}) {
  const [rushFilterLocal, setRushFilterLocal] = useState("all");
  const rushFilter = rushFilterProp ?? rushFilterLocal;
  const [drawer, setDrawer] = useState({
    open: false,
    metric: null,
    title: "",
    reasonCode: null,
    service: "wf",
    queue: null,
  });
  const [supplyDetail, setSupplyDetail] = useState({
    open: false,
    loading: false,
    error: "",
    product: null,
    rows: [],
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
  // Dashboard cards: item quantities (not order counts). Review Specialty Items
  // is a separate unresolved-order concept — do not merge.
  const comforterQty =
    specialty?.comforter_orders?.item_qty
    ?? specialty?.comforter_orders?.total_quantity
    ?? 0;
  const bathMatQty =
    specialty?.bath_mat_orders?.item_qty
    ?? specialty?.bath_mat_orders?.total_quantity
    ?? 0;
  const comforterOrders = specialty?.comforter_orders?.order_count
    ?? specialty?.comforter_orders?.count
    ?? null;
  const bathMatOrders = specialty?.bath_mat_orders?.order_count
    ?? specialty?.bath_mat_orders?.count
    ?? null;
  const rejected = specialty?.rejected_orders?.count ?? 0;
  const split = specialty?.split_orders?.count ?? 0;
  const splitReview =
    specialty?.split_review?.count
    ?? reviewProp?.split_order_review
    ?? rinse?.review?.split_order_review
    ?? 0;
  const suppliesAvailable = Boolean(supplies?.available);
  const suppliesPending = Boolean(suppliesLoading) || (Boolean(supplies?.deferred) && !suppliesAvailable);
  const supplyBanner = supplies?.supply_banner || null;
  const supplyStatus = String(supplies?.supply_status || "").toUpperCase();
  const pendingSplitReviews = Number(supplies?.pending_split_reviews || 0);
  const supplyFinalizable = supplies?.supply_finalizable !== false;
  const reviewSummary = reviewProp || rinse?.review || null;
  const supplyProducts = useMemo(() => {
    const products = Array.isArray(supplies?.products) ? supplies.products : [];
    if (products.length) return products;
    return FALLBACK_SUPPLY_ROWS.map((row) => {
      const legacy = supplies?.[row.legacy_report_key] || {};
      return {
        ...row,
        orders_using: legacy.orders_using,
        confirmed_loads: legacy.confirmed_loads ?? legacy.doses,
        confirmed_doses: legacy.doses,
        quantity_used: legacy.quantity_used ?? legacy.ounces,
        quantity_unit: "oz",
        estimated_cost: legacy.estimated_cost,
      };
    });
  }, [supplies]);

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
    if (onRushFilterChange) onRushFilterChange(next);
    else setRushFilterLocal(next);
  };

  const openSupplyDetail = async (product) => {
    if (snapshotUnavailable || suppliesPending || !suppliesAvailable) return;
    setSupplyDetail({
      open: true,
      loading: true,
      error: "",
      product,
      rows: [],
    });
    try {
      const res = await getManagementTodaySuppliesDetail(
        selectedDateEt || rinse?.selected_date_et,
        {
          rush: rushFilter,
          product_id: product?.product_id || undefined,
          legacy_report_key: product?.legacy_report_key || undefined,
        },
      );
      setSupplyDetail({
        open: true,
        loading: false,
        error: "",
        product,
        rows: res.data?.orders || [],
      });
    } catch (err) {
      setSupplyDetail({
        open: true,
        loading: false,
        error: err?.response?.data?.error || err?.message || "Detail unavailable",
        product,
        rows: [],
      });
    }
  };

  const supplyHint = suppliesPending
    ? "LOADING"
    : supplyStatus
      ? `${supplyStatus}${pendingSplitReviews > 0 ? ` · ${pendingSplitReviews} PENDING SPLIT` : ""}`
      : "DAY TOTALS";

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
          label="COMFORTERS"
          value={snapshotUnavailable ? "—" : fmtInt(comforterQty)}
          sub={
            snapshotUnavailable || comforterOrders == null
              ? undefined
              : `${fmtInt(comforterOrders)} order${Number(comforterOrders) === 1 ? "" : "s"}`
          }
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
          label="BATH MATS"
          value={snapshotUnavailable ? "—" : fmtInt(bathMatQty)}
          sub={
            snapshotUnavailable || bathMatOrders == null
              ? undefined
              : `${fmtInt(bathMatOrders)} order${Number(bathMatOrders) === 1 ? "" : "s"}`
          }
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
          sub={
            !snapshotUnavailable && splitReview > 0
              ? `SPLIT REVIEW ${splitReview}`
              : undefined
          }
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

      <BlockLabel hint={supplyHint}>Supplies</BlockLabel>
      {!snapshotUnavailable && suppliesAvailable && !supplyFinalizable && supplyBanner ? (
        <Alert severity="warning" sx={{ mb: 0.75, py: 0.35 }}>
          {supplyBanner}
        </Alert>
      ) : null}
      {!snapshotUnavailable && suppliesAvailable && supplyStatus ? (
        <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b", mb: 0.75 }}>
          Status {supplyStatus}
          {pendingSplitReviews > 0
            ? ` · Pending Split Reviews = ${pendingSplitReviews}`
            : ""}
        </Typography>
      ) : null}
      <CardGrid columns={{ xs: 1, sm: 2 }}>
        {supplyProducts.map((row) => {
          const key = row.legacy_report_key || row.label;
          const shortLabel =
            key === "OxiClean" ? "Oxi" : key === "All Free & Clear" ? "All Free & Clear" : (row.label || key);
          return (
            <TodayTapCard
              key={key}
              label={shortLabel}
              value={
                suppliesPending
                  ? "…"
                  : snapshotUnavailable || !suppliesAvailable
                    ? "—"
                    : fmtInt(row.confirmed_loads ?? row.confirmed_doses)
              }
              sub={
                suppliesPending
                  ? "Loading…"
                  : snapshotUnavailable || !suppliesAvailable
                    ? undefined
                    : [
                        `${fmtInt(row.orders_using)} orders`,
                        `${fmtQty(row.quantity_used, row.quantity_unit)}`,
                        `est ${fmtMoney(row.estimated_cost)}`,
                      ].join(" · ")
              }
              onClick={
                snapshotUnavailable || suppliesPending || !suppliesAvailable
                  ? undefined
                  : () => openSupplyDetail(row)
              }
            />
          );
        })}
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
      <Box sx={{ mt: -0.5, mb: 1.25 }}>
        <Button
          size="small"
          component={RouterLink}
          to="/management/supply-master"
          sx={{ textTransform: "none", fontWeight: 700, px: 0.5 }}
        >
          Supply Master · Products & Mappings
        </Button>
      </Box>

      <Dialog
        open={supplyDetail.open}
        onClose={() => setSupplyDetail((s) => ({ ...s, open: false }))}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle sx={{ pr: 6 }}>
          {supplyDetail.product?.label || supplyDetail.product?.legacy_report_key || "Supply detail"}
          <IconButton
            aria-label="Close"
            onClick={() => setSupplyDetail((s) => ({ ...s, open: false }))}
            sx={{ position: "absolute", right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {supplyDetail.loading ? (
            <Box sx={{ py: 3, textAlign: "center" }}>
              <CircularProgress size={22} />
            </Box>
          ) : supplyDetail.error ? (
            <Alert severity="error">{supplyDetail.error}</Alert>
          ) : supplyDetail.rows.length === 0 ? (
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>No orders for this product.</Typography>
          ) : (
            <Stack spacing={0.75}>
              {supplyDetail.rows.map((row) => (
                <Box
                  key={row.order_id}
                  sx={{
                    borderBottom: "1px solid #e2e8f0",
                    pb: 0.75,
                  }}
                >
                  <Typography sx={{ fontSize: 13, fontWeight: 700 }}>
                    {row.order_id}
                    {row.customer ? ` · ${row.customer}` : ""}
                  </Typography>
                  <Typography sx={{ fontSize: 11, color: "#64748b" }}>
                    {row.confirmed_for_supply
                      ? `Confirmed ${fmtInt(row.confirmed_loads)} load${Number(row.confirmed_loads) === 1 ? "" : "s"}`
                      : `Provisional · ${row.split_state || "unresolved"}`}
                    {row.supply_interpretation ? ` · ${row.supply_interpretation}` : ""}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </DialogContent>
      </Dialog>

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
