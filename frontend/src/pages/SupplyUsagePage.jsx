import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import OrderSearchDetailDrawer from "../components/orderSearch/OrderSearchDetailDrawer";
import PlanningDatePicker from "../components/datetime/PlanningDatePicker";
import {
  getRinseOrderArchiveDetail,
  getSupplyUsage,
  getSupplyUsageDosages,
  updateSupplyUsageDosages,
  updateSupplyUsageMappingRules,
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
  { key: "orders_analyzed", labelKey: "supplyUsage.ordersAnalyzed", filter: { type: "all" } },
  { key: "split_orders", labelKey: "supplyUsage.splitOrders", filter: { type: "split" } },
  { key: "tide_orders", labelKey: "supplyUsage.tideOrders", filter: { type: "supply", supply: "Tide" } },
  { key: "downy_orders", labelKey: "supplyUsage.downyOrders", filter: { type: "supply", supply: "Downy" } },
  { key: "oxiclean_orders", labelKey: "supplyUsage.oxicleanOrders", filter: { type: "supply", supply: "OxiClean" } },
  {
    key: "hypo_orders",
    labelKey: "supplyUsage.hypoOrders",
    filter: { type: "supply", supply: "All Free & Clear" },
  },
];

const USAGE_SUPPLIES = ["Tide", "Downy", "OxiClean", "All Free & Clear"];

const CLICKABLE_NUMBER_SX = {
  cursor: "pointer",
  textDecoration: "none",
  color: "inherit",
  "&:hover": { textDecoration: "underline" },
};

function normalizeMappingRule(rule) {
  const supplies = Array.isArray(rule?.supplies)
    ? rule.supplies
    : String(rule?.supplies || "")
        .split(/[,+]+/)
        .map((s) => s.trim())
        .filter(Boolean);
  return {
    instructions: rule?.instructions || "",
    supplies,
    default: Boolean(rule?.default),
  };
}

function mappingRulesFromReport(reportRules) {
  return (reportRules || []).map(normalizeMappingRule);
}

function orderMatchesFilter(row, filter) {
  if (!filter || filter.type === "all") return true;
  if (filter.type === "split") return Boolean(row.split_order);
  if (filter.type === "supply") {
    return (row.supplies_used || []).includes(filter.supply);
  }
  return true;
}

function filtersEqual(a, b) {
  if (!a && !b) return true;
  if (!a || !b) return false;
  if (a.type !== b.type) return false;
  if (a.type === "supply") return a.supply === b.supply;
  return true;
}

function SummaryCard({ label, value, onValueClick, active }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.75,
        borderRadius: 2.5,
        border: "1px solid",
        borderColor: active ? VEEWASH_DASHBOARD.primaryBlue : VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: active ? VEEWASH_DASHBOARD.primaryBlueLight : "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        minWidth: 0,
        flex: "1 1 150px",
      }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ letterSpacing: 0.2 }}>
        {label}
      </Typography>
      <Typography
        variant="h5"
        fontWeight={800}
        component="button"
        type="button"
        onClick={onValueClick}
        sx={{
          ...CLICKABLE_NUMBER_SX,
          lineHeight: 1.15,
          mt: 0.5,
          border: 0,
          bgcolor: "transparent",
          p: 0,
          font: "inherit",
          textAlign: "left",
        }}
      >
        {value ?? "—"}
      </Typography>
    </Paper>
  );
}

