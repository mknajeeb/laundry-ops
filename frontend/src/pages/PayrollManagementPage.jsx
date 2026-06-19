import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { getPayoutBatches } from "../api";
import AccountantReportsPanel from "../components/AccountantReportsPanel";
import AccountantPaymentQueuePanel from "../components/AccountantPaymentQueuePanel";
import ContractorManagementPanel from "../components/ContractorManagementPanel";
import PayoutBatchesPanel from "../components/PayoutBatchesPanel";
import PayoutDetailsPanel from "../components/PayoutDetailsPanel";
import PayrollWorkerPaymentsPanel from "../components/PayrollWorkerPaymentsPanel";
import PayrollTaxSettingsPanel from "../components/PayrollTaxSettingsPanel";
import PayrollDocumentsPanel from "../components/PayrollDocumentsPanel";
import PayrollTimeRecordsPanel from "../components/PayrollTimeRecordsPanel";
import PayrollSchedulingPanel from "../components/PayrollSchedulingPanel";
import PayrollPeriodSearchBar from "../components/PayrollPeriodSearchBar";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";
import { PAYROLL_ESTIMATE_PURPOSE } from "../payroll/payrollTaxMessages";

/**
 * Payroll Management — operations vs accountant reporting.
 * Worker categories (W-2, 1099, Temp) stay separate across tabs.
 */
export default function PayrollManagementPage() {
  const { hasPerm, loading: authLoading, user } = useAuth();
  const { t } = useI18n();
  const rolesUpper = useMemo(() => {
    const roles = user?.roles;
    if (Array.isArray(roles) && roles.length) {
      return roles.map((r) => String(r).toUpperCase());
    }
    if (user?.role_code) return [String(user.role_code).toUpperCase()];
    return [];
  }, [user?.roles, user?.role_code]);
  const isAdmin = rolesUpper.includes("ADMIN");
  const isPayrollAdmin = rolesUpper.includes("PAYROLL_ADMIN");
  const isAccountantRole = rolesUpper.includes("ACCOUNTANT");
  const canTime = hasPerm("ta.monitor") || hasPerm("ta.settings") || isAdmin;
  const canPayout = hasPerm("ta.settings") || hasPerm("users.edit") || isAdmin || isPayrollAdmin;
  const canContractors = hasPerm("users.edit") || hasPerm("ta.settings") || isAdmin;
  const canAccountant = hasPerm("users.view") || hasPerm("ta.settings") || isAdmin;
  const canPayoutDetails = canPayout;
  const canAccountantQueue = isAccountantRole && canAccountant;

  const sections = useMemo(() => {
    const out = [];
    if (canTime) out.push({ key: "time", label: "Time Records" });
    if (canTime) out.push({ key: "schedule", label: "Scheduling" });
    if (canPayout) out.push({ key: "batches", label: "Payout Batches" });
    if (canAccountantQueue) out.push({ key: "accountant_queue", label: "Payment Queue" });
    if (canPayoutDetails) out.push({ key: "payout_details", label: "Payout Details" });
    if (canContractors) out.push({ key: "contractors", label: t("payroll.tabContractors") });
    if (canPayout) out.push({ key: "documents", label: "Documents" });
    if (canPayout) out.push({ key: "payments", label: "Worker Payments" });
    if (canPayout) out.push({ key: "taxsettings", label: "Tax Settings" });
    if (canAccountant) out.push({ key: "accountant", label: "Accountant Reports" });
    return out;
  }, [canTime, canPayout, canContractors, canAccountant, canAccountantQueue, canPayoutDetails, t]);

  const [tab, setTab] = useState(0);

  const [payPeriod, setPayPeriod] = useState(() => {
    const r = defaultPayPeriodRange(0);
    return {
      mode: "pay_period",
      start: r.start,
      end: r.end,
      category: "all",
    };
  });

  const onPayPeriodChange = useCallback((patch) => {
    setPayPeriod((prev) => ({ ...prev, ...patch }));
  }, []);

  const [payoutBatchesForSearch, setPayoutBatchesForSearch] = useState([]);

  useEffect(() => {
    if (!canTime && !canPayout) return;
    getPayoutBatches()
      .then((res) => setPayoutBatchesForSearch(res.data?.items || []))
      .catch(() => setPayoutBatchesForSearch([]));
  }, [canTime, canPayout]);

  useEffect(() => {
    if (tab >= sections.length) setTab(Math.max(0, sections.length - 1));
  }, [sections.length, tab]);

  useEffect(() => {
    if (!sections.length) return;
    const accountantOnly = sections.length === 1 && sections[0]?.key === "accountant";
    const readOnlyAccountant = isAccountantRole && !canPayout && !canTime && !isAdmin;
    if (accountantOnly || readOnlyAccountant) {
      const idx = sections.findIndex((s) => s.key === "accountant");
      if (idx >= 0) setTab(idx);
    }
  }, [sections, isAccountantRole, canPayout, canTime, isAdmin]);

  if (authLoading) {
    return (
      <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (!sections.length) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="info">{t("payroll.needMgmtAccess")}</Alert>
      </Box>
    );
  }

  const active = sections[tab] || sections[0];

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, width: "100%", maxWidth: "100%", boxSizing: "border-box" }}>
      <Typography className="no-print" sx={{ fontSize: 28, fontWeight: 700, mb: 0.5 }}>
        {t("payroll.mgmtTitle")}
      </Typography>
      <Typography className="no-print" variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 720 }}>
        Approve time on <strong>Time Records</strong>, then open or create a payout batch for the
        same pay period — approved hours sync automatically by date. W-2, 1099, and temp workers are
        never mixed in one batch.
      </Typography>
      <Alert className="no-print" severity="info" sx={{ mb: 2, maxWidth: 900 }}>
        {PAYROLL_ESTIMATE_PURPOSE}
      </Alert>

      <Tabs
        className="no-print"
        value={tab}
        onChange={(_, v) => setTab(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ borderBottom: 1, borderColor: "divider", mb: 0 }}
      >
        {sections.map((s) => (
          <Tab key={s.key} label={s.label} />
        ))}
      </Tabs>

      {active?.key === "time" || active?.key === "batches" ? (
        <Box sx={{ pt: 2 }}>
          <PayrollPeriodSearchBar
            value={payPeriod}
            onChange={setPayPeriod}
            batches={payoutBatchesForSearch}
          />
        </Box>
      ) : null}

      <Box sx={{ pt: active?.key === "time" || active?.key === "batches" ? 0 : 2 }} role="tabpanel">
        {active?.key === "time" ? (
          <PayrollTimeRecordsPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            linkedCategory={payPeriod.category}
            onPayPeriodChange={onPayPeriodChange}
          />
        ) : null}
        {active?.key === "schedule" ? <PayrollSchedulingPanel /> : null}
        {active?.key === "batches" ? (
          <PayoutBatchesPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            onPayPeriodChange={onPayPeriodChange}
          />
        ) : null}
        {active?.key === "accountant_queue" ? <AccountantPaymentQueuePanel /> : null}
        {active?.key === "payout_details" ? <PayoutDetailsPanel /> : null}
        {active?.key === "contractors" ? <ContractorManagementPanel /> : null}
        {active?.key === "documents" ? <PayrollDocumentsPanel /> : null}
        {active?.key === "payments" ? <PayrollWorkerPaymentsPanel /> : null}
        {active?.key === "taxsettings" ? <PayrollTaxSettingsPanel /> : null}
        {active?.key === "accountant" ? <AccountantReportsPanel /> : null}
      </Box>
    </Box>
  );
}
