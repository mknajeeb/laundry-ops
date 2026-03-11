import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  Alert,
  AppBar,
  Button,
  Box,
  IconButton,
  Snackbar,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import {
  ArrowBack,
  Refresh,
  Home as HomeIcon,
  Dashboard as DashboardIcon,
  Inventory2,
  LocalShipping,
  AccessTime,
  PrecisionManufacturing,
} from "@mui/icons-material";

import Sidebar from "./components/Sidebar";

import OrdersPage from "./pages/OrdersPage";
import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import MaintenancePage from "./pages/MaintenancePage";
import IssuePage from "./pages/IssuePage";
import EmployeesPage from "./pages/EmployeesPage";
import ClockPage from "./pages/ClockPage";
import CheckoutPage from "./pages/CheckoutPage";
import Dashboard from "./pages/Dashboard";
import UploadPage from "./pages/UploadPage";
import HomePage from "./pages/HomePage";
import { getCurrentUploadBatch } from "./api";

const MOBILE_TABS = [
  { label: "Home", value: "/", icon: <HomeIcon /> },
  { label: "Dashboard", value: "/dashboard", icon: <DashboardIcon /> },
  { label: "Orders", value: "/orders", icon: <Inventory2 /> },
  { label: "Checkout", value: "/checkout", icon: <LocalShipping /> },
  { label: "Clock", value: "/clock", icon: <AccessTime /> },
  { label: "Prod", value: "/production", icon: <PrecisionManufacturing /> },
];

function getActiveMobileTab(pathname) {
  if (pathname === "/") return MOBILE_TABS[0];
  return MOBILE_TABS.find((tab) => tab.value !== "/" && pathname.startsWith(tab.value)) || MOBILE_TABS[0];
}

function MobileTopBar({ pathname }) {
  const navigate = useNavigate();
  const activeTab = getActiveMobileTab(pathname);
  const canGoBack = pathname !== "/";

  return (
    <AppBar
      position="sticky"
      elevation={0}
      sx={{
        top: 0,
        background: "#ffffff",
        color: "#111827",
        borderBottom: "1px solid #e5e7eb",
      }}
    >
      <Toolbar sx={{ minHeight: "48px !important", px: 1.2 }}>
        {canGoBack ? (
          <IconButton
            size="small"
            onClick={() => navigate(-1)}
            sx={{ mr: 0.5, border: "1px solid #e5e7eb" }}
          >
            <ArrowBack sx={{ fontSize: 16 }} />
          </IconButton>
        ) : (
          <Box sx={{ width: 34 }} />
        )}
        <Typography sx={{ fontSize: 16, fontWeight: 600, lineHeight: 1 }}>
          Washpro
        </Typography>
        <Box sx={{ flex: 1 }} />
        <IconButton
          size="small"
          onClick={() => window.location.reload()}
          sx={{ mr: 0.5, border: "1px solid #e5e7eb" }}
        >
          <Refresh sx={{ fontSize: 16 }} />
        </IconButton>
        <Typography sx={{ fontSize: 13, fontWeight: 500, color: "#6b7280" }}>
          {activeTab.label}
        </Typography>
      </Toolbar>
    </AppBar>
  );
}

function AppShell() {
  const location = useLocation();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const pathname = location.pathname || "/";
  const [updateReady, setUpdateReady] = useState(false);
  const [activeBatch, setActiveBatch] = useState(null);

  useEffect(() => {
    const onUpdateReady = () => setUpdateReady(true);
    window.addEventListener("washpro:update-ready", onUpdateReady);
    return () => window.removeEventListener("washpro:update-ready", onUpdateReady);
  }, []);

  useEffect(() => {
    async function loadActiveBatch() {
      try {
        const res = await getCurrentUploadBatch();
        setActiveBatch(res?.data || null);
      } catch (error) {
        console.error(error);
        setActiveBatch(null);
      }
    }
    loadActiveBatch();
  }, [pathname]);

  const handleRefreshApp = async () => {
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      if (registration?.waiting) {
        registration.waiting.postMessage({ type: "SKIP_WAITING" });
      }
      window.location.reload();
    } catch (error) {
      console.error("Failed to refresh app:", error);
      window.location.reload();
    }
  };

  return (
    <div className={`app-layout ${isMobile ? "app-layout-checkout-mobile" : ""}`}>
      {!isMobile && <Sidebar activeBatch={activeBatch} />}
      <div className={`main-content ${isMobile ? "main-content-checkout-mobile" : ""}`}>
        {isMobile && <MobileTopBar pathname={pathname} />}
        <Box className={isMobile ? "route-scroll-mobile" : ""}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/checkout" element={<CheckoutPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/employees" element={<EmployeesPage />} />
            <Route path="/clock" element={<ClockPage />} />
            <Route path="/issues" element={<IssuePage />} />
            <Route path="/production" element={<ProductionPage />} />
            <Route path="/scoreboard" element={<ScoreboardPage />} />
            <Route path="/maintenance" element={<MaintenancePage />} />
          </Routes>
        </Box>
      </div>
      <Snackbar
        open={updateReady}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
        onClose={() => setUpdateReady(false)}
      >
        <Alert
          severity="info"
          variant="filled"
          action={
            <Button color="inherit" size="small" onClick={handleRefreshApp}>
              Refresh
            </Button>
          }
          onClose={() => setUpdateReady(false)}
        >
          New app update is ready.
        </Alert>
      </Snackbar>
    </div>
  );
}

function App(){

  return(

    <BrowserRouter>
      <AppShell />

    </BrowserRouter>

  )

}

export default App;
