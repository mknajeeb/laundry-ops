import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import DashboardIcon from "@mui/icons-material/Dashboard";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import LocalShippingIcon from "@mui/icons-material/LocalShipping";
import AssessmentIcon from "@mui/icons-material/Assessment";
import SettingsIcon from "@mui/icons-material/Settings";
import { useNavigate } from "react-router-dom";
import { authLogout, clearAuthSession, getInventoryBootstrap, getInventoryBagPrice } from "../api";
import DashboardTab from "../components/inventory/DashboardTab";
import StockCheckTab from "../components/inventory/StockCheckTab";
import PurchaseOrdersTab from "../components/inventory/OrdersTab";
import ReportsTab from "../components/inventory/ReportsTab";
import SettingsTab from "../components/inventory/SettingsTab";
import { LoadingBlock, StatusAlert } from "../components/inventory/InventoryShared";
import OpsFloorStockFlow from "../opsMobile/OpsFloorStockFlow";
import { INV_NAV_SX } from "../utils/inventoryHelpers";
import { isFloorInventoryWorkflow } from "../utils/inventoryFloorHelpers";
import { canAccessInventoryTab, getInventoryRoleTier } from "../utils/inventoryRoleHelpers";
import { useAuth } from "../context/AuthContext";
import {
  clearPinHubAppSession,
  clearPinHubSession,
  loadPinHubAppSession,
  pinHubMenuPath,
} from "../utils/pinHubSession";

const ALL_TABS = [
  { key: "dashboard", label: "Dashboard", icon: DashboardIcon },
  { key: "check", label: "Stock Check", icon: FactCheckIcon },
  { key: "orders", label: "Purchase Orders", icon: LocalShippingIcon },
  { key: "reports", label: "Reports", icon: AssessmentIcon },
  { key: "settings", label: "Settings", icon: SettingsIcon },
];

