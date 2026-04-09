import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Snackbar,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { ArrowBack, Logout, Menu, Refresh } from "@mui/icons-material";
import ClockInGate from "./components/ClockInGate";
import MobileTenantDrawer from "./components/MobileTenantDrawer";
import TenantNavAccessBoundary from "./components/TenantNavAccessBoundary";
import Sidebar from "./components/Sidebar";
import PlatformSidebar from "./components/PlatformSidebar";
import { useI18n } from "./i18n/I18nContext";
import { hasPlatformAdminRole, isPlatformOnlyUser, userSatisfiesRoleGate } from "./utils/platformAccess";

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
import NotificationsPage from "./pages/NotificationsPage";
import OrganizationSettingsPage from "./pages/OrganizationSettingsPage";
import OrganizationsPlatformPage from "./pages/OrganizationsPlatformPage";
import PlatformAdminPage from "./pages/PlatformAdminPage";
import UserProfilePage from "./pages/UserProfilePage";
import PayrollFormsHubPage from "./pages/PayrollFormsHubPage";
import DocumentsEvidencePage from "./pages/DocumentsEvidencePage";
import { authLogout, authMe, clearAuthSession, getClockPayrollUiSettings, getCurrentUploadBatch, getSavedUser } from "./api";
import { useAuth } from "./context/AuthContext";

function MobileTopBar({ pathname, user, onOpenNav, onLogout }) {
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
        <IconButton size="small" onClick={onOpenNav} aria-label="Menu" sx={{ mr: 0.5 }}>
          <Menu sx={{ fontSize: 22 }} />
        </IconButton>
        {canGoBack ? (
          <IconButton size="small" onClick={() => navigate(-1)} sx={{ mr: 1 }}><ArrowBack sx={{ fontSize: 18 }} /></IconButton>
        ) : <Box sx={{ width: 8 }} />}
        <Box
          sx={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            minHeight: 28,
            overflow: "hidden",
          }}
        >
          {user?.organization_logo_url ? (
            <Box
              component="img"
              src={user.organization_logo_url}
              alt=""
              sx={{
                height: 24,
                maxHeight: 24,
                width: "auto",
                maxWidth: 150,
                objectFit: "contain",
                objectPosition: "left center",
                display: "block",
              }}
            />
          ) : (
            <Typography sx={{ fontSize: 18, flex: 1 }}>{user?.organization_name || "Laundry Ops"}</Typography>
          )}
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mr: 0.5 }}>
          <Button size="small" variant={locale === "en" ? "contained" : "text"} onClick={() => setLocale("en")} sx={{ minWidth: 40 }}>EN</Button>
          <Button size="small" variant={locale === "es" ? "contained" : "text"} onClick={() => setLocale("es")} sx={{ minWidth: 40 }}>ES</Button>
        </Box>
        <IconButton size="small" onClick={onLogout} aria-label={t("nav.logout")} sx={{ mr: 0.25 }}>
          <Logout sx={{ fontSize: 18 }} />
        </IconButton>
        <IconButton size="small" onClick={() => window.location.reload()} aria-label={t("common.refresh")}><Refresh sx={{ fontSize: 18 }} /></IconButton>
      </Toolbar>
    </AppBar>
  );
}

/** Public login: /login or /login/:orgSlug (tenant-specific bookmark URL). */
function isLoginRoute(path) {
  const p = path || "";
  return p === "/login" || p.startsWith("/login/");
}

function GuardedRoute({ user, roles, permissionAnyOf, children }) {
  const { hasPerm, loading: authLoading } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  const roleOk = !roles?.length || userSatisfiesRoleGate(user, roles);
  if (roleOk) return children;
  if (permissionAnyOf?.length) {
    if (authLoading) {
      return (
        <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
          <CircularProgress size={28} />
        </Box>
      );
    }
    if (permissionAnyOf.some((k) => hasPerm(k))) return children;
  }
  return <Navigate to="/" replace />;
}

