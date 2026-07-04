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
import { getPayoutBatches, patchPayoutBatch } from "../api";
import AccountantPayrollPanel from "../components/AccountantPayrollPanel";
import AccountantW2DocumentsPanel from "../components/AccountantW2DocumentsPanel";
import PayrollWorkerDocumentsPanel from "../components/PayrollWorkerDocumentsPanel";
import AccountantEmployeePaystubsPanel from "../components/AccountantEmployeePaystubsPanel";
import ContractorManagementPanel from "../components/ContractorManagementPanel";
import W2EmployeeFormsPanel from "../components/W2EmployeeFormsPanel";
import PayoutBatchesPanel from "../components/PayoutBatchesPanel";
import PayoutDetailsPanel from "../components/PayoutDetailsPanel";
import PayrollDashboard from "../components/PayrollDashboard";
import PayrollWorkerPaymentsPanel from "../components/PayrollWorkerPaymentsPanel";
import PayrollTaxSettingsPanel from "../components/PayrollTaxSettingsPanel";
import PayrollTimeRecordsPanel from "../components/PayrollTimeRecordsPanel";
import TaskMaintenancePage from "../pages/TaskMaintenancePage";
import ShiftTaskHistoryPanel from "../components/ShiftTaskHistoryPanel";
import PayrollSchedulingPanel from "../components/PayrollSchedulingPanel";
import PayrollPeriodSearchBar from "../components/PayrollPeriodSearchBar";
import { defaultPayPeriodRange } from "../payroll/payPeriodDefaults";

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
  const isSuperAdmin = rolesUpper.includes("SUPER_ADMIN");
  const isAccountantRole = rolesUpper.includes("ACCOUNTANT");
  const canTime = hasPerm("ta.monitor") || hasPerm("ta.settings") || isAdmin;
  const canPayout = hasPerm("ta.settings") || hasPerm("users.edit") || isAdmin || isPayrollAdmin;
  const canContractors = hasPerm("users.edit") || hasPerm("ta.settings") || isAdmin;
  const canAccountant = hasPerm("users.view") || hasPerm("ta.settings") || isAdmin;
  const canPayoutDetails = canPayout || (isAccountantRole && canAccountant);

  const readOnlyAccountant =
    isAccountantRole && !canPayout && !canTime && !isAdmin && !isPayrollAdmin && !isSuperAdmin;

  const accountantTabs = useMemo(
    () => [
      { key: "accountant_payroll", label: "For Accountant" },
      { key: "accountant_documents", label: "Documents" },
      { key: "accountant_employee", label: "By Employee" },
    ],
    [],
  );

  const sections = useMemo(() => {
    const out = [];
    if (readOnlyAccountant) return [...accountantTabs];
    if (canTime) out.push({ key: "time", label: "Time Records" });
    if (canTime && hasPerm("ta.settings")) out.push({ key: "tasks", label: "Task Maintenance" });
    if (canTime) out.push({ key: "shift_task_history", label: "Shift Task History" });
    if (canPayout) out.push({ key: "batches", label: "Payout Batches" });
    if (canPayout || (isAccountantRole && canAccountant)) {
      out.push(...accountantTabs);
    }
    if (canPayoutDetails) {
      out.push({ key: "payout_details", label: canPayout ? "Finalize Payroll" : "Payment & Details" });
    }
    if (canTime) out.push({ key: "schedule", label: "Scheduling" });
    if (canContractors) out.push({ key: "contractors", label: t("payroll.tabContractors") });
    if (canContractors) out.push({ key: "w2forms", label: t("payroll.tabW2Forms") });
    if (canPayout) out.push({ key: "payments", label: "Worker Payments" });
    if (canPayout) out.push({ key: "taxsettings", label: "Tax Settings" });
    return out;
  }, [
    accountantTabs,
    canTime,
    canPayout,
    canContractors,
    canPayoutDetails,
    readOnlyAccountant,
    isAccountantRole,
    canAccountant,
    hasPerm,
    t,
  ]);

  const [tab, setTab] = useState(0);
  const [detailsBatchId, setDetailsBatchId] = useState(null);
  const [primaryLoading, setPrimaryLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState("");

  const [payPeriod, setPayPeriod] = useState(() => {
    const r = defaultPayPeriodRange(0);
    return {
      mode: "pay_period",
      start: r.start,
      end: r.end,
      category: "all",
    };
  });

  const [payoutBatchesForSearch, setPayoutBatchesForSearch] = useState([]);

  const refreshBatches = useCallback(() => {
    if (!canTime && !canPayout) return;
    getPayoutBatches()
      .then((res) => setPayoutBatchesForSearch(res.data?.items || []))
      .catch(() => setPayoutBatchesForSearch([]));
  }, [canTime, canPayout]);

  useEffect(() => {
    refreshBatches();
  }, [refreshBatches]);

  useEffect(() => {
    if (tab >= sections.length) setTab(Math.max(0, sections.length - 1));
  }, [sections.length, tab]);

  const tabIndexForKey = useCallback(
    (key) => sections.findIndex((s) => s.key === key),
    [sections],
  );

  const goToTab = useCallback(
    (key, batchId = null) => {
      if (batchId) setDetailsBatchId(batchId);
      const idx = tabIndexForKey(key);
      if (idx >= 0) setTab(idx);
    },
    [tabIndexForKey],
  );

  const handleDashboardPrimaryAction = useCallback(
    async (action, batch) => {
      setDashboardError("");
      if (action === "enter_details") {
        setDetailsBatchId(batch?.id);
        goToTab("payout_details");
        return;
      }
      if (action === "view_documents") {
        if (batch?.id) {
          setDetailsBatchId(batch.id);
        }
        goToTab("accountant_documents");
        return;
      }
      if (action === "await_accountant") return;
      if (action === "approve_hours" || action === "mark_paid" || action === "send_to_accountant") {
        if (!batch?.id) return;
        setPrimaryLoading(true);
        try {
          await patchPayoutBatch(batch.id, { action });
          refreshBatches();
          const cat = batch.worker_category || batch.payroll_display?.worker_category;
          const skipsAccountant =
            batch.payroll_display?.skips_accountant_review ||
            cat === "temp" ||
            cat === "contractor_1099";
          if (action === "approve_hours" && skipsAccountant) {
            setDetailsBatchId(batch.id);
            goToTab("payout_details", batch.id);
          } else {
            goToTab("batches");
          }
        } catch (e) {
          setDashboardError(e.response?.data?.error || e.message || "Action failed");
        } finally {
          setPrimaryLoading(false);
        }
      }
    },
    [goToTab, refreshBatches],
  );

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
    <Box sx={{ p: { xs: 1, md: 1.5 }, width: "100%", maxWidth: "100%", boxSizing: "border-box" }}>
      <Typography sx={{ fontSize: 24, fontWeight: 700, mb: 1 }}>
        {readOnlyAccountant ? "Payroll" : t("payroll.mgmtTitle")}
      </Typography>

      {!readOnlyAccountant && canPayout ? (
        <>
          {dashboardError ? (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setDashboardError("")}>
              {dashboardError}
            </Alert>
          ) : null}
          <PayrollDashboard
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            batches={payoutBatchesForSearch}
            onPrimaryAction={handleDashboardPrimaryAction}
            onOpenBatches={() => goToTab("batches")}
            primaryLoading={primaryLoading}
          />
        </>
      ) : null}

      {sections.length > 1 ? (
        <Tabs
          className="no-print"
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: "divider", mb: 0, minHeight: 40 }}
        >
          {sections.map((s) => (
            <Tab key={s.key} label={s.label} sx={{ minHeight: 40, py: 0.5 }} />
          ))}
        </Tabs>
      ) : null}

      {active?.key === "time" || active?.key === "batches" ? (
        <Box sx={{ pt: 1 }}>
          <PayrollPeriodSearchBar
            value={payPeriod}
            onChange={setPayPeriod}
            batches={payoutBatchesForSearch}
          />
        </Box>
      ) : null}

      <Box sx={{ pt: 1 }} role="tabpanel">
        {active?.key === "time" ? (
          <PayrollTimeRecordsPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            linkedCategory={payPeriod.category}
            onPayPeriodChange={setPayPeriod}
          />
        ) : null}
        {active?.key === "tasks" ? <TaskMaintenancePage /> : null}
        {active?.key === "shift_task_history" ? <ShiftTaskHistoryPanel /> : null}
        {active?.key === "schedule" ? <PayrollSchedulingPanel /> : null}
        {active?.key === "batches" ? (
          <PayoutBatchesPanel
            payPeriodStart={payPeriod.start}
            payPeriodEnd={payPeriod.end}
            onPayPeriodChange={setPayPeriod}
            onNavigateTab={goToTab}
            onBatchesChange={refreshBatches}
          />
        ) : null}
        {active?.key === "payout_details" ? (
          <PayoutDetailsPanel initialBatchId={detailsBatchId} />
        ) : null}
        {active?.key === "accountant_payroll" ? <AccountantPayrollPanel /> : null}
        {active?.key === "accountant_documents" ? (
          readOnlyAccountant ? (
            <AccountantW2DocumentsPanel />
          ) : (
            <PayrollWorkerDocumentsPanel />
          )
        ) : null}
        {active?.key === "accountant_employee" ? <AccountantEmployeePaystubsPanel /> : null}
        {active?.key === "contractors" ? <ContractorManagementPanel /> : null}
        {active?.key === "w2forms" ? <W2EmployeeFormsPanel /> : null}
        {active?.key === "payments" ? <PayrollWorkerPaymentsPanel /> : null}
        {active?.key === "taxsettings" ? <PayrollTaxSettingsPanel /> : null}
      </Box>
    </Box>
  );
}
