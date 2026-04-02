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
import { useI18n } from "./i18n/I18nContext";

import OrdersPage from "./pages/OrdersPage";
import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import MaintenancePage from "./pages/MaintenancePage";
import IssuePage from "./pages/IssuePage";
import PeoplePage from "./pages/PeoplePage";
import ClockPage from "./pages/ClockPage";
import CheckoutPage from "./pages/CheckoutPage";
import Dashboard from "./pages/Dashboard";
import UploadPage from "./pages/UploadPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import InventoryPage from "./pages/InventoryPage";
import DiscrepanciesPage from "./pages/DiscrepanciesPage";
import PayrollManagementPage from "./pages/PayrollManagementPage";
import PermissionsPage from "./pages/PermissionsPage";
import OrganizationSettingsPage from "./pages/OrganizationSettingsPage";
import { authLogout, authMe, clearAuthSession, getCurrentUploadBatch, getSavedUser } from "./api";

function MobileTopBar({ pathname, user }) {
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();
  const canGoBack = pathname !== "/";
  return (
    <AppBar
      position="sticky"
      elevation={0}
      sx={{
        top: 0,
        pt: "env(safe-area-inset-top, 0px)",
        background: "#ffffff",
        color: "#0f172a",
        borderBottom: "1px solid #e2e8f0",
      }}
    >
      <Toolbar sx={{ minHeight: "50px !important", px: 1 }}>
        {canGoBack ? (
          <IconButton size="small" onClick={() => navigate(-1)} sx={{ mr: 1 }}><ArrowBack sx={{ fontSize: 18 }} /></IconButton>
        ) : <Box sx={{ width: 36 }} />}
        <Box sx={{ flex: 1, display: "flex", alignItems: "center", minHeight: 28 }}>
          {user?.organization_logo_url ? (
            <Box
              component="img"
              src={user.organization_logo_url}
              alt=""
              sx={{ maxHeight: 26, maxWidth: 160, objectFit: "contain" }}
            />
          ) : (
            <Typography sx={{ fontSize: 18, flex: 1 }}>{user?.organization_name || "Laundry Ops"}</Typography>
          )}
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mr: 0.5 }}>
          <Button size="small" variant={locale === "en" ? "contained" : "text"} onClick={() => setLocale("en")} sx={{ minWidth: 40 }}>EN</Button>
          <Button size="small" variant={locale === "es" ? "contained" : "text"} onClick={() => setLocale("es")} sx={{ minWidth: 40 }}>ES</Button>
        </Box>
        <IconButton size="small" onClick={() => window.location.reload()} aria-label={t("lang.label")}><Refresh sx={{ fontSize: 18 }} /></IconButton>
      </Toolbar>
    </AppBar>
  );
}

/** Public login: /login or /login/:orgSlug (tenant-specific bookmark URL). */
function isLoginRoute(path) {
  const p = path || "";
  return p === "/login" || p.startsWith("/login/");
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
    try { await authLogout(); } catch { /* ignore */ }
    clearAuthSession();
    setUser(null);
  };

  useEffect(() => {
    async function bootstrap() {
      if (isLoginRoute(pathname)) {
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
    const onRefresh = () => {
      authMe()
        .then((r) => setUser(r.data || null))
        .catch(() => {});
    };
    window.addEventListener("washpro-user-refresh", onRefresh);
    return () => window.removeEventListener("washpro-user-refresh", onRefresh);
  }, []);

  useEffect(() => {
    const onUpdateReady = () => setUpdateReady(true);
    window.addEventListener("washpro:update-ready", onUpdateReady);
    return () => window.removeEventListener("washpro:update-ready", onUpdateReady);
  }, []);

  useEffect(() => {
    if (isLoginRoute(pathname) || !user) {
      setActiveBatch(null);
      return;
    }
    async function loadBatch() {
      try {
        const res = await getCurrentUploadBatch();
        setActiveBatch(res?.data || null);
      } catch {
        setActiveBatch(null);
      }
    }
    loadBatch();
  }, [pathname, user]);

  const shellBackground = useMemo(
    () => "linear-gradient(145deg, #f8fbff 0%, #f2f6ff 45%, #f7fafc 100%)",
    []
  );

  if (authLoading && !isLoginRoute(pathname)) {
    return <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><Typography>Loading...</Typography></Box>;
  }

  if (!user && !isLoginRoute(pathname)) return <Navigate to="/login" replace />;

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", background: shellBackground }}>
      {!isMobile && user && <Sidebar activeBatch={activeBatch} user={user} onLogout={doLogout} />}
      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {isMobile && user && <MobileTopBar pathname={pathname} user={user} />}
        <Box sx={{ p: { xs: 0, md: 1 }, flex: 1, minWidth: 0, pb: { xs: "env(safe-area-inset-bottom, 0px)", md: 1 } }}>
          <Routes>
            <Route
              path="/login/:orgSlug"
              element={user ? <Navigate to="/" replace /> : <LoginPage onLoggedIn={setUser} />}
            />
            <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage onLoggedIn={setUser} />} />
            <Route path="/ta-login" element={<Navigate to="/" replace />} />
            <Route path="/time-clock" element={<Navigate to="/clock" replace />} />
            <Route path="/" element={<GuardedRoute user={user}><HomePage /></GuardedRoute>} />
            <Route path="/dashboard" element={<GuardedRoute user={user}><Dashboard /></GuardedRoute>} />
            <Route path="/orders" element={<GuardedRoute user={user}><OrdersPage user={user} /></GuardedRoute>} />
            <Route path="/checkout" element={<GuardedRoute user={user}><CheckoutPage user={user} /></GuardedRoute>} />
            <Route path="/upload" element={<GuardedRoute user={user} roles={["ADMIN", "OPS"]}><UploadPage /></GuardedRoute>} />
            <Route path="/employees" element={<GuardedRoute user={user} roles={["ADMIN"]}><PeoplePage user={user} /></GuardedRoute>} />
            <Route path="/clock" element={<GuardedRoute user={user}><ClockPage user={user} /></GuardedRoute>} />
            <Route path="/issues" element={<GuardedRoute user={user}><IssuePage /></GuardedRoute>} />
            <Route path="/production" element={<GuardedRoute user={user}><ProductionPage /></GuardedRoute>} />
            <Route path="/scoreboard" element={<GuardedRoute user={user}><ScoreboardPage /></GuardedRoute>} />
            <Route path="/maintenance" element={<GuardedRoute user={user}><MaintenancePage /></GuardedRoute>} />
            <Route path="/inventory" element={<GuardedRoute user={user}><InventoryPage user={user} /></GuardedRoute>} />
            <Route path="/discrepancies" element={<GuardedRoute user={user} roles={["ADMIN", "OPS"]}><DiscrepanciesPage /></GuardedRoute>} />
            <Route
              path="/payroll"
              element={
                <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                  <PayrollManagementPage />
                </GuardedRoute>
              }
            />
            <Route path="/payroll-monitor" element={<Navigate to="/payroll" replace />} />
            <Route path="/attendance-setup" element={<Navigate to="/payroll" replace />} />
            <Route
              path="/organization"
              element={
                <GuardedRoute user={user} roles={["ADMIN"]}>
                  <OrganizationSettingsPage />
                </GuardedRoute>
              }
            />
            <Route
              path="/permissions"
              element={
                <GuardedRoute user={user} roles={["ADMIN"]}>
                  <PermissionsPage />
                </GuardedRoute>
              }
            />
            <Route path="/ta-employees" element={<Navigate to="/employees" replace />} />
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
