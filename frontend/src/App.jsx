import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  IconButton,
  Snackbar,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { ArrowBack, Refresh } from "@mui/icons-material";
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
import LoginPage from "./pages/LoginPage";
import InventoryPage from "./pages/InventoryPage";
import DiscrepanciesPage from "./pages/DiscrepanciesPage";
import { authLogout, authMe, clearAuthSession, getCurrentUploadBatch, getSavedUser } from "./api";

function MobileTopBar({ pathname }) {
  const navigate = useNavigate();
  const canGoBack = pathname !== "/";
  return (
    <AppBar position="sticky" elevation={0} sx={{ top: 0, background: "#ffffff", color: "#0f172a", borderBottom: "1px solid #e2e8f0" }}>
      <Toolbar sx={{ minHeight: "50px !important", px: 1 }}>
        {canGoBack ? (
          <IconButton size="small" onClick={() => navigate(-1)} sx={{ mr: 1 }}><ArrowBack sx={{ fontSize: 18 }} /></IconButton>
        ) : <Box sx={{ width: 36 }} />}
        <Typography sx={{ fontSize: 18, flex: 1 }}>Washpro</Typography>
        <IconButton size="small" onClick={() => window.location.reload()}><Refresh sx={{ fontSize: 18 }} /></IconButton>
      </Toolbar>
    </AppBar>
  );
}

function GuardedRoute({ user, roles, children }) {
  if (!user) return <Navigate to="/login" replace />;
  if (!roles?.length) return children;
  const userRoles = (user.roles || []).map((r) => String(r).toUpperCase());
  const ok = roles.some((r) => userRoles.includes(String(r).toUpperCase()));
  return ok ? children : <Navigate to="/" replace />;
}

function AppShell() {
  const location = useLocation();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const [updateReady, setUpdateReady] = useState(false);
  const [activeBatch, setActiveBatch] = useState(null);
  const [user, setUser] = useState(getSavedUser());
  const [authLoading, setAuthLoading] = useState(true);

  const pathname = location.pathname || "/";

  const doLogout = async () => {
    try { await authLogout(); } catch (_) { /* ignore */ }
    clearAuthSession();
    setUser(null);
  };

  useEffect(() => {
    async function bootstrap() {
      if (pathname === "/login") {
        setAuthLoading(false);
        return;
      }
      try {
        const res = await authMe();
        setUser(res.data || null);
      } catch (e) {
        console.error(e);
        clearAuthSession();
        setUser(null);
      } finally {
        setAuthLoading(false);
      }
    }
    bootstrap();
  }, [pathname]);

  useEffect(() => {
    const onUpdateReady = () => setUpdateReady(true);
    window.addEventListener("washpro:update-ready", onUpdateReady);
    return () => window.removeEventListener("washpro:update-ready", onUpdateReady);
  }, []);

  useEffect(() => {
    async function loadBatch() {
      try {
        const res = await getCurrentUploadBatch();
        setActiveBatch(res?.data || null);
      } catch (_) {
        setActiveBatch(null);
      }
    }
    loadBatch();
  }, [pathname]);

  const shellBackground = useMemo(
    () => "linear-gradient(145deg, #f8fbff 0%, #f2f6ff 45%, #f7fafc 100%)",
    []
  );

  if (authLoading && pathname !== "/login") {
    return <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><Typography>Loading...</Typography></Box>;
  }

  if (!user && pathname !== "/login") return <Navigate to="/login" replace />;

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", background: shellBackground }}>
      {!isMobile && user && <Sidebar activeBatch={activeBatch} user={user} onLogout={doLogout} />}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {isMobile && user && <MobileTopBar pathname={pathname} />}
        <Box sx={{ p: { xs: 0, md: 1 } }}>
          <Routes>
            <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage onLoggedIn={setUser} />} />
            <Route path="/" element={<GuardedRoute user={user}><HomePage /></GuardedRoute>} />
            <Route path="/dashboard" element={<GuardedRoute user={user}><Dashboard /></GuardedRoute>} />
            <Route path="/orders" element={<GuardedRoute user={user}><OrdersPage user={user} /></GuardedRoute>} />
            <Route path="/checkout" element={<GuardedRoute user={user}><CheckoutPage user={user} /></GuardedRoute>} />
            <Route path="/upload" element={<GuardedRoute user={user} roles={["ADMIN", "OPS"]}><UploadPage /></GuardedRoute>} />
            <Route path="/employees" element={<GuardedRoute user={user} roles={["ADMIN"]}><EmployeesPage user={user} /></GuardedRoute>} />
            <Route path="/clock" element={<GuardedRoute user={user}><ClockPage user={user} /></GuardedRoute>} />
            <Route path="/issues" element={<GuardedRoute user={user}><IssuePage /></GuardedRoute>} />
            <Route path="/production" element={<GuardedRoute user={user}><ProductionPage /></GuardedRoute>} />
            <Route path="/scoreboard" element={<GuardedRoute user={user}><ScoreboardPage /></GuardedRoute>} />
            <Route path="/maintenance" element={<GuardedRoute user={user}><MaintenancePage /></GuardedRoute>} />
            <Route path="/inventory" element={<GuardedRoute user={user}><InventoryPage user={user} /></GuardedRoute>} />
            <Route path="/discrepancies" element={<GuardedRoute user={user} roles={["ADMIN", "OPS"]}><DiscrepanciesPage /></GuardedRoute>} />
          </Routes>
        </Box>
      </Box>

      <Snackbar open={updateReady} anchorOrigin={{ vertical: "top", horizontal: "center" }} onClose={() => setUpdateReady(false)}>
        <Alert severity="info" variant="filled" action={<Button color="inherit" size="small" onClick={() => window.location.reload()}>Refresh</Button>}>
          New app update is ready.
        </Alert>
      </Snackbar>
    </Box>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

export default App;