function TenantOnlyRoute({ user, children }) {
  if (!user) return <Navigate to="/login" replace />;
  if (isPlatformOnlyUser(user)) return <Navigate to="/platform" replace />;
  return children;
}

function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const [updateReady, setUpdateReady] = useState(false);
  const [activeBatch, setActiveBatch] = useState(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [payrollNavVisible, setPayrollNavVisible] = useState(true);
  const [user, setUser] = useState(getSavedUser());
  const [authLoading, setAuthLoading] = useState(true);
  /** Avoid calling GET /auth/me on every client-side navigation (was a major local slowness). */
  const washproSessionSyncedRef = useRef(false);

  const pathname = location.pathname || "/";

  const doLogout = async () => {
    try { await authLogout(); } catch { /* ignore */ }
    clearAuthSession();
    washproSessionSyncedRef.current = false;
    setUser(null);
  };

  useEffect(() => {
    if (!user) washproSessionSyncedRef.current = false;
  }, [user]);

  useEffect(() => {
    async function bootstrap() {
      if (isLoginRoute(pathname)) {
        setAuthLoading(false);
        return;
      }
      if (washproSessionSyncedRef.current) {
        setAuthLoading(false);
        return;
      }
      try {
        setAuthLoading(true);
        const res = await authMe();
        setUser(res.data || null);
        washproSessionSyncedRef.current = true;
      } catch (e) {
        console.error(e);
        clearAuthSession();
        setUser(null);
        washproSessionSyncedRef.current = false;
      } finally {
        setAuthLoading(false);
      }
    }
    bootstrap();
  }, [pathname]);

  useEffect(() => {
    const onRefresh = () => {
      authMe()
        .then((r) => {
          setUser(r.data || null);
          washproSessionSyncedRef.current = true;
        })
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
    if (isLoginRoute(pathname) || !user?.id) {
      setActiveBatch(null);
    }
  }, [pathname, user?.id]);

  useEffect(() => {
    if (!user?.id || isPlatformOnlyUser(user)) return;
    getClockPayrollUiSettings()
      .then((res) => {
        const v = res.data?.payroll?.nav_payroll_visible;
        setPayrollNavVisible(v !== false);
      })
      .catch(() => setPayrollNavVisible(true));
  }, [user?.id]);

  const refreshUploadBatchBadge = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await getCurrentUploadBatch();
      setActiveBatch(res?.data || null);
    } catch {
      setActiveBatch(null);
    }
  }, [user?.id]);

  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    let intervalId;
    /** Stagger after auth / TA identity calls so the first paint does fewer parallel DB round-trips. */
    const t = window.setTimeout(() => {
      if (cancelled) return;
      refreshUploadBatchBadge();
      intervalId = window.setInterval(refreshUploadBatchBadge, 120000);
    }, 150);
    const onBatchChanged = () => refreshUploadBatchBadge();
    window.addEventListener("washpro-upload-batch-changed", onBatchChanged);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
      if (intervalId) window.clearInterval(intervalId);
      window.removeEventListener("washpro-upload-batch-changed", onBatchChanged);
    };
  }, [user?.id, refreshUploadBatchBadge]);

  useEffect(() => {
    if (authLoading || isLoginRoute(pathname) || !user) return;
    if (isPlatformOnlyUser(user) && pathname !== "/platform" && !pathname.startsWith("/platform/")) {
      navigate("/platform", { replace: true });
    }
  }, [authLoading, pathname, user, navigate]);

  const shellBackground = useMemo(
    () => "linear-gradient(145deg, #f8fbff 0%, #f2f6ff 45%, #f7fafc 100%)",
    []
  );

  if (authLoading && !isLoginRoute(pathname)) {
    return <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><Typography>Loading...</Typography></Box>;
  }

  if (!user && !isLoginRoute(pathname)) return <Navigate to="/login" replace />;

  if (user && isPlatformOnlyUser(user) && !isLoginRoute(pathname)) {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", background: shellBackground }}>
        {!isMobile && <PlatformSidebar user={user} onLogout={doLogout} />}
        <Box sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {isMobile && (
            <AppBar position="sticky" elevation={0} sx={{ borderBottom: "1px solid #e2e8f0", bgcolor: "#fff", color: "#1e1b4b" }}>
              <Toolbar sx={{ minHeight: 48 }}>
                <Typography sx={{ flex: 1, fontWeight: 700 }}>Platform</Typography>
                <Button size="small" onClick={doLogout}>Logout</Button>
              </Toolbar>
            </AppBar>
          )}
          <Box sx={{ p: { xs: 0, md: 1 }, flex: 1, minWidth: 0 }}>
            <Routes>
              <Route
                path="/platform"
                element={
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <PlatformAdminPage />
                  </GuardedRoute>
                }
              />
              <Route path="/platform/organizations" element={<OrganizationsPlatformPage />} />
              <Route
                path="/platform/users/:userId"
                element={
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/platform" replace />} />
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

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", background: shellBackground }}>
      {!isMobile && user && (pathname.startsWith("/platform") && hasPlatformAdminRole(user) ? (
        <PlatformSidebar user={user} onLogout={doLogout} showTenantEntry />
      ) : (
        <Sidebar activeBatch={activeBatch} user={user} onLogout={doLogout} />
      ))}
      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {isMobile && user && (
          <>
            <MobileTenantDrawer
              open={mobileNavOpen}
              onClose={() => setMobileNavOpen(false)}
              user={user}
              payrollNavVisible={payrollNavVisible}
              activeBatch={activeBatch}
              onLogout={doLogout}
            />
            <MobileTopBar pathname={pathname} user={user} onOpenNav={() => setMobileNavOpen(true)} onLogout={doLogout} />
          </>
        )}
        <Box sx={{ p: { xs: 0, md: 1 }, flex: 1, minWidth: 0, pb: { xs: "env(safe-area-inset-bottom, 0px)", md: 1 } }}>
          <ClockInGate user={user}>
          <TenantNavAccessBoundary user={user} payrollNavVisible={payrollNavVisible}>
          <Routes>
            <Route
              path="/login/:orgSlug"
              element={user ? <Navigate to="/" replace /> : <LoginPage onLoggedIn={setUser} />}
            />
            <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage onLoggedIn={setUser} />} />
            <Route path="/ta-login" element={<Navigate to="/" replace />} />
            <Route path="/time-clock" element={<Navigate to="/clock" replace />} />
            <Route path="/" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><HomePage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/dashboard" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><Dashboard /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/orders" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><OrdersPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/checkout" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><CheckoutPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/upload"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute
                    user={user}
                    roles={["ADMIN", "OPS", "UPLOAD"]}
                    permissionAnyOf={["upload.view", "upload.create"]}
                  >
                    <UploadPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/employees" element={<TenantOnlyRoute user={user}><GuardedRoute user={user} roles={["ADMIN"]}><PeoplePage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/documents"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <DocumentsEvidencePage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/employees/:userId/hr"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <PayrollFormsHubPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/employees/:userId"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/clock" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ClockPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/issues" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><IssuePage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/production" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ProductionPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/scoreboard" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ScoreboardPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/maintenance" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><MaintenancePage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/inventory" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><InventoryPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/discrepancies" element={<TenantOnlyRoute user={user}><GuardedRoute user={user} roles={["ADMIN", "OPS"]}><DiscrepanciesPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/payroll"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <PayrollManagementPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/payroll-monitor" element={<Navigate to="/payroll" replace />} />
            <Route path="/attendance-setup" element={<Navigate to="/payroll" replace />} />
            <Route
              path="/organization"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <OrganizationSettingsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/notifications"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <NotificationsPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform/organizations"
              element={
                <TenantOnlyRoute user={user}>
                  <OrganizationsPlatformPage />
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <PlatformAdminPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform/users/:userId"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/permissions"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <PermissionsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/ta-employees" element={<Navigate to="/employees" replace />} />
          </Routes>
          </TenantNavAccessBoundary>
          </ClockInGate>
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
