import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  Alert,
  AppBar,
  Button,
  BottomNavigation,
  BottomNavigationAction,
  Box,
  Snackbar,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import {
  Dashboard as DashboardIcon,
  Inventory2,
  LocalShipping,
  UploadFile,
  PrecisionManufacturing,
} from "@mui/icons-material";

import Sidebar from "./components/Sidebar";

import OrdersPage from "./pages/OrdersPage";
import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import MaintenancePage from "./pages/MaintenancePage";
import IssuePage from "./pages/IssuePage";
import EmployeesPage from "./pages/EmployeesPage";
import CheckoutPage from "./pages/CheckoutPage";
import Dashboard from "./pages/Dashboard";
import UploadPage from "./pages/UploadPage";

const MOBILE_TABS = [
  { label: "Dashboard", value: "/dashboard", icon: <DashboardIcon /> },
  { label: "Orders", value: "/orders", icon: <Inventory2 /> },
  { label: "Checkout", value: "/checkout", icon: <LocalShipping /> },
  { label: "Upload", value: "/upload", icon: <UploadFile /> },
  { label: "Prod", value: "/production", icon: <PrecisionManufacturing /> },
];

function MobileTopBar({ pathname }) {
  const activeTab =
    MOBILE_TABS.find((tab) => pathname.startsWith(tab.value)) || MOBILE_TABS[0];

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
        <Typography sx={{ fontSize: 16, fontWeight: 900, lineHeight: 1 }}>
          WashPro
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#6b7280" }}>
          {activeTab.label}
        </Typography>
      </Toolbar>
    </AppBar>
  );
}

function MobileBottomTabs({ pathname }) {
  const navigate = useNavigate();
  const selected =
    MOBILE_TABS.find((tab) => pathname.startsWith(tab.value))?.value || "/dashboard";

  return (
    <BottomNavigation
      showLabels
      value={selected}
      onChange={(_, value) => navigate(value)}
      sx={{
        position: "fixed",
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1200,
        borderTop: "1px solid #e5e7eb",
        height: 62,
      }}
    >
      {MOBILE_TABS.map((tab) => (
        <BottomNavigationAction
          key={tab.value}
          label={tab.label}
          value={tab.value}
          icon={tab.icon}
          sx={{
            minWidth: 0,
            ".MuiBottomNavigationAction-label": { fontSize: 11, fontWeight: 700 },
          }}
        />
      ))}
    </BottomNavigation>
  );
}

function AppShell() {
  const location = useLocation();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const pathname = location.pathname || "/";
  const hideMobileTopBar = pathname === "/checkout";
  const [updateReady, setUpdateReady] = useState(false);

  useEffect(() => {
    const onUpdateReady = () => setUpdateReady(true);
    window.addEventListener("washpro:update-ready", onUpdateReady);
    return () => window.removeEventListener("washpro:update-ready", onUpdateReady);
  }, []);

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
      {!isMobile && <Sidebar />}
      <div className={`main-content ${isMobile ? "main-content-checkout-mobile" : ""}`}>
        {isMobile && !hideMobileTopBar && <MobileTopBar pathname={pathname} />}
        <Box className={isMobile ? (hideMobileTopBar ? "route-scroll-mobile-no-top" : "route-scroll-mobile") : ""}>
          <Routes>
            <Route path="/" element={<OrdersPage />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/checkout" element={<CheckoutPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/employees" element={<EmployeesPage />} />
            <Route path="/issues" element={<IssuePage />} />
            <Route path="/production" element={<ProductionPage />} />
            <Route path="/scoreboard" element={<ScoreboardPage />} />
            <Route path="/maintenance" element={<MaintenancePage />} />
          </Routes>
          {isMobile && <Box sx={{ height: 72 }} />}
        </Box>
      </div>
      {isMobile && <MobileBottomTabs pathname={pathname} />}
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
