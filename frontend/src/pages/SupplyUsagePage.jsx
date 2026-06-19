import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import OrderSearchDetailDrawer from "../components/orderSearch/OrderSearchDetailDrawer";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import {
  getRinseOrderArchiveDetail,
  getSupplyUsage,
  getSupplyUsageDosages,
  updateSupplyUsageDosages,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { todayRange, yesterdayRange } from "../utils/foldingDateRange";

const DATE_PRESETS = [
  { id: "today", labelKey: "supplyUsage.dateToday" },
  { id: "yesterday", labelKey: "supplyUsage.dateYesterday" },
  { id: "custom", labelKey: "supplyUsage.dateCustom" },
];

const SUMMARY_CARDS = [
  { key: "orders_analyzed", labelKey: "supplyUsage.ordersAnalyzed" },
  { key: "split_orders", labelKey: "supplyUsage.splitOrders" },
  { key: "tide_orders", labelKey: "supplyUsage.tideOrders" },
  { key: "downy_orders", labelKey: "supplyUsage.downyOrders" },
  { key: "oxiclean_orders", labelKey: "supplyUsage.oxicleanOrders" },
  { key: "hypo_orders", labelKey: "supplyUsage.hypoOrders" },
];

const USAGE_SUPPLIES = ["Tide", "Downy", "OxiClean", "All Free & Clear"];

function SummaryCard({ label, value }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.75,
        borderRadius: 2.5,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        minWidth: 0,
        flex: "1 1 150px",
      }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ letterSpacing: 0.2 }}>
        {label}
      </Typography>
      <Typography variant="h5" fontWeight={800} sx={{ lineHeight: 1.15, mt: 0.5 }}>
        {value ?? "—"}
      </Typography>
    </Paper>
  );
}

function UsageCard({ supply, usage }) {
  const row = usage?.[supply] || {};
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2.5,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.tealBorder,
        bgcolor: VEEWASH_DASHBOARD.tealLight,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        minWidth: 0,
        flex: "1 1 200px",
      }}
    >
      <Typography variant="subtitle2" fontWeight={800} gutterBottom>
        {supply}
      </Typography>
      <Stack spacing={0.5}>
        <Typography variant="body2">
          Orders: <strong>{row.orders ?? 0}</strong>
        </Typography>
        <Typography variant="body2">
          Doses: <strong>{row.doses ?? 0}</strong>
        </Typography>
        <Typography variant="body2">
          Ounces: <strong>{row.ounces ?? 0}</strong>
        </Typography>
      </Stack>
    </Paper>
  );
}