export default function InventoryPage({ user, onPinHubDone }) {
  const navigate = useNavigate();
  const { hasPerm } = useAuth();
  const pinHubApp = useMemo(() => loadPinHubAppSession(), []);
  const floorWorkflow = useMemo(
    () => isFloorInventoryWorkflow({ pinHubApp }),
    [pinHubApp],
  );
  const roleTier = useMemo(() => getInventoryRoleTier(user), [user]);
  const visibleTabs = useMemo(
    () => ALL_TABS.filter((t) => canAccessInventoryTab(roleTier, t.key, hasPerm)),
    [roleTier, hasPerm],
  );

  const [tabKey, setTabKey] = useState("dashboard");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState({ type: "", text: "" });

  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [latestCheck, setLatestCheck] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [bagPrice, setBagPrice] = useState(10);
  const [varianceThreshold, setVarianceThreshold] = useState(5);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [bootRes, priceRes] = await Promise.all([
        getInventoryBootstrap(),
        getInventoryBagPrice().catch(() => ({ data: { bag_default_price: 10 } })),
      ]);
      const boot = bootRes?.data || {};
      setItems(boot.items || []);
      setCategories(boot.categories || []);
      setLatestCheck(boot.latest_check);
      setDashboard(boot.dashboard);
      setSuggestions(
        boot.dashboard?.low_stock?.length
          ? boot.dashboard.low_stock.map((r) => ({
              ...r,
              id: r.id,
              name: r.name,
              suggested_qty: r.suggested_qty,
            }))
          : [],
      );
      setVarianceThreshold(boot.dashboard?.kpis?.variance_threshold ?? 5);
      setBagPrice(Number(priceRes?.data?.bag_default_price || 0));
      if (roleTier !== "floor" && !floorWorkflow) {
        const { getInventoryVendors, getInventoryReorderSuggestions } = await import("../api");
        const [vRes, sRes] = await Promise.all([
          getInventoryVendors({ with_stats: roleTier === "admin" ? "1" : "0" }).catch(() => ({ data: [] })),
          getInventoryReorderSuggestions().catch(() => ({ data: [] })),
        ]);
        setVendors(vRes?.data || []);
        setSuggestions(sRes?.data || []);
      }
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: "Inventory load failed." });
    } finally {
      setLoading(false);
    }
  }, [roleTier, floorWorkflow]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (floorWorkflow) return;
    if (!visibleTabs.some((t) => t.key === tabKey)) {
      setTabKey(visibleTabs[0]?.key || "dashboard");
    }
  }, [visibleTabs, tabKey, floorWorkflow]);

  const handleMessage = (msg) => {
    setMessage(msg);
    if (msg?.type === "success") setTimeout(() => setMessage({ type: "", text: "" }), 4000);
  };

  const clearWashproSession = async () => {
    try {
      await authLogout();
    } catch {
      /* ignore */
    }
    clearAuthSession();
    try {
      localStorage.removeItem("ta_token");
    } catch {
      /* ignore */
    }
    onPinHubDone?.();
  };

  /** Back / Done — leave inventory app session, keep PIN hub unlock. */
  const returnToPinMenu = async () => {
    const slug = pinHubApp?.organization_slug || user?.organization_slug || "";
    clearPinHubAppSession();
    await clearWashproSession();
    navigate(pinHubMenuPath(slug), { replace: true });
  };

  /** Lock — clear hub unlock + inventory session; no punch / no submit. */
  const lockToPinEntry = async () => {
    const slug = pinHubApp?.organization_slug || user?.organization_slug || "";
    clearPinHubAppSession();
    clearPinHubSession();
    await clearWashproSession();
    navigate(pinHubMenuPath(slug), { replace: true });
  };

  const tabIndex = Math.max(0, visibleTabs.findIndex((t) => t.key === tabKey));

  if (loading && !dashboard && !items.length) {
    return (
      <Box className="page" sx={{ maxWidth: 960, mx: "auto", width: "100%" }}>
        <LoadingBlock />
      </Box>
    );
  }

  if (floorWorkflow) {
    return (
      <OpsFloorStockFlow
        user={user}
        items={items}
        categories={categories}
        varianceThreshold={varianceThreshold}
        onRefresh={load}
        onBack={returnToPinMenu}
        onDone={returnToPinMenu}
        onLock={lockToPinEntry}
      />
    );
  }

  return (
    <Box className="page" sx={{ maxWidth: 960, mx: "auto", width: "100%", px: { xs: 1.5, sm: 2 }, pb: { xs: 2, md: 0 } }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5, fontSize: { xs: "1.35rem", sm: "1.5rem" } }}>
        Inventory
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        What you have, what to buy, and full purchase history.
      </Typography>

      <StatusAlert message={message} onClose={() => setMessage({ type: "", text: "" })} />

      <Box sx={INV_NAV_SX}>
        <Tabs
          value={tabIndex}
          onChange={(_, v) => setTabKey(visibleTabs[v]?.key || "dashboard")}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
          sx={{
            minHeight: 52,
            "& .MuiTab-root": {
              minHeight: 52,
              minWidth: "auto",
              px: { xs: 1.25, sm: 2 },
              fontSize: { xs: "0.72rem", sm: "0.875rem" },
            },
          }}
        >
          {visibleTabs.map((t) => {
            const Icon = t.icon;
            return (
              <Tab
                key={t.key}
                icon={<Icon sx={{ fontSize: { xs: 18, sm: 20 } }} />}
                iconPosition="start"
                label={t.label}
              />
            );
          })}
        </Tabs>
      </Box>

      {tabKey === "dashboard" ? (
        <DashboardTab
          dashboard={dashboard}
          roleTier={roleTier}
          onCreatePO={() => setTabKey("orders")}
          onGoCheck={() => setTabKey("check")}
        />
      ) : null}

      {tabKey === "check" ? (
        <StockCheckTab
          user={user}
          items={items}
          categories={categories}
          latestCheck={latestCheck}
          varianceThreshold={varianceThreshold}
          onRefresh={load}
          onMessage={handleMessage}
          onGoDashboard={() => setTabKey("dashboard")}
        />
      ) : null}

      {tabKey === "orders" ? (
        <PurchaseOrdersTab
          suggestions={suggestions}
          vendors={vendors}
          categories={categories}
          items={items}
          onRefresh={load}
          onMessage={handleMessage}
        />
      ) : null}

      {tabKey === "reports" ? <ReportsTab /> : null}

      {tabKey === "settings" ? (
        <SettingsTab
          user={user}
          items={items}
          categories={categories}
          vendors={vendors}
          bagPrice={bagPrice}
          varianceThreshold={varianceThreshold}
          roleTier={roleTier}
          hasPerm={hasPerm}
          onRefresh={load}
          onMessage={handleMessage}
        />
      ) : null}
    </Box>
  );
}
