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
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import RushFilterChips from "../shift/RushFilterChips";
import Step1MetricDrawer from "../shift/Step1MetricDrawer";
import TodayTapCard from "./TodayTapCard";
import ManagementRinseWfReviewSection from "./ManagementRinseWfReviewSection";
import ManagementCopyableId from "./ManagementCopyableId";
import { getManagementTodaySuppliesDetail } from "../../api";
import {
  pickRinseSegments,
  pickWfSpecialty,
  pickWfSupplies,
  pickWfWeights,
  wfHeadline,
  wfIdentityLine,
} from "./todayRinseModel";

const DOSE_TOOLTIP =
  "Split orders may require multiple doses, so doses can exceed orders.";

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

function fmtMoney(v, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
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

function SupplyMetric({ label, value, hint }) {
  const body = (
    <Box
      sx={{
        px: 1,
        py: 0.7,
        borderRadius: 1.25,
        border: "1px solid #e2e8f0",
        bgcolor: "#fff",
        minHeight: 52,
      }}
    >
      <Typography sx={{ fontSize: 16, fontWeight: 800, lineHeight: 1.1, color: "#0f172a" }}>
        {value}
      </Typography>
      <Typography
        sx={{
          mt: 0.25,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          color: "#64748b",
        }}
      >
        {label}
      </Typography>
    </Box>
  );
  if (!hint) return body;
  return (
    <Tooltip title={hint} enterDelay={350} placement="top" arrow>
      <Box>{body}</Box>
    </Tooltip>
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
  const supplyBannerDetail = supplies?.supply_banner_detail || null;
  const supplyStatus = String(supplies?.supply_status || "").toUpperCase();
  const pendingSplitReviews = Number(supplies?.pending_split_reviews || 0);
  const supplyFinalizable = supplies?.supply_finalizable !== false;
  const reviewSummary = reviewProp || rinse?.review || null;
  const dashboard = supplies?.dashboard || null;
  const population = supplies?.population || {};
  const kpis = dashboard?.kpis || {};
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
        cost_per_dose: legacy.cost_per_dose,
        average_dose: legacy.average_dose,
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
    : supplyStatus === "PROVISIONAL" && pendingSplitReviews > 0
      ? `PROVISIONAL · ${pendingSplitReviews} PENDING`
      : supplyStatus || "DAY TOTALS";

  const uniqueOrders =
    dashboard?.unique_orders
    ?? population?.orders
    ?? null;
  const confirmedLoads =
    dashboard?.confirmed_loads
    ?? population?.confirmed_loads
    ?? null;
  const totalDoses = dashboard?.total_doses ?? null;
  const totalQty = dashboard?.total_quantity_used ?? null;
  const totalQtyUnit = dashboard?.quantity_unit || "oz";
  const totalCost = dashboard?.total_supply_cost ?? supplies?.cost ?? null;

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
          <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{supplyBanner}</Typography>
          {supplyBannerDetail ? (
            <Typography sx={{ fontSize: 11, color: "#64748b", mt: 0.35, fontWeight: 500 }}>
              {supplyBannerDetail}
            </Typography>
          ) : (
            <Typography sx={{ fontSize: 11, color: "#64748b", mt: 0.35, fontWeight: 500 }}>
              Costs may increase after pending split reviews are resolved. Confirmed totals
              exclude unresolved split increments.
            </Typography>
          )}
        </Alert>
      ) : null}

      {!snapshotUnavailable && suppliesAvailable && !suppliesPending ? (
        <>
          <Typography
            sx={{
              fontSize: 11,
              fontWeight: 800,
              letterSpacing: 0.6,
              textTransform: "uppercase",
              color: "#64748b",
              mb: 0.5,
            }}
          >
            Supply Cost
          </Typography>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", sm: "repeat(4, minmax(0, 1fr))" },
              gap: 0.75,
              mb: 0.75,
            }}
          >
            <SupplyMetric label="Total Supply Cost" value={fmtMoney(totalCost)} />
            <SupplyMetric
              label="Total Doses"
              value={fmtInt(totalDoses)}
              hint="Sum of confirmed product doses (chemical uses)."
            />
            <SupplyMetric
              label="Total Qty Used"
              value={fmtQty(totalQty, totalQtyUnit)}
            />
            <SupplyMetric
              label="Orders · Loads"
              value={`${fmtInt(uniqueOrders)} · ${fmtInt(confirmedLoads)}`}
              hint="Orders = unique workload bags. Loads = canonical processing units (not sum of product doses)."
            />
          </Box>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "repeat(3, minmax(0, 1fr))" },
              gap: 0.75,
              mb: 1.25,
            }}
          >
            <SupplyMetric
              label="Cost / Order"
              value={fmtMoney(kpis.cost_per_order, 4)}
              hint="Total supply cost ÷ confirmed unique orders."
            />
            <SupplyMetric
              label="Cost / Load"
              value={fmtMoney(kpis.cost_per_load, 4)}
              hint="Total supply cost ÷ confirmed canonical loads."
            />
            <SupplyMetric
              label="Cost / Lb"
              value={
                dashboard?.pounds_available
                  ? fmtMoney(kpis.cost_per_lb, 4)
                  : "—"
              }
              hint={
                dashboard?.pounds_available
                  ? `Based on ${dashboard.pounds_basis || "population"} (${fmtLbs(dashboard.pounds)}).`
                  : "Pounds not yet available for selected population."
              }
            />
          </Box>
        </>
      ) : null}

      <CardGrid columns={{ xs: 1, sm: 2 }}>
        {supplyProducts.map((row) => {
          const key = row.legacy_report_key || row.label;
          const shortLabel =
            key === "OxiClean" ? "Oxi" : key === "All Free & Clear" ? "All Free & Clear" : (row.label || key);
          const doses = row.confirmed_doses ?? row.confirmed_loads;
          const orders = row.orders_using;
          return (
            <TodayTapCard
              key={key}
              label={shortLabel}
              value={
                suppliesPending
                  ? "…"
                  : snapshotUnavailable || !suppliesAvailable
                    ? "—"
                    : `${fmtInt(doses)} doses`
              }
              sub={
                suppliesPending
                  ? "Loading…"
                  : snapshotUnavailable || !suppliesAvailable
                    ? undefined
                    : [
                        `${fmtInt(orders)} orders · ${fmtQty(row.quantity_used, row.quantity_unit)}`,
                        `${fmtMoney(row.estimated_cost)}`,
                        row.cost_per_dose != null ? `${fmtMoney(row.cost_per_dose, 4)}/dose` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
              }
              tooltip={DOSE_TOOLTIP}
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
            <Stack spacing={0}>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "1.1fr 1fr 0.55fr 0.45fr 0.45fr 0.55fr 0.55fr",
                  gap: 0.5,
                  pb: 0.5,
                  mb: 0.5,
                  borderBottom: "1px solid #e2e8f0",
                }}
              >
                {["Bag ID", "Preference", "Split?", "Loads", "Dose", "Qty", "Cost"].map((h) => (
                  <Typography
                    key={h}
                    sx={{
                      fontSize: 9,
                      fontWeight: 800,
                      letterSpacing: 0.4,
                      textTransform: "uppercase",
                      color: "#94a3b8",
                    }}
                  >
                    {h}
                  </Typography>
                ))}
              </Box>
              {supplyDetail.rows.map((row) => (
                <Box
                  key={row.order_id}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "1.1fr 1fr 0.55fr 0.45fr 0.45fr 0.55fr 0.55fr",
                    gap: 0.5,
                    py: 0.65,
                    borderBottom: "1px solid #f1f5f9",
                    opacity: row.confirmed_for_supply ? 1 : 0.72,
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <ManagementCopyableId value={row.bag_id || row.order_id} />
                  </Box>
                  <Typography sx={{ fontSize: 11, color: "#475569", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {row.preference || row.supply_interpretation || "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#334155" }}>
                    {row.split || "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 11, fontWeight: 700 }}>
                    {row.confirmed_for_supply ? fmtInt(row.loads ?? row.confirmed_loads) : "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 11, fontWeight: 700 }}>
                    {row.dose != null ? fmtInt(row.dose) : "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 11 }}>
                    {row.quantity_used != null
                      ? fmtQty(row.quantity_used, row.quantity_unit)
                      : "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 11, fontWeight: 700 }}>
                    {row.estimated_cost != null ? fmtMoney(row.estimated_cost) : "—"}
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