export default function SupplyUsagePage() {
  const { t } = useI18n();
  const [datePreset, setDatePreset] = useState("today");
  const [customDate, setCustomDate] = useState(todayRange().start);
  const [activeDateEt, setActiveDateEt] = useState(todayRange().start);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dosages, setDosages] = useState({});
  const [dosageDraft, setDosageDraft] = useState({});
  const [savingDosages, setSavingDosages] = useState(false);
  const [dosageMsg, setDosageMsg] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");

  const applyDate = useCallback((preset, ymd) => {
    setDatePreset(preset);
    setActiveDateEt(ymd);
    if (preset === "custom") setCustomDate(ymd);
  }, []);

  const handlePresetChange = (_e, value) => {
    if (!value) return;
    if (value === "today") applyDate("today", todayRange().start);
    else if (value === "yesterday") applyDate("yesterday", yesterdayRange().start);
    else applyDate("custom", customDate);
  };

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [usageRes, dosageRes] = await Promise.all([
        getSupplyUsage({ date_et: activeDateEt }),
        getSupplyUsageDosages(),
      ]);
      setReport(usageRes.data);
      const d = dosageRes.data || {};
      setDosages(d);
      setDosageDraft(d);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load supply usage");
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [activeDateEt]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const openOrderDetail = async (orderId) => {
    if (!orderId) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    setDetailError("");
    try {
      const res = await getRinseOrderArchiveDetail(orderId);
      setDetail(res.data);
    } catch (e) {
      setDetailError(e?.response?.data?.error || e?.message || "Could not load order detail");
    } finally {
      setDetailLoading(false);
    }
  };

  const saveDosages = async () => {
    setSavingDosages(true);
    setDosageMsg("");
    try {
      const res = await updateSupplyUsageDosages(dosageDraft);
      setDosages(res.data);
      setDosageDraft(res.data);
      setDosageMsg(t("supplyUsage.dosagesSaved"));
      await loadReport();
    } catch (e) {
      setDosageMsg(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSavingDosages(false);
    }
  };

  const orders = report?.orders || [];
  const summary = report?.summary || {};
  const usageBySupply = report?.usage_by_supply || {};
  const mappingRules = report?.mapping_rules || [];

  const dateLabel = useMemo(() => activeDateEt, [activeDateEt]);

  return (
    <Box
      sx={{
        p: { xs: 2, md: 3 },
        maxWidth: 1280,
        mx: "auto",
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h4" fontWeight={800} gutterBottom>
            {t("supplyUsage.title")}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t("supplyUsage.subtitle")}
          </Typography>
        </Box>
        <Button component={RouterLink} to="/maintenance" variant="text" size="small" sx={{ alignSelf: "flex-start" }}>
          {t("nav.maintenance")}
        </Button>
      </Stack>

      <Paper elevation={0} sx={{ p: 2, mb: 3, borderRadius: 2.5, border: "1px solid", borderColor: "divider" }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
          <ToggleButtonGroup exclusive size="small" value={datePreset} onChange={handlePresetChange}>
            {DATE_PRESETS.map((p) => (
              <ToggleButton key={p.id} value={p.id} sx={{ px: 2, fontWeight: 600 }}>
                {t(p.labelKey)}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          {datePreset === "custom" ? (
            <PlanningDatePicker label={t("supplyUsage.dateCustom")} value={customDate} onChange={(ymd) => applyDate("custom", ymd)} />
          ) : null}
          <Typography variant="body2" color="text.secondary" sx={{ ml: { md: "auto" } }}>
            {t("supplyUsage.selectedDate")}: <strong>{dateLabel}</strong>
          </Typography>
        </Stack>
      </Paper>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 3 }}>
            {SUMMARY_CARDS.map(({ key, labelKey }) => (
              <SummaryCard key={key} label={t(labelKey)} value={summary[key] ?? 0} />
            ))}
          </Stack>

          <Typography variant="h6" fontWeight={700} sx={{ mb: 1.5 }}>
            {t("supplyUsage.usageBySupply")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 3 }}>
            {USAGE_SUPPLIES.map((supply) => (
              <UsageCard key={supply} supply={supply} usage={usageBySupply} />
            ))}
          </Stack>

          <Typography variant="h6" fontWeight={700} sx={{ mb: 1 }}>
            {t("supplyUsage.orderDetail")}
          </Typography>
          <TableContainer component={Paper} elevation={0} sx={{ borderRadius: 2.5, border: "1px solid", borderColor: "divider", mb: 4 }}>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ bgcolor: "grey.50" }}>
                  <TableCell>{t("supplyUsage.colOrderId")}</TableCell>
                  <TableCell>{t("supplyUsage.colCustomer")}</TableCell>
                  <TableCell>{t("supplyUsage.colSpecialInstructions")}</TableCell>
                  <TableCell>{t("supplyUsage.colSplitOrder")}</TableCell>
                  <TableCell>{t("supplyUsage.colSuppliesUsed")}</TableCell>
                  <TableCell align="right">{t("supplyUsage.colMultiplier")}</TableCell>
                  <TableCell align="right">{t("supplyUsage.colEstimatedDoses")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {orders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} align="center" sx={{ py: 4, color: "text.secondary" }}>
                      {t("supplyUsage.noOrders")}
                    </TableCell>
                  </TableRow>
                ) : (
                  orders.map((row) => (
                    <TableRow key={row.order_id} hover>
                      <TableCell>
                        <Button
                          variant="text"
                          size="small"
                          sx={{ fontWeight: 700, p: 0, minWidth: 0 }}
                          onClick={() => openOrderDetail(row.order_id)}
                        >
                          {row.order_id}
                        </Button>
                      </TableCell>
                      <TableCell>{row.customer || "—"}</TableCell>
                      <TableCell sx={{ maxWidth: 280, whiteSpace: "normal", wordBreak: "break-word" }}>
                        {row.special_instructions || row.supply_interpretation || "—"}
                      </TableCell>
                      <TableCell>{row.split_order ? t("supplyUsage.yes") : t("supplyUsage.no")}</TableCell>
                      <TableCell>{(row.supplies_used || []).join(", ") || "—"}</TableCell>
                      <TableCell align="right">{row.multiplier ?? 1}</TableCell>
                      <TableCell align="right">{row.estimated_doses ?? 0}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <Paper elevation={0} sx={{ p: 2.5, borderRadius: 2.5, border: "1px solid", borderColor: "divider" }}>
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {t("supplyUsage.settingsTitle")}
            </Typography>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
              {t("supplyUsage.mappingRules")}
            </Typography>
            <Table size="small" sx={{ mb: 3, maxWidth: 640 }}>
              <TableHead>
                <TableRow>
                  <TableCell>{t("supplyUsage.mappingInstructions")}</TableCell>
                  <TableCell>{t("supplyUsage.mappingSupplies")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {mappingRules.map((rule) => (
                  <TableRow key={rule.instructions}>
                    <TableCell>{rule.instructions}</TableCell>
                    <TableCell>{rule.supplies}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              {t("supplyUsage.dosageSettings")}
            </Typography>
            <Stack direction="row" flexWrap="wrap" gap={2} sx={{ mb: 2 }}>
              {USAGE_SUPPLIES.map((supply) => (
                <TextField
                  key={supply}
                  label={`${supply} (oz/dose)`}
                  type="number"
                  size="small"
                  inputProps={{ min: 0.1, step: 0.1 }}
                  value={dosageDraft[supply] ?? ""}
                  onChange={(e) => setDosageDraft((prev) => ({ ...prev, [supply]: e.target.value }))}
                  sx={{ width: 180 }}
                />
              ))}
            </Stack>
            {dosageMsg ? (
              <Alert severity={dosageMsg === t("supplyUsage.dosagesSaved") ? "success" : "error"} sx={{ mb: 2 }}>
                {dosageMsg}
              </Alert>
            ) : null}
            <Button variant="contained" onClick={saveDosages} disabled={savingDosages}>
              {savingDosages ? t("supplyUsage.saving") : t("supplyUsage.saveDosages")}
            </Button>
          </Paper>
        </>
      )}

      <OrderSearchDetailDrawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        detail={detail}
        loading={detailLoading}
        detailError={detailError}
        bagId={detail?.bag_id}
      />
    </Box>
  );
}