function UsageCard({ supply, usage, onMetricClick, active }) {
  const row = usage?.[supply] || {};
  const handleClick = () => onMetricClick?.({ type: "supply", supply });

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2.5,
        border: active ? "2px solid" : "1px solid",
        borderColor: active ? VEEWASH_DASHBOARD.teal : VEEWASH_DASHBOARD.tealBorder,
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
          Orders:{" "}
          <Box
            component="button"
            type="button"
            onClick={handleClick}
            sx={{
              ...CLICKABLE_NUMBER_SX,
              border: 0,
              bgcolor: "transparent",
              p: 0,
              font: "inherit",
              fontWeight: 700,
            }}
          >
            {row.orders ?? 0}
          </Box>
        </Typography>
        <Typography variant="body2">
          Doses:{" "}
          <Box
            component="button"
            type="button"
            onClick={handleClick}
            sx={{
              ...CLICKABLE_NUMBER_SX,
              border: 0,
              bgcolor: "transparent",
              p: 0,
              font: "inherit",
              fontWeight: 700,
            }}
          >
            {row.doses ?? 0}
          </Box>
        </Typography>
        <Typography variant="body2">
          Ounces:{" "}
          <Box
            component="button"
            type="button"
            onClick={handleClick}
            sx={{
              ...CLICKABLE_NUMBER_SX,
              border: 0,
              bgcolor: "transparent",
              p: 0,
              font: "inherit",
              fontWeight: 700,
            }}
          >
            {row.ounces ?? 0}
          </Box>
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
  const [mappingRulesDraft, setMappingRulesDraft] = useState([]);
  const [savingMappingRules, setSavingMappingRules] = useState(false);
  const [mappingRulesMsg, setMappingRulesMsg] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [orderFilter, setOrderFilter] = useState({ type: "all" });

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
      setMappingRulesDraft(mappingRulesFromReport(usageRes.data?.mapping_rules));
      setOrderFilter({ type: "all" });
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

  const scrollToOrderTable = () => {
    document.getElementById("supply-usage-orders-table")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const applyOrderFilter = useCallback((filter) => {
    setOrderFilter(filter);
    scrollToOrderTable();
  }, []);

  const clearOrderFilter = () => applyOrderFilter({ type: "all" });

  const filterLabel = useMemo(() => {
    if (!orderFilter || orderFilter.type === "all") return null;
    if (orderFilter.type === "split") return t("supplyUsage.splitOrders");
    if (orderFilter.type === "supply") {
      if (orderFilter.supply === "All Free & Clear") return t("supplyUsage.hypoOrders");
      if (orderFilter.supply === "Tide") return t("supplyUsage.tideOrders");
      if (orderFilter.supply === "Downy") return t("supplyUsage.downyOrders");
      if (orderFilter.supply === "OxiClean") return t("supplyUsage.oxicleanOrders");
      return `${orderFilter.supply} orders`;
    }
    return null;
  }, [orderFilter, t]);

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

  const saveMappingRules = async () => {
    setSavingMappingRules(true);
    setMappingRulesMsg("");
    try {
      const payload = mappingRulesDraft.map((rule) => ({
        instructions: rule.instructions,
        supplies: rule.supplies,
        ...(rule.default ? { default: true } : {}),
      }));
      const res = await updateSupplyUsageMappingRules({ mapping_rules: payload });
      const saved = mappingRulesFromReport(res.data);
      setMappingRulesDraft(saved);
      setMappingRulesMsg(t("supplyUsage.mappingRulesSaved"));
      await loadReport();
    } catch (e) {
      setMappingRulesMsg(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSavingMappingRules(false);
    }
  };

  const addMappingRule = () => {
    setMappingRulesDraft((prev) => [...prev, { instructions: "", supplies: ["Tide"] }]);
  };

  const updateMappingRule = (index, patch) => {
    setMappingRulesDraft((prev) => prev.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  };

  const deleteMappingRule = (index) => {
    setMappingRulesDraft((prev) => prev.filter((_, i) => i !== index));
  };

  const orders = report?.orders || [];
  const summary = report?.summary || {};
  const usageBySupply = report?.usage_by_supply || {};

  const filteredOrders = useMemo(
    () => orders.filter((row) => orderMatchesFilter(row, orderFilter)),
    [orders, orderFilter],
  );

  const dateLabel = useMemo(() => activeDateEt, [activeDateEt]);
  const filterActive = orderFilter && orderFilter.type !== "all";

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
      {!loading && report?.supply_banner && report?.supply_finalizable === false ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {report.supply_banner}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 3 }}>
            {SUMMARY_CARDS.map(({ key, labelKey, filter }) => (
              <SummaryCard
                key={key}
                label={t(labelKey)}
                value={summary[key] ?? 0}
                onValueClick={() => applyOrderFilter(filter)}
                active={filtersEqual(orderFilter, filter)}
              />
            ))}
          </Stack>

          <Typography variant="h6" fontWeight={700} sx={{ mb: 1.5 }}>
            {t("supplyUsage.usageBySupply")}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={1.5} sx={{ mb: 3 }}>
            {USAGE_SUPPLIES.map((supply) => (
              <UsageCard
                key={supply}
                supply={supply}
                usage={usageBySupply}
                onMetricClick={applyOrderFilter}
                active={orderFilter?.type === "supply" && orderFilter.supply === supply}
              />
            ))}
          </Stack>

          <Stack
            id="supply-usage-orders-table"
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            alignItems={{ sm: "center" }}
            spacing={1}
            sx={{ mb: 1 }}
          >
            <Typography variant="h6" fontWeight={700}>
              {t("supplyUsage.orderDetail")}
            </Typography>
            {filterActive && filterLabel ? (
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Chip
                  label={`${t("supplyUsage.showingPrefix")}: ${filterLabel} (${filteredOrders.length})`}
                  color="primary"
                  variant="outlined"
                  onDelete={clearOrderFilter}
                />
                <Button size="small" onClick={clearOrderFilter}>
                  {t("supplyUsage.clearFilter")}
                </Button>
              </Stack>
            ) : null}
          </Stack>
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
                ) : filteredOrders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} align="center" sx={{ py: 4, color: "text.secondary" }}>
                      {t("supplyUsage.noOrdersFiltered")}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredOrders.map((row) => (
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
                        {row.special_instructions || "—"}
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
            <TableContainer component={Paper} elevation={0} sx={{ mb: 2, maxWidth: 900, border: "1px solid", borderColor: "divider" }}>
              <Table size="small">
                <TableHead>
                  <TableRow sx={{ bgcolor: "grey.50" }}>
                    <TableCell>{t("supplyUsage.mappingInstructions")}</TableCell>
                    <TableCell>{t("supplyUsage.mappingSupplies")}</TableCell>
                    <TableCell align="right" width={72} />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {mappingRulesDraft.map((rule, index) => (
                    <TableRow key={`mapping-rule-${index}`}>
                      <TableCell sx={{ minWidth: 260, whiteSpace: "normal" }}>
                        <TextField
                          size="small"
                          fullWidth
                          multiline
                          maxRows={3}
                          value={rule.instructions}
                          placeholder={rule.default ? "None / default" : "Instruction pattern"}
                          onChange={(e) => updateMappingRule(index, { instructions: e.target.value })}
                        />
                      </TableCell>
                      <TableCell>
                        <Autocomplete
                          multiple
                          size="small"
                          options={USAGE_SUPPLIES}
                          value={rule.supplies || []}
                          onChange={(_e, value) => updateMappingRule(index, { supplies: value })}
                          renderInput={(params) => <TextField {...params} placeholder="Supplies" />}
                        />
                      </TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          aria-label={t("supplyUsage.deleteRule")}
                          onClick={() => deleteMappingRule(index)}
                          disabled={rule.default}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
              <Button variant="outlined" size="small" onClick={addMappingRule}>
                {t("supplyUsage.addMappingRule")}
              </Button>
              <Button variant="contained" size="small" onClick={saveMappingRules} disabled={savingMappingRules}>
                {savingMappingRules ? t("supplyUsage.saving") : t("supplyUsage.saveMappingRules")}
              </Button>
            </Stack>
            {mappingRulesMsg ? (
              <Alert
                severity={mappingRulesMsg === t("supplyUsage.mappingRulesSaved") ? "success" : "error"}
                sx={{ mb: 2 }}
              >
                {mappingRulesMsg}
              </Alert>
            ) : null}

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
