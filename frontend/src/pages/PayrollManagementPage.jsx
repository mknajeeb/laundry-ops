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
import AccountantReportsPanel from "../components/AccountantReportsPanel";
import ContractorManagementPanel from "../components/ContractorManagementPanel";
import PayoutBatchesPanel from "../components/PayoutBatchesPanel";
import PayrollWorkerPaymentsPanel from "../components/PayrollWorkerPaymentsPanel";
import PayrollTaxSettingsPanel from "../components/PayrollTaxSettingsPanel";
import PayrollDocumentsPanel from "../components/PayrollDocumentsPanel";
import PayrollTimeRecordsPanel from "../components/PayrollTimeRecordsPanel";
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
  const canTime = hasPerm("ta.monitor") || hasPerm("ta.settings") || isAdmin;
  const canPayout = hasPerm("ta.settings") || hasPerm("users.edit") || isAdmin;
  const canContractors = hasPerm("users.view") || hasPerm("users.edit") || hasPerm("ta.settings") || isAdmin;
  const canAccountant = hasPerm("ta.settings") || hasPerm("users.view") || isAdmin;

  const sections = useMemo(() => {
    const out = [];
    if (canTime) out.push({ key: "time", label: "Time Records" });
    if (canPayout) out.push({ key: "batches", label: "Payout Batches" });
    if (canContractors) out.push({ key: "contractors", label: t("payroll.tabContractors") });
    if (canPayout) out.push({ key: "documents", label: "Documents" });
    if (canPayout) out.push({ key: "payments", label: "Worker Payments" });
    if (canPayout) out.push({ key: "taxsettings", label: "Tax Settings" });
    if (canAccountant) out.push({ key: "accountant", label: "Accountant Reports" });
    return out;
  }, [canTime, canPayout, canContractors, canAccountant, t]);

  const [tab, setTab] = useState(0);

  const [payPeriod, setPayPeriod] = useState(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 13);
    return {
      start: start.toISOString().slice(0, 10),
      end: end.toISOString().slice(0, 10),
      category: "all",
    };
  });

  const onPayPeriodChange = useCallback((patch) => {
    setPayPeriod((prev) => ({ ...prev, ...patch }));
  }, []);

  useEffect(() => {
    if (tab >= sections.length) setTab(Math.max(0, sections.length - 1));
  }, [sections.length, tab]);

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

      <Box sx={{ pt: 2 }} role="tabpanel">
        {active?.key === "time" ? (
          <PayrollTimeRecordsPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            linkedCategory={payPeriod.category}
            onPayPeriodChange={onPayPeriodChange}
          />
        ) : null}
        {active?.key === "batches" ? (
          <PayoutBatchesPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            onPayPeriodChange={onPayPeriodChange}
          />
        ) : null}
        {active?.key === "contractors" ? <ContractorManagementPanel /> : null}
        {active?.key === "documents" ? <PayrollDocumentsPanel /> : null}
        {active?.key === "payments" ? <PayrollWorkerPaymentsPanel /> : null}
        {active?.key === "taxsettings" ? <PayrollTaxSettingsPanel /> : null}
        {active?.key === "accountant" ? <AccountantReportsPanel /> : null}
      </Box>
    </Box>
  );
}
